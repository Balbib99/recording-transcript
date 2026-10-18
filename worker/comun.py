"""Piezas compartidas por el worker y el cliente: configuracion, tunel y llamadas HTTP."""

from __future__ import annotations

import datetime as dt
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

import requests  # noqa: E402

from recordingcraft.config import load_env_file  # noqa: E402

load_env_file(RAIZ / "worker" / ".env")
load_env_file(RAIZ / ".env")

API_URL = os.environ.get("RC_API_URL", "http://127.0.0.1:8000").rstrip("/")
API_TOKEN = os.environ.get("RC_API_TOKEN", "").strip()
WORKER = os.environ.get("RC_WORKER_NAME") or f"{platform.node()}-gpu"
SSH_HOST = os.environ.get("RC_SSH_HOST", "pi-rcraft").strip()
TUNEL_LOCAL = int(os.environ.get("RC_TUNNEL_LOCAL_PORT", "8000"))
TUNEL_REMOTO = os.environ.get("RC_TUNNEL_REMOTE", "127.0.0.1:8000")
ESPERA = int(os.environ.get("RC_POLL_SECONDS", "15"))

CABECERAS = {"Authorization": f"Bearer {API_TOKEN}"}


def log(mensaje: str = "") -> None:
    print(f"{dt.datetime.now():%H:%M:%S}  {mensaje}", flush=True)


class Tunel:
    """Tunel SSH al puerto de la API, con reapertura automatica.

    La API de la Pi solo escucha en su loopback: en vez de exponerla a la red,
    el cliente abre el tunel con la clave del usuario sin privilegios.
    """

    def __init__(self, host: str | None = None) -> None:
        self.host = SSH_HOST if host is None else host
        self.proceso: subprocess.Popen | None = None

    @property
    def activo(self) -> bool:
        return self.proceso is not None and self.proceso.poll() is None

    def _puerto_ocupado(self) -> bool:
        with socket.socket() as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", TUNEL_LOCAL)) == 0

    def abrir(self) -> None:
        if not self.host or self.activo or self._puerto_ocupado():
            return

        orden = [
            "ssh", "-N",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "BatchMode=yes",
            "-L", f"{TUNEL_LOCAL}:{TUNEL_REMOTO}",
            self.host,
        ]
        log(f"abriendo tunel SSH a {self.host} ({TUNEL_LOCAL} -> {TUNEL_REMOTO})")
        self.proceso = subprocess.Popen(
            orden, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )

        for _ in range(20):
            time.sleep(0.5)
            if self._puerto_ocupado():
                return
            if not self.activo:
                error = (self.proceso.stderr.read() or b"").decode(errors="replace")
                raise RuntimeError(f"el tunel SSH no abrio: {error.strip()[:300]}")
        raise RuntimeError("el tunel SSH no respondio a tiempo")

    def cerrar(self) -> None:
        if self.activo and self.proceso is not None:
            self.proceso.terminate()
            try:
                self.proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proceso.kill()


def api(metodo: str, ruta: str, **kwargs: Any) -> requests.Response:
    respuesta = requests.request(
        metodo, f"{API_URL}{ruta}", headers=CABECERAS,
        timeout=kwargs.pop("timeout", 60), **kwargs,
    )
    if respuesta.status_code == 401:
        raise RuntimeError(
            "La API rechaza el token. Copialo del .env de la Pi:\n"
            '  ssh pi-rcraft "grep RC_API_TOKEN /srv/recordingcraft/app/server/.env"'
        )
    return respuesta


def esperar_api(intentos: int = 10) -> bool:
    for _ in range(intentos):
        try:
            if requests.get(f"{API_URL}/api/health", timeout=5).ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False
