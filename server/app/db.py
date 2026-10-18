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
    idioma        TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado, creado);
CREATE INDEX IF NOT EXISTS idx_jobs_sha    ON jobs(sha256);
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


def inicializar() -> None:
    config.crear_directorios()
    with conexion() as con:
        con.executescript(ESQUEMA)


def _fila_a_dict(fila: sqlite3.Row) -> dict[str, Any]:
    return {k: fila[k] for k in fila.keys()}


def crear_job(*, titulo: str | None, fichero: str, extension: str, bytes_: int,
              sha256: str) -> dict[str, Any]:
    job_id = nuevo_id()
    with conexion() as con:
        con.execute(
            "INSERT INTO jobs (id, titulo, fichero, extension, bytes, sha256, estado, creado)"
            " VALUES (?,?,?,?,?,?,'pendiente',?)",
            (job_id, titulo, fichero, extension, bytes_, sha256, ahora()),
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
