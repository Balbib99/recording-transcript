"""Cola de trabajos en SQLite.

Sin ORM a proposito: el modelo son cuatro campos y una tabla, y asi el servidor
no arrastra dependencias que compilar en ARM.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from typing import Any, Iterable

from app import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    titulo        TEXT,
    fichero       TEXT NOT NULL,
    extension     TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    estado        TEXT NOT NULL DEFAULT 'pendiente',
    creado        TEXT NOT NULL,
    reclamado     TEXT,
    terminado     TEXT,
    worker        TEXT,
    intentos      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    duracion      REAL,
    hablantes     INTEGER,
    idioma        TEXT,
    vocabulario   TEXT,
    esperados     INTEGER,
    voces         TEXT,
    perfil        TEXT,
    contexto      TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado, creado);
CREATE INDEX IF NOT EXISTS idx_jobs_sha    ON jobs(sha256);

CREATE TABLE IF NOT EXISTS perfiles (
    id            TEXT PRIMARY KEY,
    nombre        TEXT NOT NULL,
    color         INTEGER NOT NULL DEFAULT 0,
    vocabulario   TEXT,
    participantes TEXT,
    orden         INTEGER NOT NULL DEFAULT 0,
    creado        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estado (
    clave      TEXT PRIMARY KEY,
    valor      TEXT,
    actualizado TEXT NOT NULL
);
"""

ESTADOS = ("pendiente", "procesando", "hecho", "fallido")


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def nuevo_id() -> str:
    return uuid.uuid4().hex[:16]


def conexion() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    # WAL permite que el worker lea mientras la API escribe.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# Columnas anadidas despues de la primera version. SQLite no tiene
# "ADD COLUMN IF NOT EXISTS", asi que se comprueba y se anade a mano.
COLUMNAS_NUEVAS = {
    "vocabulario": "TEXT",
    "esperados": "INTEGER",
    "voces": "TEXT",
    "perfil": "TEXT",
    "contexto": "TEXT",
}


def inicializar() -> None:
    config.crear_directorios()
    with conexion() as con:
        con.executescript(ESQUEMA)
        existentes = {f["name"] for f in con.execute("PRAGMA table_info(jobs)")}
        for nombre, tipo in COLUMNAS_NUEVAS.items():
            if nombre not in existentes:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {nombre} {tipo}")
    sembrar_perfiles()


def _fila_a_dict(fila: sqlite3.Row) -> dict[str, Any]:
    return {k: fila[k] for k in fila.keys()}


def crear_job(*, titulo: str | None, fichero: str, extension: str, bytes_: int,
              sha256: str, vocabulario: str | None = None,
              esperados: int | None = None, perfil: str | None = None,
              contexto: str | None = None) -> dict[str, Any]:
    job_id = nuevo_id()
    with conexion() as con:
        con.execute(
            "INSERT INTO jobs (id, titulo, fichero, extension, bytes, sha256, estado,"
            " creado, vocabulario, esperados, perfil, contexto)"
            " VALUES (?,?,?,?,?,?,'pendiente',?,?,?,?,?)",
            (job_id, titulo, fichero, extension, bytes_, sha256, ahora(),
             vocabulario, esperados, perfil, contexto),
        )
    return obtener_job(job_id)  # type: ignore[return-value]


def obtener_job(job_id: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def buscar_por_sha(sha256: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT * FROM jobs WHERE sha256 = ? ORDER BY creado LIMIT 1", (sha256,)
        ).fetchone()
    return _fila_a_dict(fila) if fila else None


def listar_jobs(estado: str | None = None, limite: int = 50,
                desplazamiento: int = 0) -> list[dict[str, Any]]:
    consulta = "SELECT * FROM jobs"
    parametros: list[Any] = []
    if estado:
        consulta += " WHERE estado = ?"
        parametros.append(estado)
    consulta += " ORDER BY creado DESC LIMIT ? OFFSET ?"
    parametros += [limite, desplazamiento]
    with conexion() as con:
        filas = con.execute(consulta, parametros).fetchall()
    return [_fila_a_dict(f) for f in filas]


def contar_por_estado() -> dict[str, int]:
    with conexion() as con:
        filas = con.execute(
            "SELECT estado, COUNT(*) AS n FROM jobs GROUP BY estado"
        ).fetchall()
    conteo = {estado: 0 for estado in ESTADOS}
    conteo.update({f["estado"]: f["n"] for f in filas})
    return conteo


def borrar_job(job_id: str) -> bool:
    with conexion() as con:
        cur = con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return cur.rowcount > 0


def actualizar(job_id: str, **campos: Any) -> dict[str, Any] | None:
    """Actualiza solo las columnas conocidas que se pasen."""
    permitidas = {
        "titulo", "estado", "reclamado", "terminado", "worker",
        "intentos", "error", "duracion", "hablantes", "idioma",
        "vocabulario", "esperados", "voces", "perfil", "contexto",
    }
    cambios = {k: v for k, v in campos.items() if k in permitidas}
    if not cambios:
        return obtener_job(job_id)
    asignaciones = ", ".join(f"{k} = ?" for k in cambios)
    with conexion() as con:
        con.execute(
            f"UPDATE jobs SET {asignaciones} WHERE id = ?",
            [*cambios.values(), job_id],
        )
    return obtener_job(job_id)


def anotar(clave: str, valor: str) -> None:
    """Guarda un dato suelto con su marca de tiempo (el latido del worker)."""
    with conexion() as con:
        con.execute(
            "INSERT INTO estado (clave, valor, actualizado) VALUES (?,?,?)"
            " ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor,"
            " actualizado=excluded.actualizado",
            (clave, valor, ahora()),
        )


def leer_anotacion(clave: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT valor, actualizado FROM estado WHERE clave = ?", (clave,)
        ).fetchone()
    return {"valor": fila["valor"], "actualizado": fila["actualizado"]} if fila else None


def reclamar_siguiente(worker: str) -> dict[str, Any] | None:
    """Entrega el trabajo pendiente mas antiguo y lo marca como 'procesando'.

    La actualizacion condicional (`WHERE estado = 'pendiente'`) es lo que evita
    que dos workers se lleven el mismo trabajo: solo uno cambia la fila.
    """
    limite_abandono = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=config.CLAIM_TIMEOUT)
    ).isoformat(timespec="seconds")

    with conexion() as con:
        # Devuelve a la cola lo que un worker reclamo y nunca termino.
        con.execute(
            "UPDATE jobs SET estado = 'pendiente', worker = NULL"
            " WHERE estado = 'procesando' AND reclamado < ?",
            (limite_abandono,),
        )
        fila = con.execute(
            "SELECT id FROM jobs WHERE estado = 'pendiente' ORDER BY creado LIMIT 1"
        ).fetchone()
        if fila is None:
            return None
        cur = con.execute(
            "UPDATE jobs SET estado = 'procesando', worker = ?, reclamado = ?,"
            " intentos = intentos + 1 WHERE id = ? AND estado = 'pendiente'",
            (worker, ahora(), fila["id"]),
        )
        if cur.rowcount == 0:
            return None  # otro worker se adelanto
    return obtener_job(fila["id"])


# ------------------------------------------------------------------- perfiles
# Un perfil es un contexto de trabajo (la empresa, la casa...): su propio
# vocabulario y la gente con la que se suele hablar. Se guardan aqui, en el
# servidor de cada cual, y no en el repositorio: los terminos de una empresa no
# tienen por que estar en un codigo publico.

PERFILES_INICIALES = ("Empresa", "Casa")
COLORES = 6   # los que sabe pintar la app


def sembrar_perfiles() -> None:
    """Crea los perfiles de partida la primera vez, y nunca mas.

    Se recuerda con una anotacion en vez de mirar si la tabla esta vacia: quien
    borre todos sus perfiles no quiere que reaparezcan al reiniciar.
    """
    if leer_anotacion("perfiles_sembrados"):
        return
    with conexion() as con:
        if con.execute("SELECT COUNT(*) FROM perfiles").fetchone()[0] == 0:
            for orden, nombre in enumerate(PERFILES_INICIALES):
                con.execute(
                    "INSERT INTO perfiles (id, nombre, color, orden, creado)"
                    " VALUES (?,?,?,?,?)",
                    (nuevo_id(), nombre, orden % COLORES, orden, ahora()),
                )
    anotar("perfiles_sembrados", "1")


def listar_perfiles() -> list[dict[str, Any]]:
    with conexion() as con:
        filas = con.execute("SELECT * FROM perfiles ORDER BY orden, creado").fetchall()
    return [_fila_a_dict(f) for f in filas]


def obtener_perfil(perfil_id: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute("SELECT * FROM perfiles WHERE id = ?", (perfil_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def crear_perfil(*, nombre: str, vocabulario: str | None = None,
                 participantes: str | None = None) -> dict[str, Any]:
    perfil_id = nuevo_id()
    with conexion() as con:
        orden = con.execute("SELECT COALESCE(MAX(orden), -1) + 1 FROM perfiles").fetchone()[0]
        con.execute(
            "INSERT INTO perfiles (id, nombre, color, vocabulario, participantes, orden, creado)"
            " VALUES (?,?,?,?,?,?,?)",
            (perfil_id, nombre, orden % COLORES, vocabulario, participantes, orden, ahora()),
        )
    return obtener_perfil(perfil_id)  # type: ignore[return-value]


def actualizar_perfil(perfil_id: str, **campos: Any) -> dict[str, Any] | None:
    cambios = {k: v for k, v in campos.items()
               if k in {"nombre", "vocabulario", "participantes"}}
    if not cambios:
        return obtener_perfil(perfil_id)
    asignaciones = ", ".join(f"{k} = ?" for k in cambios)
    with conexion() as con:
        con.execute(f"UPDATE perfiles SET {asignaciones} WHERE id = ?",
                    [*cambios.values(), perfil_id])
    return obtener_perfil(perfil_id)


def borrar_perfil(perfil_id: str) -> int:
    """Borra el perfil y deja sin perfil a sus grabaciones. Devuelve cuantas eran."""
    with conexion() as con:
        sueltas = con.execute("UPDATE jobs SET perfil = NULL WHERE perfil = ?",
                              (perfil_id,)).rowcount
        con.execute("DELETE FROM perfiles WHERE id = ?", (perfil_id,))
    return sueltas


def contar_jobs_por_perfil() -> dict[str, int]:
    with conexion() as con:
        filas = con.execute(
            "SELECT perfil, COUNT(*) AS n FROM jobs WHERE perfil IS NOT NULL GROUP BY perfil"
        ).fetchall()
    return {f["perfil"]: f["n"] for f in filas}
