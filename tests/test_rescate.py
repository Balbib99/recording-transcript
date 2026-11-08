"""Tests del rescate de tramos: sin GPU ni modelos, con audio sintetico."""

from types import SimpleNamespace

import numpy as np

from recordingcraft import rescate as r

SR = r.SAMPLE_RATE


def audio(duracion: float, voz: list[tuple[float, float]]) -> np.ndarray:
    """Silencio con tramos de 'voz' (ruido a unos -30 dBFS)."""
    wave = np.zeros(int(duracion * SR), dtype=np.float32)
    rng = np.random.default_rng(0)
    for ini, fin in voz:
        n = int((fin - ini) * SR)
        wave[int(ini * SR):int(ini * SR) + n] = rng.normal(0, 0.03, n)
    return wave


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


def fw(start, end, text, no_speech=0.1, logprob=-0.3):
    return SimpleNamespace(start=start, end=end, text=text,
                           no_speech_prob=no_speech, avg_logprob=logprob)


def test_alucinaciones_tipicas():
    assert r.es_alucinacion("¡SUSCRIBETE!")
    assert r.es_alucinacion("¡Gracias por ver este vídeo!")
    assert r.es_alucinacion("Subtítulos realizados por la comunidad de Amara.org")
    assert not r.es_alucinacion("Hay que suscribir el contrato con el cliente")
    assert not r.es_alucinacion("Gracias, Luis")


def test_quitar_alucinaciones_conserva_lo_demas():
    texto = "Ahí están los AnyDesk, las contraseñas. ¡Gracias por ver este vídeo! ¡Suscríbete al canal!"
    assert r.quitar_alucinaciones(texto) == "Ahí están los AnyDesk, las contraseñas."


def test_repeticion():
    assert r.es_repeticion("Y... Y... Y...")
    assert not r.es_repeticion("y y y este que no me deja generar el vínculo")


def test_busca_segmentos_raros_y_huecos_con_voz():
    wave = audio(100, [(0, 100)])
    segmentos = [
        seg(0, 20, "Texto normal " * 20),
        seg(20, 45, "¡SUSCRIBETE!"),                 # alucinacion
        seg(45, 60, "Texto normal " * 15),
        # hueco 60-75 con voz
        seg(75, 100, "Texto normal " * 25),
    ]
    tramos = r.buscar_tramos(segmentos, wave, 100)
    assert [(t.start, t.end) for t in tramos] == [(20, 45), (60, 75)]
    assert tramos[0].motivo == "alucinacion"
    assert tramos[1].motivo == "hueco con voz"


def test_hueco_en_silencio_no_se_revisa():
    wave = audio(60, [(0, 20), (40, 60)])
    segmentos = [seg(0, 20, "Texto normal " * 20), seg(40, 60, "Texto normal " * 20)]
    assert r.buscar_tramos(segmentos, wave, 60) == []


def test_segmento_largo_con_poco_texto():
    wave = audio(30, [(0, 30)])
    tramos = r.buscar_tramos([seg(0, 25, "Y luego"), seg(25, 30, "fin de la frase")], wave, 30)
    assert [(t.start, t.end, t.motivo) for t in tramos] == [(0, 25, "poco texto")]


def test_fusiona_tramos_pegados():
    unidos = r.fusionar([r.Tramo(10, 20, "alucinacion"), r.Tramo(20.5, 30, "hueco con voz"),
                         r.Tramo(40, 50, "poco texto")])
    assert [(t.start, t.end) for t in unidos] == [(10, 30), (40, 50)]
    assert unidos[0].motivo == "alucinacion + hueco con voz"


def test_rescatar_sustituye_y_filtra():
    wave = audio(60, [(0, 60)])
    segmentos = [seg(0, 20, "Texto normal " * 20), seg(20, 45, "¡SUSCRIBETE!"),
                 seg(45, 60, "Texto normal " * 15)]

    def transcribir(trozo, con_vocabulario):
        assert len(trozo) == 25 * SR
        return [fw(0, 10, " es decir, un remoto y una presencial"),
                fw(10, 15, " ¡Suscríbete!"),                          # inventada
                fw(15, 25, " ruido", no_speech=0.9, logprob=-1.5)]    # poco fiable

    nuevos, revisados = r.rescatar(segmentos, wave, 60, transcribir, lambda _: None)
    assert [s["text"] for s in nuevos] == [
        segmentos[0]["text"],
        "es decir, un remoto y una presencial",
        segmentos[2]["text"],
    ]
    assert nuevos[1]["start"] == 20 and nuevos[1]["end"] == 30
    assert revisados == [{"start": 20, "end": 45, "motivo": "alucinacion", "segmentos": 1}]


def test_si_el_rescate_no_saca_nada_se_borra_la_alucinacion():
    wave = audio(30, [(0, 30)])
    segmentos = [seg(0, 20, "Texto normal " * 20), seg(20, 30, "¡Gracias por ver este vídeo!")]
    nuevos, _ = r.rescatar(segmentos, wave, 30, lambda trozo, voc: [], lambda _: None)
    assert [s["text"] for s in nuevos] == [segmentos[0]["text"]]


def test_reintenta_sin_vocabulario_si_delira():
    wave = audio(30, [(0, 30)])
    segmentos = [seg(0, 20, "Texto normal " * 20), seg(20, 30, "¡Suscríbete!")]
    llamadas = []

    def transcribir(trozo, con_vocabulario):
        llamadas.append(con_vocabulario)
        if con_vocabulario:
            return [fw(0, 10, " NVR, NVR, NVR, NVR, NVR")]
        return [fw(0, 10, " a lo mejor por ser muy grande")]

    nuevos, _ = r.rescatar(segmentos, wave, 30, transcribir, lambda _: None)
    assert llamadas == [True, False]
    assert nuevos[-1]["text"] == "a lo mejor por ser muy grande"
