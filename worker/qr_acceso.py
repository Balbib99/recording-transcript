"""Muestra un QR con la URL de la app y el token, para abrirla en el movil.

El token se lee de worker/.env y no se imprime en ningun momento: solo va
dentro del codigo QR.

    python worker/qr_acceso.py
    python worker/qr_acceso.py --url https://otro-dominio:8443
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comun import API_TOKEN, log  # noqa: E402

URL_POR_DEFECTO = "https://reuniones-balbi.duckdns.org:8443"


def main() -> int:
    # El QR se dibuja con caracteres de bloque: sin esto, una consola con la
    # pagina de codigos antigua o una salida redirigida lo hacen reventar.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="QR de acceso a la app")
    parser.add_argument("--url", default=URL_POR_DEFECTO,
                        help=f"direccion de la app (por defecto {URL_POR_DEFECTO})")
    args = parser.parse_args()

    if not API_TOKEN:
        log("Falta RC_API_TOKEN en worker/.env")
        return 1

    try:
        import qrcode
    except ImportError:
        log("Falta la libreria qrcode. Instalala con:")
        log(r"  .venv\Scripts\python.exe -m pip install qrcode")
        return 1

    destino = f"{args.url.rstrip('/')}/?token={API_TOKEN}"

    codigo = qrcode.QRCode(border=2)
    codigo.add_data(destino)
    codigo.make(fit=True)

    print()
    codigo.print_ascii(invert=True)
    print(f"  El codigo lleva la direccion Y el token ({len(destino)} caracteres).")
    print("  El token no se imprime aqui a proposito; va dentro del QR.")
    print()
    print(f"  Destino: {args.url}/?token=<los 64 caracteres del .env>")
    print("  Escanealo con la camara del movil, con WireGuard conectado.")
    print("  Si entras directo a la lista, el token se guardo. Si te la pide, no llego.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
