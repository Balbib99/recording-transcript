"""Servicio que envia el paquete magico, con la red del host.

Existe por una limitacion concreta: un contenedor normal no puede mandar una
difusion a la red de casa. Linux no reenvia difusiones dirigidas entre
interfaces, asi que el paquete muere en el puente de Docker. Comprobado: la
API enviaba cuatro paquetes sin error y no llegaba ninguno.

La solucion es este proceso diminuto con `network_mode: host`, que si ve la
red real. No escucha en ningun puerto: la API deja una peticion en un fichero
de la carpeta de datos, que los dos comparten, y este la recoge.

Solo actua cuando ese fichero aparece, y el fichero solo lo escribe la API
cuando alguien pulsa el boton. Nada enciende el PC por su cuenta.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from app import config, wol

INTERVALO = 2.0          # cada cuanto se mira si hay peticion
PETICION = "despertar.peticion"
REGISTRO = "despertar.log"


def anotar(texto: str) -> None:
    linea = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}  {texto}"
    print(linea, flush=True)
    try:
        with open(config.DATA_DIR / REGISTRO, "a", encoding="utf-8") as fichero:
            fichero.write(linea + "\n")
    except OSError:
        pass


def main() -> None:
    config.crear_directorios()
    peticion = config.DATA_DIR / PETICION
    anotar(f"despertador en marcha (mac={'si' if config.WOL_MAC else 'sin configurar'}, "
           f"difusiones={', '.join(config.WOL_DIFUSIONES)})")

    while True:
        try:
            if peticion.exists():
                quien = peticion.read_text(encoding="utf-8").strip()[:80]
                peticion.unlink(missing_ok=True)
                if not config.WOL_MAC:
                    anotar("peticion recibida pero no hay RC_WOL_MAC configurada")
                else:
                    enviados, errores = wol.enviar(config.WOL_MAC, config.WOL_DIFUSIONES)
                    anotar(f"paquete magico a {config.WOL_MAC}: {enviados} envios"
                           + (f" | errores: {errores}" if errores else "")
                           + (f" | pedido por {quien}" if quien else ""))
        except Exception as exc:
            anotar(f"error: {type(exc).__name__}: {exc}")
        time.sleep(INTERVALO)


if __name__ == "__main__":
    main()
