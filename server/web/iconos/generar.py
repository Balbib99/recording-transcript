"""Genera los PNG del icono de la app sin dependencias externas.

Un cuadrado redondeado con una onda de audio. Se ejecuta a mano cuando se
quiera cambiar el icono:

    python server/web/iconos/generar.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

AQUI = Path(__file__).resolve().parent

FONDO = (14, 17, 22)        # casi negro, como el tema oscuro de la app
ACENTO = (94, 204, 176)     # verde agua
CLARO = (233, 238, 240)


def lienzo(lado: int, color: tuple[int, int, int]) -> list[list[tuple[int, int, int, int]]]:
    return [[(*color, 0) for _ in range(lado)] for _ in range(lado)]


def cuadrado_redondeado(px, lado: int, radio: int, color) -> None:
    for y in range(lado):
        for x in range(lado):
            cx = min(max(x, radio), lado - radio - 1)
            cy = min(max(y, radio), lado - radio - 1)
            if math.hypot(x - cx, y - cy) <= radio:
                px[y][x] = (*color, 255)


def barra(px, lado: int, centro_x: int, alto: int, ancho: int, color) -> None:
    """Una barra vertical redondeada, centrada verticalmente."""
    medio = lado // 2
    y0, y1 = medio - alto // 2, medio + alto // 2
    r = ancho / 2
    for y in range(max(0, y0), min(lado, y1)):
        for x in range(centro_x - ancho // 2, centro_x + ancho // 2 + 1):
            if not (0 <= x < lado):
                continue
            # Extremos redondeados
            if y < y0 + r:
                if math.hypot(x - centro_x, y - (y0 + r)) > r:
                    continue
            elif y > y1 - r:
                if math.hypot(x - centro_x, y - (y1 - r)) > r:
                    continue
            px[y][x] = (*color, 255)


def escribir_png(px, ruta: Path) -> None:
    lado = len(px)
    crudo = b"".join(
        b"\x00" + b"".join(struct.pack("4B", *px[y][x]) for x in range(lado))
        for y in range(lado)
    )

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + trozo(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
           + trozo(b"IDAT", zlib.compress(crudo, 9))
           + trozo(b"IEND", b""))
    ruta.write_bytes(png)


def icono(lado: int, recortable: bool = False) -> None:
    px = lienzo(lado, FONDO)
    # Un icono "maskable" necesita margen: Android le recorta las esquinas.
    margen = int(lado * 0.1) if recortable else 0
    util = lado - 2 * margen

    if recortable:
        for y in range(lado):
            for x in range(lado):
                px[y][x] = (*FONDO, 255)
    cuadrado_redondeado(px, lado, int(lado * 0.22), FONDO)

    # Onda de audio: cinco barras de alturas distintas.
    alturas = (0.26, 0.52, 0.78, 0.46, 0.22)
    colores = (CLARO, CLARO, ACENTO, CLARO, CLARO)
    ancho = max(2, int(util * 0.085))
    paso = int(util * 0.15)
    inicio = lado // 2 - paso * 2
    for i, (h, color) in enumerate(zip(alturas, colores)):
        barra(px, lado, inicio + paso * i, int(util * h), ancho, color)

    nombre = f"icono-{lado}{'-recortable' if recortable else ''}.png"
    escribir_png(px, AQUI / nombre)
    print("  ", nombre)


if __name__ == "__main__":
    print("generando iconos en", AQUI)
    icono(192)
    icono(512)
    icono(512, recortable=True)
