"""Rescate de tramos que la transcripcion por lotes pierde.

WhisperX transcribe por lotes: corta el audio en ventanas de hasta 30 s y las
descodifica a la vez, sin reintentos. Va rapido, pero cuando una ventana sale
mal no hay segunda oportunidad, y pasan dos cosas:

  - Whisper "alucina" frases de los subtitulos de YouTube con los que se
    entreno ("¡Suscribete!", "Gracias por ver este video") en lugar de lo que
    se dijo. Parece un video de fondo, pero es voz real que se ha perdido.
  - Trozos con voz se quedan sin texto, o con dos palabras para 25 segundos.

Aqui se buscan esos tramos y se vuelven a transcribir de uno en uno, con el
metodo clasico de Whisper: busqueda en haz y reintentos a mas temperatura si
el resultado no convence. Es mas lento, pero solo se aplica a lo sospechoso.

Las funciones de deteccion no necesitan GPU ni modelos, y tienen tests.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterable

SAMPLE_RATE = 16000

# Frases que Whisper inventa sobre ruido o silencio, sacadas de subtitulos de
# videos. Se comparan sin tildes ni mayusculas.
ALUCINACIONES = [
    r"suscribete", r"suscribanse", r"suscribirte al canal",
    r"gracias por ver",
    r"gracias por (su|vuestra) atencion",
    r"subtitul(os|ado) (realizados? )?por",
    r"amara\.org",
    r"comunidad de amara",
    r"no olvides? (dar|darle|de) (like|me gusta|suscrib)",
    r"dale (a )?like",
    r"activa la campanita",
    r"nos vemos en el (proximo|siguiente) video",
    r"hasta el proximo video",
]
_ALUCINACION = re.compile("|".join(ALUCINACIONES))

# Por debajo de esto, un segmento largo tiene "demasiado poco texto": se habla
# a unos 12-15 caracteres por segundo.
SEGMENTO_LARGO = 8.0       # segundos
CARACTERES_MINIMOS = 3.0   # por segundo

# Un hueco entre segmentos se revisa si dura esto y tiene voz.
HUECO_MINIMO = 6.0         # segundos
NIVEL_VOZ = -48.0          # dBFS de una ventana de medio segundo
PROPORCION_VOZ = 0.25      # parte del hueco por encima de ese nivel

# Resultados del rescate que se descartan: Whisper los marca como poco fiables.
NO_SPEECH_MAX = 0.6
LOGPROB_MIN = -1.0


@dataclass
class Tramo:
    start: float
    end: float
    motivo: str

    def como_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2),
                "motivo": self.motivo}


def _plano(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.lower()


def es_alucinacion(texto: str) -> bool:
    return bool(_ALUCINACION.search(_plano(texto)))


def quitar_alucinaciones(texto: str) -> str:
    """Quita solo las frases inventadas y deja el resto del segmento."""
    frases = re.split(r"(?<=[.!?])\s+|\s+(?=[¡¿])", texto.strip())
    return " ".join(f for f in frases if f and not es_alucinacion(f)).strip()


def es_repeticion(texto: str) -> bool:
    """'Y... Y... Y...' o 'no no no no': casi todo es la misma palabra."""
    palabras = re.findall(r"\w+", _plano(texto))
    if len(palabras) < 3:
        return False
    mas_comun = max(palabras.count(p) for p in set(palabras))
    return mas_comun >= 3 and mas_comun / len(palabras) >= 0.75


def es_escaso(seg: dict) -> bool:
    duracion = float(seg["end"]) - float(seg["start"])
    texto = (seg.get("text") or "").strip()
    return duracion >= SEGMENTO_LARGO and len(texto) / duracion < CARACTERES_MINIMOS


def proporcion_voz(wave: Any, start: float, end: float) -> float:
    """Parte del tramo [start, end] con nivel de voz, en ventanas de 0,5 s."""
    import numpy as np

    trozo = wave[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
    paso = SAMPLE_RATE // 2
    n = len(trozo) // paso
    if n == 0:
        return 0.0
    ventanas = np.asarray(trozo[:n * paso], dtype=np.float32).reshape(n, paso)
    rms = np.sqrt(np.mean(ventanas ** 2, axis=1)) + 1e-10
    db = 20 * np.log10(rms)
    return float(np.mean(db > NIVEL_VOZ))


def buscar_tramos(segmentos: list[dict], wave: Any, duracion: float) -> list[Tramo]:
    """Tramos sospechosos: segmentos raros y huecos con voz, ya fusionados."""
    tramos: list[Tramo] = []
    for seg in segmentos:
        texto = seg.get("text") or ""
        ini, fin = float(seg["start"]), float(seg["end"])
        if es_alucinacion(texto):
            tramos.append(Tramo(ini, fin, "alucinacion"))
        elif es_repeticion(texto):
            tramos.append(Tramo(ini, fin, "repeticion"))
        elif es_escaso(seg):
            tramos.append(Tramo(ini, fin, "poco texto"))

    bordes = [0.0] + [x for s in segmentos for x in (float(s["start"]), float(s["end"]))] + [duracion]
    for i in range(0, len(bordes), 2):
        ini, fin = bordes[i], bordes[i + 1]
        if fin - ini >= HUECO_MINIMO and proporcion_voz(wave, ini, fin) >= PROPORCION_VOZ:
            tramos.append(Tramo(ini, fin, "hueco con voz"))

    return fusionar(tramos)


def fusionar(tramos: Iterable[Tramo], separacion: float = 1.0) -> list[Tramo]:
    """Une tramos solapados o casi pegados, para transcribirlos de una vez."""
    unidos: list[Tramo] = []
    for t in sorted(tramos, key=lambda t: t.start):
        if unidos and t.start - unidos[-1].end <= separacion:
            ultimo = unidos[-1]
            ultimo.end = max(ultimo.end, t.end)
            if t.motivo not in ultimo.motivo.split(" + "):
                ultimo.motivo += " + " + t.motivo
        else:
            unidos.append(Tramo(t.start, t.end, t.motivo))
    return unidos


def fiable(seg: Any) -> bool:
    texto = (getattr(seg, "text", "") or "").strip()
    if not texto or es_alucinacion(texto):
        return False
    return not (seg.no_speech_prob > NO_SPEECH_MAX and seg.avg_logprob < LOGPROB_MIN)


def sustituir(segmentos: list[dict], tramo: Tramo, nuevos: list[dict]) -> list[dict]:
    """Quita los segmentos cuyo centro cae en el tramo y mete los rescatados.

    Si el rescate no saca nada, solo se quitan las repeticiones; las frases
    inventadas las limpia despues limpiar(), y un segmento con poco texto se
    deja como estaba.
    """
    def dentro(s: dict) -> bool:
        centro = (float(s["start"]) + float(s["end"])) / 2
        return tramo.start <= centro <= tramo.end

    if not nuevos:
        return [s for s in segmentos
                if not (dentro(s) and es_repeticion(s.get("text") or ""))]
    resto = [s for s in segmentos if not dentro(s)]
    return sorted(resto + nuevos, key=lambda s: float(s["start"]))


def rescatar(segmentos: list[dict], wave: Any, duracion: float,
             transcribir: Callable[[Any], Iterable[Any]],
             log: Callable[[str], None]) -> tuple[list[dict], list[dict]]:
    """Revisa los tramos sospechosos. Devuelve (segmentos, tramos revisados).

    `transcribir` recibe el audio del tramo y devuelve segmentos de
    faster-whisper (con start, end, text, no_speech_prob y avg_logprob).
    """
    tramos = buscar_tramos(segmentos, wave, duracion)
    if not tramos:
        return segmentos, []
    total = sum(t.end - t.start for t in tramos)
    log(f"  · revisando {len(tramos)} tramo(s) dudoso(s) ({total:.0f} s)")

    revisados = []
    for tramo in tramos:
        trozo = wave[int(tramo.start * SAMPLE_RATE):int(tramo.end * SAMPLE_RATE)]
        nuevos = [
            {"start": round(tramo.start + s.start, 3),
             "end": round(min(tramo.end, tramo.start + s.end), 3),
             "text": s.text.strip()}
            for s in transcribir(trozo) if fiable(s)
        ]
        segmentos = sustituir(segmentos, tramo, nuevos)
        info = tramo.como_dict()
        info["segmentos"] = len(nuevos)
        revisados.append(info)
        log(f"    {info['start']:.0f}-{info['end']:.0f} s ({tramo.motivo}): "
            f"{len(nuevos)} segmento(s)")

    return limpiar(segmentos), revisados


def limpiar(segmentos: list[dict]) -> list[dict]:
    """Quita las frases inventadas que hayan sobrevivido, y los segmentos vacios."""
    limpios = []
    for s in segmentos:
        texto = s.get("text") or ""
        if es_alucinacion(texto):
            texto = quitar_alucinaciones(texto)
            if not texto:
                continue
            s = {**s, "text": texto}
        limpios.append(s)
    return limpios
