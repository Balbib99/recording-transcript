"""Worker de transcripcion: pide trabajo a la Pi, lo transcribe con la GPU y devuelve el resultado.

La API de la Pi solo escucha en su loopback, asi que el worker abre el tunel SSH
el mismo y lo reabre si se cae. Para el usuario es un unico proceso.

    python worker/worker.py             # bucle continuo
    python worker/worker.py --once      # un solo trabajo y sale
    python worker/worker.py --estado    # que hay en la cola

Configuracion en worker/.env (ver .env.example). Los ajustes de transcripcion
(modelo, idioma, diarizacion) salen del config.toml del proyecto, el mismo que
usa el CLI.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comun import (  # noqa: E402
    API_TOKEN, API_URL, ESPERA, RAIZ, WORKER, Tunel, api, esperar_api, log,
)

from recordingcraft import outputs, speakers as spk, store  # noqa: E402
from recordingcraft.config import load_config  # noqa: E402


# ---------------------------------------------------------------------- API

def reclamar() -> dict[str, Any] | None:
    r = api("POST", "/api/worker/reclamar", data={"worker": WORKER})
    r.raise_for_status()
    return r.json().get("trabajo")


def descargar_audio(job: dict[str, Any], destino: Path) -> Path:
    with api("GET", f"/api/jobs/{job['id']}/audio", stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(destino, "wb") as fichero:
            for trozo in r.iter_content(chunk_size=1024 * 1024):
                fichero.write(trozo)
    return destino


# ------------------------------------------------------------- transcripcion

def construir_resultado(job: dict[str, Any], datos: dict[str, Any],
                        carpeta: Path, cfg) -> dict[str, Any]:
    """Empaqueta lo que devuelve el pipeline en el JSON que guarda la Pi."""
    datos = dict(datos)
    datos["id"] = job["id"]
    datos["title"] = job["titulo"]
    datos["source_file"] = job["fichero"]
    datos["recorded_at"] = job["creado"]

    reunion = store.Meeting(path=carpeta, data=datos)
    mapeo: dict[str, str] = {}   # sin renombrar: los nombres se ponen luego
    hueco = float(cfg.output.get("merge_gap_seconds", 1.5))

    turnos = outputs.merge_turns(reunion.segments, mapeo, hueco)
    estadisticas = spk.stats(reunion.segments, mapeo)

    return {
        "id": job["id"],
        "titulo": job["titulo"],
        "idioma": datos.get("language"),
        "duracion": datos.get("duration"),
        "modelo": datos.get("model"),
        "diarizacion": datos.get("diarization"),
        "procesado_por": WORKER,
        "procesado_en": datos.get("processed_at"),
        "segundos_de_proceso": datos.get("processing_seconds"),
        "hablantes": [
            {"etiqueta": s.label, "nombre": s.name, "segundos": round(s.seconds, 2),
             "intervenciones": s.turns, "palabras": s.words}
            for s in estadisticas
        ],
        "turnos": [
            {"hablante": t.label, "inicio": round(t.start, 2),
             "fin": round(t.end, 2), "texto": t.text}
            for t in turnos
        ],
        "segmentos": datos.get("segments", []),
    }


def procesar(job: dict[str, Any], cfg) -> None:
    log(f"trabajo {job['id']}: {job['titulo']} ({job['bytes'] / 1e6:.1f} MB)")
    from recordingcraft import pipeline

    with tempfile.TemporaryDirectory(prefix="rc-worker-") as tmp:
        carpeta = Path(tmp)
        audio = carpeta / f"audio{Path(job['fichero']).suffix or '.m4a'}"
        log("  descargando audio")
        descargar_audio(job, audio)

        datos = pipeline.transcribe(audio, cfg, lambda m: log(f"  {m.strip()}"))
        resultado = construir_resultado(job, datos, carpeta, cfg)

        log("  enviando resultado")
        r = api("POST", f"/api/jobs/{job['id']}/resultado", json=resultado, timeout=300)
        r.raise_for_status()

    hablantes = len(resultado["hablantes"])
    log(f"  listo: {hablantes} hablante(s), {len(resultado['turnos'])} intervenciones")


# ------------------------------------------------------------------- bucles

def ciclo(cfg, tunel: Tunel, una_vez: bool) -> int:
    procesados = 0
    while True:
        try:
            tunel.abrir()
            job = reclamar()
        except Exception as exc:
            log(f"! no se pudo contactar con la API: {exc}")
            if una_vez:
                return 1
            time.sleep(ESPERA)
            continue

        if job is None:
            if una_vez:
                log("no hay nada pendiente")
                return 0
            time.sleep(ESPERA)
            continue

        try:
            procesar(job, cfg)
            procesados += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log(f"! fallo al procesar {job['id']}: {exc}")
            traceback.print_exc()
            try:
                api("POST", f"/api/jobs/{job['id']}/fallo",
                    data={"error": f"{type(exc).__name__}: {exc}"})
            except Exception as exc2:
                log(f"! tampoco se pudo avisar del fallo: {exc2}")

        if una_vez:
            return 0


def mostrar_estado() -> int:
    tunel = Tunel()
    try:
        tunel.abrir()
        if not esperar_api():
            log("la API no responde")
            return 1
        estado = api("GET", "/api/estado").json()
        log(f"cola: {estado['trabajos']}")
        log(f"disco: {estado['bytes_en_disco'] / 1e6:.1f} MB")
        trabajos = api("GET", "/api/jobs", params={"limite": 10}).json()["trabajos"]
        for t in trabajos:
            log(f"  {t['id']}  {t['estado']:<11} {t['titulo']}")
        return 0
    finally:
        tunel.cerrar()


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker de transcripcion de RecordingCraft")
    parser.add_argument("--once", action="store_true", help="procesa un trabajo y termina")
    parser.add_argument("--estado", action="store_true", help="muestra la cola y sale")
    parser.add_argument("--sin-tunel", action="store_true",
                        help="no abrir tunel SSH (la API ya es accesible)")
    args = parser.parse_args()

    if not API_TOKEN:
        log("Falta RC_API_TOKEN en worker/.env")
        return 1

    if args.estado:
        return mostrar_estado()

    cfg = load_config()
    log(f"worker '{WORKER}' contra {API_URL}")
    log(f"modelo={cfg.whisper['model']} device={cfg.whisper['device']} "
        f"diarizacion={'si' if cfg.diarization.get('enabled') else 'no'}")

    tunel = Tunel(host="" if args.sin_tunel else None)

    try:
        tunel.abrir()
        if not esperar_api():
            log(f"la API no responde en {API_URL}")
            return 1
        return ciclo(cfg, tunel, args.once)
    except KeyboardInterrupt:
        log("interrumpido")
        return 130
    finally:
        tunel.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
