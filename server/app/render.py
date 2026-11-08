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


# ------------------------------------------------------------ para Claude

PETICION_POR_DEFECTO = (
    "Ordena el contenido por temas, aunque se hayan tratado en momentos distintos de "
    "la reunión, citando el minuto de cada punto. Después, por separado: decisiones "
    "tomadas, tareas (quién y qué) y dudas que quedaron abiertas. Si te paso ficheros "
    "junto a esta transcripción, relaciona lo que se dice con ellos."
)


def nombres_legibles(datos: dict[str, Any]) -> dict[str, str]:
    """Como nombres_por_etiqueta, pero las voces sin nombre son "Persona N".

    SPEAKER_01 no le dice nada a quien lee; "Persona 1" deja claro que es una
    persona concreta de la que no se sabe el nombre. Se numeran en el orden de
    la lista de hablantes.
    """
    nombres: dict[str, str] = {}
    sin_nombre = 0
    for h in datos.get("hablantes") or []:
        etiqueta = h.get("etiqueta")
        if not etiqueta:
            continue
        nombre = str(h.get("nombre") or "").strip()
        if not nombre or nombre == etiqueta:
            sin_nombre += 1
            nombre = f"Persona {sin_nombre}"
        nombres[etiqueta] = nombre
    return nombres


def para_claude(datos: dict[str, Any], *, titulo: str | None = None,
                perfil: str | None = None, contexto: str | None = None,
                glosario: list[str] | None = None, peticion: str | None = None) -> str:
    """Markdown pensado para pegarlo en una conversacion con Claude.

    Ademas de la transcripcion lleva lo que un lector necesita para no
    malinterpretarla: quien habla, de que va, que terminos son nombres propios
    del sector y que limitaciones tiene una transcripcion automatica. Al final,
    lo que se le pide, para no tener que escribirlo cada vez.
    """
    nombres = nombres_legibles(datos)
    lineas = [f"# {titulo or datos.get('titulo') or 'Reunión'}", ""]

    grabado = datos.get("grabado") or ""
    try:
        grabado = dt.datetime.fromisoformat(grabado).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        pass
    if grabado:
        lineas.append(f"- **Fecha**: {grabado}")
    lineas.append(f"- **Duración**: {duracion(datos.get('duracion'))}")
    if perfil:
        lineas.append(f"- **Ámbito**: {perfil}")
    if contexto:
        lineas.append(f"- **De qué va**: {contexto}")

    hablantes = datos.get("hablantes") or []
    total = sum(float(h.get("segundos") or 0) for h in hablantes) or 1.0
    if hablantes:
        lineas.append("- **Participantes**:")
        for h in hablantes:
            segundos = float(h.get("segundos") or 0)
            lineas.append(
                f"  - {nombres.get(h.get('etiqueta'), h.get('etiqueta'))}: "
                f"{100 * segundos / total:.0f}% del tiempo, "
                f"{h.get('intervenciones') or 0} intervenciones")

    if glosario:
        lineas += ["", "## Glosario", "",
                   "Nombres propios, marcas y modelos que pueden salir en la reunión. "
                   "Si en la transcripción aparece algo parecido, seguramente es uno "
                   "de estos:", "", ", ".join(glosario)]

    lineas += [
        "", "## Cómo leer esta transcripción", "",
        "- Es automática (WhisperX), grabada con un móvil. Puede haber palabras mal "
        "reconocidas, sobre todo nombres propios que no estén en el glosario: "
        "interprétalas por el contexto y, si no estás seguro, dilo en vez de suponer.",
        "- Quién habla en cada momento es una estimación: una frase corta puede estar "
        "atribuida a otra persona, y una intervención puede mezclar a dos.",
        "- Lo que dijo quien estaba lejos del móvil puede faltar o estar incompleto.",
        "- [mm:ss] es el minuto de la grabación.",
        "", "## Transcripción", "",
    ]
    for t in datos.get("turnos") or []:
        quien = nombres.get(t.get("hablante"), t.get("hablante") or "?")
        minuto = reloj(t.get("inicio"))
        minuto = minuto[3:] if minuto.startswith("00:") else minuto
        lineas += [f"**{quien}** [{minuto}]: {(t.get('texto') or '').strip()}", ""]

    lineas += ["## Lo que te pido", "", (peticion or "").strip() or PETICION_POR_DEFECTO]
    return "\n".join(lineas).rstrip() + "\n"
