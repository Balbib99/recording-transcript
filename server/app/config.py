"""Configuracion del servidor, leida del entorno."""

from __future__ import annotations

import os
from pathlib import Path


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


# Carpeta de datos. En el contenedor se monta /srv/recordingcraft/data.
DATA_DIR = Path(os.environ.get("RC_DATA_DIR", "/data"))
AUDIO_DIR = DATA_DIR / "audio"
RESULT_DIR = DATA_DIR / "resultados"
DB_PATH = DATA_DIR / "recordingcraft.db"

# Token compartido. Sin el, la API no arranca: es la unica autenticacion que hay.
API_TOKEN = os.environ.get("RC_API_TOKEN", "").strip()

# Limite de subida, en megabytes. Una hora de grabacion del Pixel ronda los 30-50 MB.
MAX_UPLOAD_MB = _int("RC_MAX_UPLOAD_MB", 500)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Extensiones aceptadas.
EXTENSIONES = {
    ".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".amr", ".3gp",
}

# Segundos tras los cuales un trabajo reclamado por un worker que nunca volvio
# se considera abandonado y vuelve a la cola.
CLAIM_TIMEOUT = _int("RC_CLAIM_TIMEOUT", 3 * 3600)


# Wake-on-LAN: MAC del PC del worker y a donde difundir el paquete.
WOL_MAC = os.environ.get("RC_WOL_MAC", "").strip()
WOL_DIFUSIONES = tuple(
    d.strip() for d in os.environ.get(
        "RC_WOL_BROADCAST", "255.255.255.255,192.168.1.255").split(",") if d.strip()
)
# Segundos sin noticias del worker tras los que se considera que el PC no esta.
WORKER_VIVO = _int("RC_WORKER_VIVO", 75)


def crear_directorios() -> None:
    for carpeta in (DATA_DIR, AUDIO_DIR, RESULT_DIR):
        carpeta.mkdir(parents=True, exist_ok=True)
