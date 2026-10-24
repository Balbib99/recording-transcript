"""API de RecordingCraft: recibe grabaciones y mantiene la cola de trabajos.

Fase 3: subir, listar, consultar y descargar el audio. La transcripcion la hara
el worker del PC en la fase siguiente, pidiendo trabajo a esta misma API.
"""

from __future__ import annotations

import datetime as dt
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

from app import config, db, render, wol


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


@app.middleware("http")
async def sin_cache_en_la_web(request, call_next):
    """Obliga al navegador a preguntar siempre antes de reusar la interfaz.

    Sin esto, el servidor no decia nada sobre caducidad y cada navegador
    decidia por su cuenta cuanto guardarse el HTML, el CSS y el script. De ahi
    venian las versiones viejas que no se iban ni a tiros.

    "no-cache" no significa no guardar: significa guardar pero revalidar. Con
    el ETag, si no ha cambiado nada la respuesta es un 304 de unos pocos bytes.
    """
    respuesta = await call_next(request)
    if not request.url.path.startswith("/api"):
        respuesta.headers.setdefault("Cache-Control", "no-cache")
    return respuesta


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


def guardar_resultado(ruta: Path, datos: dict[str, Any]) -> None:
    """Escribe el JSON de una transcripcion sin dejarlo nunca a medias.

    Se escribe aparte y se renombra: si el proceso muere a medias, no queda
    un JSON truncado que luego falle al leerse.
    """
    temporal = ruta.with_suffix(".json.parcial")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    temporal.replace(ruta)


def terminos_de(texto: Any) -> list[str]:
    """Separa una lista escrita a mano (comas o saltos de linea) en terminos.

    Quita los vacios y los repetidos (sin distinguir mayusculas) y respeta el
    orden en que se escribieron.
    """
    if not texto:
        return []
    if isinstance(texto, str):
        texto = texto.replace(chr(10), ",").replace(chr(13), ",").split(",")
    vistos: set[str] = set()
    salida: list[str] = []
    for bruto in texto:
        termino = str(bruto).strip()
        if termino and termino.lower() not in vistos:
            vistos.add(termino.lower())
            salida.append(termino)
    return salida


def unir_terminos(*listas: Any) -> str | None:
    """Suma varias listas de terminos en una, sin repetir: general, perfil y reunion."""
    juntos: list[str] = []
    for lista in listas:
        juntos.extend(terminos_de(lista))
    return ", ".join(terminos_de(juntos)) or None


def perfil_publico(perfil: dict[str, Any], grabaciones: int | None = None) -> dict[str, Any]:
    try:
        participantes = json.loads(perfil["participantes"]) if perfil.get("participantes") else []
    except (TypeError, ValueError):
        participantes = []
    return {
        "id": perfil["id"],
        "nombre": perfil["nombre"],
        "color": perfil["color"],
        "vocabulario": perfil["vocabulario"] or "",
        "participantes": participantes,
        "orden": perfil["orden"],
        "grabaciones": grabaciones,
    }


def voces_de(job: dict[str, Any]) -> list[str] | None:
    try:
        return json.loads(job["voces"]) if job.get("voces") else None
    except (TypeError, ValueError):
        return None


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
        "vocabulario": job["vocabulario"],
        "esperados": job["esperados"],
        "voces": voces_de(job),
        "perfil": job["perfil"],
        "contexto": job["contexto"],
    }


# ------------------------------------------------------------------ endpoints

@app.get("/api/health")
def salud() -> dict[str, Any]:
    """Sin autenticacion: sirve para comprobar que el servicio esta vivo."""
    return {"ok": True, "version": app.version}


def estado_del_worker() -> dict[str, Any]:
    """Si el worker ha preguntado hace poco, el PC esta encendido."""
    visto = db.leer_anotacion("worker_visto")
    if not visto:
        return {"visto": None, "nombre": None, "segundos": None, "vivo": False,
                "puede_despertarse": bool(config.WOL_MAC)}
    marca = dt.datetime.fromisoformat(visto["actualizado"])
    segundos = int((dt.datetime.now(dt.timezone.utc) - marca).total_seconds())
    return {
        "visto": visto["actualizado"],
        "nombre": visto["valor"],
        "segundos": segundos,
        "vivo": segundos <= config.WORKER_VIVO,
        "puede_despertarse": bool(config.WOL_MAC),
    }


@app.get("/api/estado", dependencies=[Protegido])
def estado() -> dict[str, Any]:
    conteo = db.contar_por_estado()
    uso = sum(f.stat().st_size for f in config.AUDIO_DIR.glob("*") if f.is_file())
    return {"trabajos": conteo, "bytes_en_disco": uso, "worker": estado_del_worker()}


@app.post("/api/despertar", dependencies=[Protegido])
def despertar() -> dict[str, Any]:
    """Manda el paquete magico al PC del worker. Lo dispara el usuario, nadie mas."""
    if not config.WOL_MAC:
        raise HTTPException(
            status_code=409,
            detail="No hay MAC configurada: pon RC_WOL_MAC en el .env del servidor",
        )
    actual = estado_del_worker()
    if actual["vivo"]:
        return {"enviado": False, "motivo": "el worker ya esta en marcha",
                "worker": actual}
    # El paquete no se manda desde aqui: un contenedor en red puente no puede
    # difundir a la red de casa. Lo hace el servicio "despertador", que corre
    # con la red del host y recoge esta peticion del disco compartido.
    try:
        config.crear_directorios()
        (config.DATA_DIR / "despertar.peticion").write_text(
            f"app {db.ahora()}", encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo pedir el encendido: {exc}")

    return {"enviado": True, "worker": actual}


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED, dependencies=[Protegido])
async def subir(
    file: Annotated[UploadFile, File(description="Fichero de audio")],
    titulo: Annotated[str | None, Form()] = None,
    vocabulario: Annotated[str | None, Form(
        description="Terminos separados por comas: nombres, marcas, modelos")] = None,
    esperados: Annotated[int | None, Form(
        description="Cuantas personas hablan, si se sabe")] = None,
    perfil: Annotated[str | None, Form(
        description="Id del perfil de trabajo (empresa, casa...)")] = None,
    contexto: Annotated[str | None, Form(
        description="De que va la reunion, en una frase, si se quiere")] = None,
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

    perfil = (perfil or "").strip() or None
    if perfil and db.obtener_perfil(perfil) is None:
        raise HTTPException(status_code=400, detail="No existe ese perfil")

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
        vocabulario=(vocabulario or "").strip()[:2000] or None,
        esperados=esperados if esperados and 1 <= esperados <= 20 else None,
        perfil=perfil,
        contexto=(contexto or "").strip()[:300] or None,
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


@app.post("/api/jobs/{job_id}/ajustes", dependencies=[Protegido])
def ajustes(job_id: str, datos: dict[str, Any]) -> dict[str, Any]:
    """Cambia titulo, vocabulario y numero de hablantes antes de transcribir.

    Solo tiene sentido mientras el trabajo espera: una vez transcrito, cambiar
    estos datos no rehace nada. Para eso hay que reencolarlo.
    """
    job = db.obtener_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo")

    cambios: dict[str, Any] = {}
    if "titulo" in datos:
        cambios["titulo"] = (str(datos["titulo"] or "").strip()[:120] or None)
    if "vocabulario" in datos:
        cambios["vocabulario"] = (str(datos["vocabulario"] or "").strip()[:2000] or None)
    if "esperados" in datos:
        try:
            numero = int(datos["esperados"] or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="'esperados' debe ser un numero")
        if numero and not 1 <= numero <= 20:
            raise HTTPException(status_code=400, detail="Entre 1 y 20 hablantes")
        cambios["esperados"] = numero or None
    if "perfil" in datos:
        perfil_id = str(datos["perfil"] or "").strip()
        if perfil_id and db.obtener_perfil(perfil_id) is None:
            raise HTTPException(status_code=400, detail="No existe ese perfil")
        cambios["perfil"] = perfil_id or None
    if "contexto" in datos:
        cambios["contexto"] = (str(datos["contexto"] or "").strip()[:300] or None)

    actualizado = db.actualizar(job_id, **cambios)

    # El nombre se puede cambiar siempre. Si la reunion ya esta transcrita, el
    # JSON y el Markdown que lleva dentro tienen que enterarse tambien, o
    # quedarian con el nombre viejo.
    if "titulo" in cambios:
        ruta = config.RESULT_DIR / f"{job_id}.json"
        if ruta.is_file():
            resultado = json.loads(ruta.read_text(encoding="utf-8"))
            resultado["titulo"] = actualizado["titulo"] or Path(job["fichero"]).stem  # type: ignore[index]
            render.regenerar(resultado)
            guardar_resultado(ruta, resultado)

    # Vocabulario, contexto y personas esperadas, en cambio, solo cuentan al
    # transcribir. El perfil de una reunion hecha es una etiqueta: se puede
    # corregir sin rehacer nada.
    afecta_a_la_transcripcion = bool(
        {"vocabulario", "esperados", "contexto"} & cambios.keys())
    aviso = None if (job["estado"] == "pendiente" or not afecta_a_la_transcripcion) else (
        "El trabajo ya no esta pendiente: reencolalo para que surtan efecto")
    return {**publico(actualizado), "aviso": aviso}  # type: ignore[arg-type]


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
    nombre = worker.strip()[:60] or "worker"
    # Cada consulta es un latido: con esto la app sabe si el PC esta vivo.
    db.anotar("worker_visto", nombre)
    job = db.reclamar_siguiente(nombre)
    if job is None:
        return {"trabajo": None}
    # El vocabulario que se aplica es el del perfil mas el de la reunion, juntos
    # y sin repetir. Se resuelve aqui, en el momento de reclamar, para que el
    # worker no tenga que saber nada de perfiles.
    perfil = db.obtener_perfil(job["perfil"]) if job["perfil"] else None
    return {"trabajo": {
        **publico(job),
        "sha256": job["sha256"],
        "intentos": job["intentos"],
        "vocabulario_total": unir_terminos(perfil["vocabulario"] if perfil else None,
                                           job["vocabulario"]),
    }}


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
    guardar_resultado(config.RESULT_DIR / f"{job_id}.json", payload)

    actualizado = db.actualizar(
        job_id,
        estado="hecho",
        terminado=db.ahora(),
        error=None,
        duracion=payload.get("duracion"),
        hablantes=len(payload.get("hablantes") or []) or None,
        idioma=payload.get("idioma"),
        voces=render.voces_json(payload.get("hablantes")),
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
    guardar_resultado(ruta, datos)

    # El listado muestra las iniciales y cuantas quedan sin nombre: hay que
    # rehacer ese resumen aqui, que es donde cambian los nombres.
    db.actualizar(job_id, voces=render.voces_json(datos.get("hablantes")))

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


# ------------------------------------------------------------------- perfiles

def _nombre_de_perfil(datos: dict[str, Any], propio: str | None = None) -> str:
    nombre = str(datos.get("nombre") or "").strip()[:40]
    if not nombre:
        raise HTTPException(status_code=400, detail="El perfil necesita un nombre")
    for otro in db.listar_perfiles():
        if otro["id"] != propio and otro["nombre"].lower() == nombre.lower():
            raise HTTPException(status_code=409, detail=f"Ya hay un perfil llamado {nombre}")
    return nombre


def _vocabulario_de(valor: Any) -> str | None:
    return (unir_terminos(valor) or "")[:2000] or None


def _participantes_json(valor: Any) -> str | None:
    nombres = [n[:60] for n in terminos_de(valor)][:30]
    return json.dumps(nombres, ensure_ascii=False) if nombres else None


@app.get("/api/perfiles", dependencies=[Protegido])
def perfiles_listar() -> dict[str, Any]:
    cuentas = db.contar_jobs_por_perfil()
    return {"perfiles": [perfil_publico(p, cuentas.get(p["id"], 0))
                         for p in db.listar_perfiles()]}


@app.post("/api/perfiles", status_code=status.HTTP_201_CREATED, dependencies=[Protegido])
def perfiles_crear(datos: dict[str, Any]) -> dict[str, Any]:
    perfil = db.crear_perfil(
        nombre=_nombre_de_perfil(datos),
        vocabulario=_vocabulario_de(datos.get("vocabulario")),
        participantes=_participantes_json(datos.get("participantes")),
    )
    return perfil_publico(perfil, 0)


@app.put("/api/perfiles/{perfil_id}", dependencies=[Protegido])
def perfiles_editar(perfil_id: str, datos: dict[str, Any]) -> dict[str, Any]:
    if db.obtener_perfil(perfil_id) is None:
        raise HTTPException(status_code=404, detail="No existe ese perfil")
    cambios: dict[str, Any] = {}
    if "nombre" in datos:
        cambios["nombre"] = _nombre_de_perfil(datos, propio=perfil_id)
    if "vocabulario" in datos:
        cambios["vocabulario"] = _vocabulario_de(datos["vocabulario"])
    if "participantes" in datos:
        cambios["participantes"] = _participantes_json(datos["participantes"])
    perfil = db.actualizar_perfil(perfil_id, **cambios)
    cuenta = db.contar_jobs_por_perfil().get(perfil_id, 0)
    return perfil_publico(perfil, cuenta)  # type: ignore[arg-type]


@app.delete("/api/perfiles/{perfil_id}", dependencies=[Protegido])
def perfiles_borrar(perfil_id: str) -> dict[str, Any]:
    if db.obtener_perfil(perfil_id) is None:
        raise HTTPException(status_code=404, detail="No existe ese perfil")
    sueltas = db.borrar_perfil(perfil_id)
    return {"borrado": perfil_id, "grabaciones_sin_perfil": sueltas}


# ---------------------------------------------------------------------- web
# La PWA se sirve desde la propia API para que comparta origen: asi el service
# worker funciona y no hace falta configurar CORS en ningun sitio.
# Va al final a proposito: monta en "/" y se tragaria las rutas de arriba.

WEB = Path(__file__).resolve().parents[1] / "web"
if WEB.is_dir():
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
