"""Genera el texto y el Markdown de una transcripcion a partir de sus datos.

Vive en el servidor y no en el worker porque los nombres de los hablantes se
pueden cambiar despues de transcribir: si el texto se generase solo una vez en
el worker, quedaria con los nombres viejos.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any


def voces_json(hablantes: list[dict[str, Any]] | None) -> str | None:
    """Nombres de las voces, en orden, con cadena vacia en las sin nombrar.

    Se guarda resuelto en la fila del trabajo para que el listado pueda decir
    quien habla sin abrir el JSON de cada transcripcion, que es grande.
    """
    if not hablantes:
        return None
    nombres = []
    for hablante in hablantes:
        nombre = str(hablante.get("nombre") or "").strip()
        nombres.append("" if not nombre or nombre == hablante.get("etiqueta") else nombre)
    return json.dumps(nombres, ensure_ascii=False)


def reloj(segundos: Any) -> str:
    s = max(0, int(segundos or 0))
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{seg:02d}"


def duracion(segundos: Any) -> str:
    s = int(segundos or 0)
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min {seg} s"
    return f"{seg} s"


def nombres_por_etiqueta(datos: dict[str, Any]) -> dict[str, str]:
    return {
        h.get("etiqueta"): h.get("nombre") or h.get("etiqueta")
        for h in datos.get("hablantes") or []
        if h.get("etiqueta")
    }


def texto(datos: dict[str, Any]) -> str:
    nombres = nombres_por_etiqueta(datos)
    lineas = [
        f"[{reloj(t.get('inicio'))}] {nombres.get(t.get('hablante'), t.get('hablante'))}: "
        f"{(t.get('texto') or '').strip()}"
        for t in datos.get("turnos") or []
    ]
    return "\n".join(lineas) + ("\n" if lineas else "")


def markdown(datos: dict[str, Any]) -> str:
    nombres = nombres_por_etiqueta(datos)
    titulo = datos.get("titulo") or datos.get("id") or "Reunion"

    grabado = datos.get("grabado") or ""
    try:
        grabado = dt.datetime.fromisoformat(grabado).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        pass

    lineas = [f"# {titulo}", ""]
    if grabado:
        lineas.append(f"- **Grabacion**: {grabado}")
    lineas += [
        f"- **Duracion**: {duracion(datos.get('duracion'))}",
        f"- **Idioma**: {datos.get('idioma') or '-'}",
        f"- **Modelo**: {datos.get('modelo') or '-'}",
    ]

    hablantes = datos.get("hablantes") or []
    total = sum(float(h.get("segundos") or 0) for h in hablantes) or 1.0
    if hablantes:
        lineas += ["", "## Hablantes", "",
                   "| Hablante | Tiempo | % | Intervenciones |",
                   "| --- | ---: | ---: | ---: |"]
        for h in hablantes:
            segundos = float(h.get("segundos") or 0)
            lineas.append(
                f"| {h.get('nombre') or h.get('etiqueta')} | {duracion(segundos)} | "
                f"{100 * segundos / total:.0f}% | {h.get('intervenciones') or 0} |"
            )

    lineas += ["", "## Transcripcion", ""]
    for t in datos.get("turnos") or []:
        quien = nombres.get(t.get("hablante"), t.get("hablante"))
        lineas += [f"**{quien}** `[{reloj(t.get('inicio'))}]`", "",
                   (t.get("texto") or "").strip(), ""]

    return "\n".join(lineas).rstrip() + "\n"


def regenerar(datos: dict[str, Any]) -> dict[str, Any]:
    """Rehace texto y markdown con los nombres actuales."""
    datos["texto"] = texto(datos)
    datos["markdown"] = markdown(datos)
    return datos
