"""Envio de paquetes magicos (Wake-on-LAN) desde la API.

Un paquete magico son seis bytes 0xFF seguidos de la MAC repetida dieciseis
veces, en un datagrama UDP. Lo interpreta la tarjeta de red del equipo
dormido, antes de que el sistema operativo exista siquiera.

Va por difusion porque un equipo suspendido no responde a ARP: el switch ya
no sabe por que puerto sale, asi que hay que preguntar a toda la red.
"""

from __future__ import annotations

import re
import socket

PUERTOS = (9, 7)   # 9 es el habitual; 7 esta por compatibilidad


class WolError(RuntimeError):
    pass


def normalizar(mac: str) -> bytes:
    limpia = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(limpia) != 12:
        raise WolError(f"MAC invalida: {mac!r}")
    return bytes.fromhex(limpia)


def paquete_magico(mac: bytes) -> bytes:
    return b"\xff" * 6 + mac * 16


def enviar(mac: str, difusiones: tuple[str, ...]) -> tuple[int, list[str]]:
    """Devuelve (envios correctos, errores)."""
    datos = paquete_magico(normalizar(mac))
    enviados = 0
    errores: list[str] = []

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(3)
        for destino in difusiones:
            for puerto in PUERTOS:
                try:
                    s.sendto(datos, (destino, puerto))
                    enviados += 1
                except OSError as exc:
                    errores.append(f"{destino}:{puerto} {exc}")

    if not enviados:
        raise WolError("No se pudo enviar a ninguna direccion: " + "; ".join(errores))
    return enviados, errores
