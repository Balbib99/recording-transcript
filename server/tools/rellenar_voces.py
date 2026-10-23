"""Rellena la columna 'voces' de las reuniones transcritas antes de tenerla.

El listado pinta las iniciales de cada voz y cuantas siguen sin nombre a
partir de ese resumen, que se guarda en la fila del trabajo. Las reuniones
anteriores al cambio no lo tienen, asi que aparecerian sin esa linea hasta
que se renombrase a alguien. Esto lo pone al dia leyendo cada resultado.

Se puede ejecutar las veces que haga falta: solo toca lo que falta.

    sudo docker compose -f /srv/recordingcraft/app/server/docker-compose.yml \
         exec api python tools/rellenar_voces.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, db, render  # noqa: E402


def main() -> int:
    db.inicializar()
    rellenadas = 0
    sin_fichero = 0

    for job in db.listar_jobs(estado="hecho", limite=1000):
        if job.get("voces"):
            continue
        ruta = config.RESULT_DIR / f"{job['id']}.json"
        if not ruta.is_file():
            sin_fichero += 1
            continue
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"  no se pudo leer {ruta.name}: {exc}")
            continue
        voces = render.voces_json(datos.get("hablantes"))
        if voces:
            db.actualizar(job["id"], voces=voces)
            rellenadas += 1
            print(f"  {job['id']}  {job['titulo'] or job['fichero']}: {voces}")

    print(f"\n{rellenadas} reunion(es) al dia"
          + (f", {sin_fichero} sin JSON de resultado" if sin_fichero else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
