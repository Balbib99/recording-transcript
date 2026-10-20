"""Despierta el PC del worker enviando un paquete magico (Wake-on-LAN).

Se ejecuta en la Pi. Sin dependencias: es un datagrama UDP con un formato
muy simple (seis bytes 0xFF seguidos de la MAC repetida dieciseis veces).

    python3 despertar_pc.py                 # usa RC_WOL_MAC del entorno
    python3 despertar_pc.py 2C-F0-5D-57-FD-16

La MAC se lee de server/.env (RC_WOL_MAC) para no tenerla en el repositorio.

El paquete va a la direccion de difusion, porque el PC dormido no responde a
ARP y el router ya no sabe en que puerto esta: hay que preguntar a todos.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path

PUERTOS = (9, 7)          # 9 es el habitual; 7 por compatibilidad
DIFUSIONES_POR_DEFECTO = ("255.255.255.255", "192.168.1.255")


def cargar_env(ruta: Path) -> None:
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip().strip('"'))


def normalizar(mac: str) -> bytes:
    limpia = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(limpia) != 12:
        raise ValueError(f"MAC invalida: {mac!r}")
    return bytes.fromhex(limpia)


def paquete_magico(mac: bytes) -> bytes:
    return b"\xff" * 6 + mac * 16


def despertar(mac: str, difusiones=DIFUSIONES_POR_DEFECTO) -> int:
    datos = paquete_magico(normalizar(mac))
    enviados = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for destino in difusiones:
            for puerto in PUERTOS:
                try:
                    s.sendto(datos, (destino, puerto))
                    enviados += 1
                except OSError as exc:
                    print(f"  ! {destino}:{puerto} -> {exc}")
    return enviados


def main() -> int:
    cargar_env(Path(__file__).resolve().parents[1] / ".env")
    mac = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RC_WOL_MAC", "")
    if not mac:
        print("Falta la MAC. Ponla en server/.env como RC_WOL_MAC=2C-F0-...")
        return 1

    difusiones = tuple(filter(None, [
        os.environ.get("RC_WOL_BROADCAST"), *DIFUSIONES_POR_DEFECTO,
    ]))
    enviados = despertar(mac, difusiones)
    print(f"Paquete magico enviado a {mac} ({enviados} envios)")
    print("Si el PC estaba suspendido, deberia encenderse en unos segundos.")
    return 0 if enviados else 1


if __name__ == "__main__":
    raise SystemExit(main())
