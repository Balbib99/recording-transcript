"""Prueba de humo de la API: recorre el flujo completo sin levantar servidor.

    python -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
    .venv/bin/python tests/test_api.py

Usa una carpeta temporal, asi que no toca ningun dato real.
"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="rc-api-"))
os.environ["RC_DATA_DIR"] = str(TMP)
os.environ["RC_API_TOKEN"] = "token-de-prueba"
os.environ["RC_MAX_UPLOAD_MB"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer token-de-prueba"}
fallos = []


def comprobar(nombre, condicion, detalle=""):
    print(f"  {'OK  ' if condicion else 'FALLA'}  {nombre}{(' - ' + str(detalle)) if detalle and not condicion else ''}")
    if not condicion:
        fallos.append(nombre)


with TestClient(app) as c:
    print("\n-- salud y autenticacion --")
    r = c.get("/api/health")
    comprobar("health sin token responde 200", r.status_code == 200, r.text)

    r = c.get("/api/jobs")
    comprobar("listar sin token da 401", r.status_code == 401, r.status_code)

    r = c.get("/api/jobs", headers={"Authorization": "Bearer incorrecto"})
    comprobar("token erroneo da 401", r.status_code == 401, r.status_code)

    r = c.get("/api/jobs", headers=AUTH)
    comprobar("listar con token da 200", r.status_code == 200, r.text)
    comprobar("la cola empieza vacia", r.json()["total"] == 0, r.json())

    print("\n-- subida --")
    audio = b"RIFF....audio falso...." * 100
    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("reunion equipo.m4a", audio, "audio/mp4")},
               data={"titulo": "Reunion de equipo"})
    comprobar("subida correcta da 201", r.status_code == 201, r.text)
    job = r.json()
    comprobar("devuelve id", bool(job.get("id")), job)
    comprobar("estado inicial pendiente", job["estado"] == "pendiente", job)
    comprobar("titulo respetado", job["titulo"] == "Reunion de equipo", job)
    comprobar("no marcado como duplicado", job["duplicado"] is False, job)
    job_id = job["id"]

    guardado = TMP / "audio" / f"{job_id}.m4a"
    comprobar("audio escrito en disco", guardado.is_file(), guardado)
    comprobar("tamano correcto", guardado.stat().st_size == len(audio))

    print("\n-- validaciones --")
    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("virus.exe", b"MZ", "application/octet-stream")})
    comprobar("extension no admitida da 415", r.status_code == 415, r.status_code)

    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("vacio.m4a", b"", "audio/mp4")})
    comprobar("fichero vacio da 400", r.status_code == 400, r.status_code)

    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("enorme.m4a", b"x" * (2 * 1024 * 1024), "audio/mp4")})
    comprobar("fichero gigante da 413", r.status_code == 413, r.status_code)
    sobrantes = list((TMP / "audio").glob(".subiendo-*"))
    comprobar("no deja temporales tras rechazar", not sobrantes, sobrantes)

    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("../../etc/passwd.m4a", audio[:50], "audio/mp4")})
    comprobar("nombre con rutas se sanea",
              "/" not in r.json()["fichero"] and ".." not in r.json()["fichero"],
              r.json().get("fichero"))

    print("\n-- duplicados --")
    r = c.post("/api/jobs", headers=AUTH,
               files={"file": ("otra-copia.m4a", audio, "audio/mp4")})
    comprobar("mismo audio se reconoce", r.json().get("duplicado") is True, r.json())
    comprobar("devuelve el trabajo original", r.json()["id"] == job_id, r.json())

    print("\n-- consulta y descarga --")
    r = c.get(f"/api/jobs/{job_id}", headers=AUTH)
    comprobar("detalle da 200", r.status_code == 200, r.text)
    comprobar("aun sin transcripcion",
              r.json()["transcripcion_disponible"] is False, r.json())

    r = c.get(f"/api/jobs/{job_id}/audio", headers=AUTH)
    comprobar("descarga del audio coincide", r.content == audio, len(r.content))

    r = c.get("/api/jobs/noexiste", headers=AUTH)
    comprobar("id inexistente da 404", r.status_code == 404, r.status_code)

    r = c.get(f"/api/jobs/{job_id}/transcripcion", headers=AUTH)
    comprobar("transcripcion no lista da 409", r.status_code == 409, r.status_code)

    print("\n-- cola --")
    from app import db
    reclamado = db.reclamar_siguiente("worker-prueba")
    comprobar("el worker reclama el pendiente", reclamado and reclamado["id"] == job_id)
    comprobar("pasa a procesando", reclamado["estado"] == "procesando", reclamado)
    # Hay un segundo trabajo (el del nombre saneado): el otro worker debe
    # llevarse ESE, nunca el mismo que ya esta en proceso.
    segundo = db.reclamar_siguiente("otro-worker")
    comprobar("otro worker recibe un trabajo distinto",
              segundo is not None and segundo["id"] != job_id, segundo)
    comprobar("agotada la cola, no entrega nada",
              db.reclamar_siguiente("tercer-worker") is None)

    r = c.get("/api/estado", headers=AUTH)
    comprobar("resumen de estado", r.json()["trabajos"]["procesando"] == 2, r.json())

    print("\n-- voces en el listado --")
    # El listado de la app pinta las iniciales de cada voz y cuantas quedan
    # por nombrar, sin abrir el JSON de la transcripcion: ese resumen se
    # guarda en la fila y tiene que rehacerse tambien al renombrar.
    resultado = {
        "segmentos": [],
        "duracion": 90.0,
        "idioma": "es",
        "hablantes": [
            {"etiqueta": "SPEAKER_00", "nombre": "Javi", "segundos": 60.0,
             "intervenciones": 2, "palabras": 10},
            {"etiqueta": "SPEAKER_01", "nombre": "SPEAKER_01", "segundos": 30.0,
             "intervenciones": 1, "palabras": 5},
        ],
        "turnos": [
            {"hablante": "SPEAKER_00", "inicio": 0.0, "fin": 60.0, "texto": "Hola"},
            {"hablante": "SPEAKER_01", "inicio": 60.0, "fin": 90.0, "texto": "Adios"},
        ],
    }
    r = c.post(f"/api/jobs/{job_id}/resultado", headers=AUTH, json=resultado)
    comprobar("el resultado se acepta", r.status_code == 200, r.text)
    comprobar("una voz con nombre y otra sin el",
              r.json().get("voces") == ["Javi", ""], r.json().get("voces"))

    en_lista = next(t for t in c.get("/api/jobs", headers=AUTH).json()["trabajos"]
                    if t["id"] == job_id)
    comprobar("el listado trae las voces", en_lista.get("voces") == ["Javi", ""],
              en_lista.get("voces"))

    r = c.post(f"/api/jobs/{job_id}/hablantes", headers=AUTH,
               json={"SPEAKER_01": "Marta"})
    comprobar("renombrar da 200", r.status_code == 200, r.text)
    actualizado = c.get(f"/api/jobs/{job_id}", headers=AUTH).json()
    comprobar("el listado se entera del nombre nuevo",
              actualizado.get("voces") == ["Javi", "Marta"], actualizado.get("voces"))

    print("\n-- renombrar --")
    r = c.post(f"/api/jobs/{job_id}/ajustes", headers=AUTH,
               json={"titulo": "  Instalacion Norte  "})
    comprobar("renombrar una reunion ya hecha da 200", r.status_code == 200, r.text)
    comprobar("el titulo se guarda sin espacios sobrantes",
              r.json()["titulo"] == "Instalacion Norte", r.json()["titulo"])
    comprobar("cambiar solo el nombre no da aviso falso",
              r.json().get("aviso") is None, r.json().get("aviso"))

    guardada = c.get(f"/api/jobs/{job_id}/transcripcion", headers=AUTH).json()
    comprobar("el JSON guardado lleva el nombre nuevo",
              guardada.get("titulo") == "Instalacion Norte", guardada.get("titulo"))
    comprobar("el Markdown tambien",
              guardada.get("markdown", "").startswith("# Instalacion Norte"),
              guardada.get("markdown", "")[:40])
    comprobar("y las voces no se tocan", [h["nombre"] for h in guardada["hablantes"]]
              == ["Javi", "Marta"], guardada["hablantes"])

    r = c.post(f"/api/jobs/{job_id}/ajustes", headers=AUTH, json={"titulo": "x" * 500})
    comprobar("un nombre desmesurado se recorta", len(r.json()["titulo"]) == 120,
              len(r.json()["titulo"]))

    r = c.post(f"/api/jobs/{job_id}/ajustes", headers=AUTH,
               json={"vocabulario": "Alfa"})
    comprobar("el vocabulario de una reunion hecha si avisa",
              bool(r.json().get("aviso")), r.json().get("aviso"))

    r = c.post("/api/jobs/noexiste/ajustes", headers=AUTH, json={"titulo": "x"})
    comprobar("renombrar un id inexistente da 404", r.status_code == 404, r.status_code)

    print("\n-- borrado --")
    r = c.delete(f"/api/jobs/{job_id}", headers=AUTH)
    comprobar("borrado da 200", r.status_code == 200, r.text)
    comprobar("el audio desaparece del disco", not guardado.exists())
    comprobar("ya no aparece en la lista",
              c.get("/api/jobs", headers=AUTH).json()["total"] == 1)

    comprobar("borrar dos veces da 404, no un error",
              c.delete(f"/api/jobs/{job_id}", headers=AUTH).status_code == 404)
    comprobar("tampoco queda el JSON de resultado",
              not (TMP / "resultados" / f"{job_id}.json").exists())

    # El otro trabajo sigue 'procesando' (lo reclamo un worker de prueba):
    # se puede borrar igualmente, que es lo que hace falta cuando el worker
    # murio a mitad y el trabajo no se va a mover solo.
    restante = c.get("/api/jobs", headers=AUTH).json()["trabajos"][0]
    comprobar("el que queda esta en proceso", restante["estado"] == "procesando",
              restante["estado"])
    comprobar("se puede borrar un trabajo en proceso",
              c.delete(f"/api/jobs/{restante['id']}", headers=AUTH).status_code == 200)
    comprobar("la cola queda vacia", c.get("/api/jobs", headers=AUTH).json()["total"] == 0)

    print("\n-- perfiles --")
    r = c.get("/api/perfiles", headers=AUTH)
    nombres = [x["nombre"] for x in r.json()["perfiles"]]
    comprobar("arrancan los dos perfiles de partida", nombres == ["Empresa", "Casa"], nombres)
    comprobar("y vacios: nada de nadie viaja en el codigo",
              all(not x["vocabulario"] and not x["participantes"] for x in r.json()["perfiles"]))
    empresa, casa = r.json()["perfiles"]
    comprobar("cada uno con su color", empresa["color"] != casa["color"],
              (empresa["color"], casa["color"]))
    comprobar("sin token no se listan",
              c.get("/api/perfiles").status_code == 401)

    # Terminos escritos a mano: comas, saltos de linea, huecos y repetidos.
    r = c.put(f"/api/perfiles/{empresa['id']}", headers=AUTH, json={
        "vocabulario": "Alfa,  Beta Gamma" + chr(10) + "alfa, , Delta",
        "participantes": "Javi, Marta" + chr(10) + "javi",
    })
    comprobar("editar un perfil da 200", r.status_code == 200, r.text)
    comprobar("el vocabulario se normaliza y no repite",
              r.json()["vocabulario"] == "Alfa, Beta Gamma, Delta", r.json()["vocabulario"])
    comprobar("los participantes tambien",
              r.json()["participantes"] == ["Javi", "Marta"], r.json()["participantes"])

    r = c.put(f"/api/perfiles/{empresa['id']}", headers=AUTH, json={"nombre": "  casa "})
    comprobar("no se admiten dos perfiles con el mismo nombre", r.status_code == 409, r.status_code)
    r = c.put(f"/api/perfiles/{empresa['id']}", headers=AUTH, json={"nombre": "   "})
    comprobar("un nombre vacio da 400", r.status_code == 400, r.status_code)
    r = c.put("/api/perfiles/noexiste", headers=AUTH, json={"nombre": "x"})
    comprobar("editar uno inexistente da 404", r.status_code == 404, r.status_code)

    r = c.post("/api/perfiles", headers=AUTH, json={"nombre": "Proyecto X", "vocabulario": "Foo"})
    comprobar("crear un perfil da 201", r.status_code == 201, r.text)
    proyecto = r.json()
    comprobar("y recibe el siguiente color", proyecto["color"] not in (empresa["color"], casa["color"]),
              proyecto["color"])

    print("\n-- grabaciones con perfil --")
    audio2 = b"RIFF....otro audio...." * 100
    r = c.post("/api/jobs", headers=AUTH, files={"file": ("a.m4a", audio2, "audio/mp4")},
               data={"titulo": "Con perfil", "perfil": empresa["id"], "vocabulario": "Epsilon, alfa",
                     "contexto": "  Reunion de administracion  "})
    comprobar("subir con perfil da 201", r.status_code == 201, r.text)
    con_perfil = r.json()
    comprobar("queda asociado", con_perfil["perfil"] == empresa["id"], con_perfil["perfil"])
    comprobar("y guarda el contexto sin espacios",
              con_perfil["contexto"] == "Reunion de administracion", con_perfil["contexto"])

    r = c.post("/api/jobs", headers=AUTH, files={"file": ("b.m4a", b"otro mas" * 50, "audio/mp4")},
               data={"perfil": "noexiste"})
    comprobar("subir a un perfil que no existe da 400", r.status_code == 400, r.status_code)
    comprobar("y no deja el audio a medias en disco",
              not list((TMP / "audio").glob(".subiendo-*")))

    # El worker recibe el vocabulario del perfil y el de la reunion, sumados.
    from app import db as _db
    for pendiente in c.get("/api/jobs?estado=pendiente", headers=AUTH).json()["trabajos"]:
        if pendiente["id"] != con_perfil["id"]:
            _db.actualizar(pendiente["id"], estado="hecho")
    r = c.post("/api/worker/reclamar", headers=AUTH, data={"worker": "prueba"})
    trabajo = r.json()["trabajo"]
    comprobar("el worker reclama el que tiene perfil", trabajo and trabajo["id"] == con_perfil["id"], trabajo)
    comprobar("y recibe perfil mas reunion, sin repetir",
              trabajo["vocabulario_total"] == "Alfa, Beta Gamma, Delta, Epsilon",
              trabajo["vocabulario_total"])
    comprobar("el de la reunion sigue siendo solo el suyo",
              trabajo["vocabulario"] == "Epsilon, alfa", trabajo["vocabulario"])

    r = c.post(f"/api/jobs/{con_perfil['id']}/ajustes", headers=AUTH, json={"perfil": casa["id"]})
    comprobar("cambiar el perfil de una reunion en marcha da 200", r.status_code == 200, r.text)
    comprobar("sin aviso falso: es una etiqueta", r.json().get("aviso") is None, r.json().get("aviso"))
    r = c.post(f"/api/jobs/{con_perfil['id']}/ajustes", headers=AUTH, json={"perfil": "noexiste"})
    comprobar("a un perfil inexistente da 400", r.status_code == 400, r.status_code)
    r = c.post(f"/api/jobs/{con_perfil['id']}/ajustes", headers=AUTH, json={"perfil": ""})
    comprobar("quitar el perfil se puede", r.json()["perfil"] is None, r.json()["perfil"])
    r = c.post(f"/api/jobs/{con_perfil['id']}/ajustes", headers=AUTH, json={"contexto": "Otra cosa"})
    comprobar("el contexto de una en marcha si avisa", bool(r.json().get("aviso")), r.json().get("aviso"))

    print("\n-- borrar un perfil --")
    c.post(f"/api/jobs/{con_perfil['id']}/ajustes", headers=AUTH, json={"perfil": proyecto["id"]})
    cuentas = {x["id"]: x["grabaciones"] for x in c.get("/api/perfiles", headers=AUTH).json()["perfiles"]}
    comprobar("el listado cuenta las grabaciones de cada perfil", cuentas[proyecto["id"]] == 1, cuentas)
    r = c.delete(f"/api/perfiles/{proyecto['id']}", headers=AUTH)
    comprobar("borrar un perfil da 200", r.status_code == 200, r.text)
    comprobar("y dice a cuantas grabaciones deja sin perfil",
              r.json()["grabaciones_sin_perfil"] == 1, r.json())
    sigue = c.get(f"/api/jobs/{con_perfil['id']}", headers=AUTH).json()
    comprobar("la grabacion no se pierde: solo se queda sin perfil",
              sigue["perfil"] is None and sigue["estado"] == "procesando", sigue)
    comprobar("borrarlo dos veces da 404",
              c.delete(f"/api/perfiles/{proyecto['id']}", headers=AUTH).status_code == 404)

    # Quien borra todos sus perfiles no quiere que reaparezcan al reiniciar.
    for x in c.get("/api/perfiles", headers=AUTH).json()["perfiles"]:
        c.delete(f"/api/perfiles/{x['id']}", headers=AUTH)
    _db.inicializar()
    comprobar("los de partida no se resiembran al reiniciar",
              c.get("/api/perfiles", headers=AUTH).json()["perfiles"] == [])

print("\n" + ("TODO OK" if not fallos else f"{len(fallos)} FALLOS: {fallos}"))
sys.exit(1 if fallos else 0)
