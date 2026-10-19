"""API de RecordingCraft: recibe grabaciones y mantiene la cola de trabajos.

Fase 3: subir, listar, consultar y descargar el audio. La transcripcion la hara
el worker del PC en la fase siguiente, pidiendo trabajo a esta misma API.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Annotated, Any

from contextlib import asynccontextmanager

from fastapi import (
    Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, status,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config, db, render


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Comprobaciones de arranque: sin token, el servicio no debe levantarse."""
    if not config.API_TOKEN:
        raise RuntimeError("Falta RC_API_TOKEN. Generalo con: openssl rand -hex 32")
    db.inicializar()
    yield


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="RecordingCraft",
    description="Cola de transcripcion de reuniones",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)


# ------------------------------------------------------------- autenticacion

def exigir_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Token compartido en la cabecera Authorization: Bearer <token>."""
    esperado = f"Bearer {config.API_TOKEN}"
    # Comparacion en tiempo constante: no filtra el token caracter a caracter.
    if not authorization or not secrets.compare_digest(authorization, esperado):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


Protegido = Depends(exigir_token)


# -------------------------------------------------------------------- utiles

def nombre_seguro(nombre: str) -> str:
    """Nombre de fichero sin sorpresas: ni rutas, ni caracteres raros."""
    base = Path(nombre or "grabacion").name
    base = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip()
    return base[:120] or "grabacion"


def ruta_audio(job: dict[str, Any]) -> Path:
    return config.AUDIO_DIR / f"{job['id']}{job['extension']}"


def publico(job: dict[str, Any]) -> dict[str, Any]:
    """Representacion que se devuelve al cliente."""
    return {
        "id": job["id"],
        "titulo": job["titulo"] or Path(job["fichero"]).stem,
        "fichero": job["fichero"],
        "estado": job["estado"],
        "bytes": job["bytes"],
        "creado": job["creado"],
        "terminado": job["terminado"],
        "duracion": job["duracion"],
        "hablantes": job["hablantes"],
        "idioma": job["idioma"],
        "error": job["error"],
    }


# ------------------------------------------------------------------ endpoints

@app.get("/api/health")
def salud() -> dict[str, Any]:
    """Sin autenticacion: sirve para comprobar que el servicio esta vivo."""
    return {"ok": True, "version": app.version}


@app.get("/api/estado", dependencies=[Protegido])
def estado() -> dict[str, Any]:
    conteo = db.contar_por_estado()
    uso = sum(f.stat().st_size for f in config.AUDIO_DIR.glob("*") if f.is_file())
    return {"trabajos": conteo, "bytes_en_disco": uso}


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED, dependencies=[Protegido])
async def subir(
    file: Annotated[UploadFile, File(description="Fichero de audio")],
    titulo: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Recibe una grabacion y la encola.

    El fichero se escribe por trozos para no cargarlo entero en memoria: en la
    Pi, una reunion larga se comeria la RAM.
    """
    extension = Path(file.filename or "").suffix.lower()
    if extension not in config.EXTENSIONES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Extension no admitida: '{extension}'. "
                   f"Validas: {', '.join(sorted(config.EXTENSIONES))}",
        )

    config.crear_directorios()
    temporal = config.AUDIO_DIR / f".subiendo-{db.nuevo_id()}{extension}"
    digest = hashlib.sha256()
    escritos = 0

    try:
        with open(temporal, "wb") as destino:
            while trozo := await file.read(1024 * 1024):
                escritos += len(trozo)
                if escritos > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"El fichero supera {config.MAX_UPLOAD_MB} MB",
                    )
                digest.update(trozo)
                destino.write(trozo)
    except Exception:
        temporal.unlink(missing_ok=True)
        raise

    if escritos == 0:
        temporal.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="El fichero esta vacio")

    sha = digest.hexdigest()

    # Mismo audio subido dos veces: se devuelve el trabajo que ya existe.
    existente = db.buscar_por_sha(sha)
    if existente:
        temporal.unlink(missing_ok=True)
        return {**publico(existente), "duplicado": True}

    job = db.crear_job(
        titulo=titulo.strip() if titulo else None,
        fichero=nombre_seguro(file.filename or "grabacion"),
        extension=extension,
        bytes_=escritos,
        sha256=sha,
    )
    temporal.rename(ruta_audio(job))
    return {**publico(job), "duplicado": False}


@app.get("/api/jobs", dependencies=[Protegido])
def listar(
    estado: Annotated[str | None, Query(description="pendiente|procesando|hecho|fallido")] = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if estado and estado not in db.ESTADOS:
        raise HTTPException(status_code=400, detail=f"Estado invalido: {estado}")
    trabajos = db.listar_jobs(estado, limite, desplazamiento)
    return {"total": len(trabajos), "trabajos": [publico(j) for j in trabajos]}


@app.get("/api/jobs/{job_id}", dependencies=[Protegido])
def detalle(job_id: str) -> dict[str, Any]:
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    datos = publico(job)
    resultado = config.RESULT_DIR / f"{job_id}.json"
    datos["transcripcion_disponible"] = resultado.is_file()
    return datos


@app.get("/api/jobs/{job_id}/audio", dependencies=[Protegido])
def descargar_audio(job_id: str) -> FileResponse:
    """Lo usara el worker para bajarse la grabacion que va a transcribir."""
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    ruta = ruta_audio(job)
    if not ruta.is_file():
        raise HTTPException(status_code=410, detail="El audio ya no esta en disco")
    return FileResponse(ruta, filename=job["fichero"])


@app.get("/api/jobs/{job_id}/transcripcion", dependencies=[Protegido])
def transcripcion(job_id: str) -> dict[str, Any]:
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    ruta = config.RESULT_DIR / f"{job_id}.json"
    if not ruta.is_file():
        raise HTTPException(
            status_code=409,
            detail=f"Todavia no hay transcripcion (estado: {job['estado']})",
        )
    return json.loads(ruta.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- worker
# Lo que usa el equipo con GPU: pide trabajo, lo transcribe y devuelve el
# resultado. Mismo token que el resto de la API.

@app.post("/api/worker/reclamar", dependencies=[Protegido])
def reclamar(worker: Annotated[str, Form()] = "worker") -> dict[str, Any]:
    """Entrega el trabajo pendiente mas antiguo, o nada si la cola esta vacia.

    Devuelve 200 con `trabajo: null` en lugar de 404 porque "no hay nada que
    hacer" es la respuesta normal, no un error: el worker pregunta cada pocos
    segundos.
    """
    job = db.reclamar_siguiente(worker.strip()[:60] or "worker")
    if job is None:
        return {"trabajo": None}
    return {"trabajo": {**publico(job), "sha256": job["sha256"],
                        "intentos": job["intentos"]}}


@app.post("/api/jobs/{job_id}/resultado", dependencies=[Protegido])
async def entregar_resultado(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Recibe la transcripcion terminada y cierra el trabajo."""
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    if not isinstance(payload, dict) or "segmentos" not in payload:
        raise HTTPException(
            status_code=400,
            detail="El resultado debe ser un objeto JSON con una clave 'segmentos'",
        )

    payload.setdefault("id", job_id)
    payload.setdefault("titulo", job["titulo"])
    payload.setdefault("grabado", job["creado"])
    render.regenerar(payload)

    config.crear_directorios()
    destino = config.RESULT_DIR / f"{job_id}.json"
    # Se escribe aparte y se renombra: si el proceso muere a medias, no queda
    # un JSON truncado que luego falle al leerse.
    temporal = destino.with_suffix(".json.parcial")
    temporal.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    temporal.replace(destino)

    actualizado = db.actualizar(
        job_id,
        estado="hecho",
        terminado=db.ahora(),
        error=None,
        duracion=payload.get("duracion"),
        hablantes=len(payload.get("hablantes") or []) or None,
        idioma=payload.get("idioma"),
    )
    return publico(actualizado)  # type: ignore[arg-type]


@app.post("/api/jobs/{job_id}/hablantes", dependencies=[Protegido])
def renombrar_hablantes(job_id: str, nombres: dict[str, str]) -> dict[str, Any]:
    """Pone nombres reales a las etiquetas SPEAKER_xx.

    No vuelve a procesar nada: reescribe el JSON guardado y rehace el texto.
    Un nombre vacio devuelve al hablante su etiqueta original.
    """
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")

    ruta = config.RESULT_DIR / f"{job_id}.json"
    if not ruta.is_file():
        raise HTTPException(status_code=409, detail="Ese trabajo no tiene transcripcion")

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    etiquetas = {h.get("etiqueta") for h in datos.get("hablantes") or []}

    desconocidas = set(nombres) - etiquetas
    if desconocidas:
        raise HTTPException(
            status_code=400,
            detail=f"Etiquetas que no existen en esta reunion: {', '.join(sorted(desconocidas))}",
        )

    for hablante in datos.get("hablantes") or []:
        if hablante.get("etiqueta") in nombres:
            nuevo = (nombres[hablante["etiqueta"]] or "").strip()[:60]
            hablante["nombre"] = nuevo or hablante["etiqueta"]

    render.regenerar(datos)
    temporal = ruta.with_suffix(".json.parcial")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)

    return {"id": job_id, "hablantes": datos.get("hablantes") or []}


@app.post("/api/jobs/{job_id}/fallo", dependencies=[Protegido])
def marcar_fallo(job_id: str, error: Annotated[str, Form()]) -> dict[str, Any]:
    """El worker no pudo con el trabajo; queda registrado el motivo."""
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    actualizado = db.actualizar(
        job_id, estado="fallido", terminado=db.ahora(), error=error[:2000]
    )
    return publico(actualizado)  # type: ignore[arg-type]


@app.post("/api/jobs/{job_id}/reencolar", dependencies=[Protegido])
def reencolar(job_id: str) -> dict[str, Any]:
    """Devuelve a la cola un trabajo fallido, para reintentarlo."""
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    actualizado = db.actualizar(
        job_id, estado="pendiente", worker=None, reclamado=None,
        terminado=None, error=None,
    )
    return publico(actualizado)  # type: ignore[arg-type]


@app.delete("/api/jobs/{job_id}", dependencies=[Protegido])
def borrar(job_id: str) -> dict[str, Any]:
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")
    ruta_audio(job).unlink(missing_ok=True)
    (config.RESULT_DIR / f"{job_id}.json").unlink(missing_ok=True)
    db.borrar_job(job_id)
    return {"borrado": job_id}


# ---------------------------------------------------------------------- web
# La PWA se sirve desde la propia API para que comparta origen: asi el service
# worker funciona y no hace falta configurar CORS en ningun sitio.
# Va al final a proposito: monta en "/" y se tragaria las rutas de arriba.

WEB = Path(__file__).resolve().parents[1] / "web"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
