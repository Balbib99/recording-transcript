"""Mapeo de etiquetas SPEAKER_xx a nombres reales y estadisticas por hablante."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

UNKNOWN = "SIN_IDENTIFICAR"

HEADER = """# Hablantes detectados en esta reunion.
# Cambia el valor de la derecha por el nombre real y vuelve a generar las
# transcripciones con:   rc render {meeting_id}
# (el audio NO se vuelve a procesar: solo se reescriben las salidas)
#
# Tambien puedes hacerlo sin editar el fichero:
#   rc speakers {meeting_id} --set SPEAKER_00=Ana --set SPEAKER_01="Carlos Ruiz"

[speakers]"""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    raw = data.get("speakers", {})
    return {str(k): str(v) for k, v in raw.items() if str(v).strip()}


def write_map(path: Path, mapping: dict[str, str], meeting_id: str) -> None:
    lines = [HEADER.format(meeting_id=meeting_id)]
    for label in sorted(mapping):
        lines.append(f'{label} = "{_escape(mapping[label])}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_map(path: Path, labels: list[str], meeting_id: str) -> dict[str, str]:
    """Crea o completa speakers.toml con las etiquetas detectadas."""
    mapping = read_map(path)
    changed = False
    for label in labels:
        if label not in mapping:
            mapping[label] = label
            changed = True
    if changed or not path.is_file():
        write_map(path, mapping, meeting_id)
    return mapping


def display_name(label: str | None, mapping: dict[str, str]) -> str:
    if not label:
        return mapping.get(UNKNOWN, UNKNOWN)
    return mapping.get(label, label)


@dataclass
class SpeakerStats:
    label: str
    name: str
    seconds: float = 0.0
    turns: int = 0
    first_start: float = 0.0
    words: int = 0
    sample_text: str = ""
    sample_start: float = 0.0
    sample_duration: float = 0.0


def stats(segments: list[dict], mapping: dict[str, str]) -> list[SpeakerStats]:
    """Tiempo de voz, intervenciones y mejor fragmento de muestra por hablante."""
    out: dict[str, SpeakerStats] = {}
    previous: str | None = None

    for seg in segments:
        label = seg.get("speaker") or UNKNOWN
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        text = (seg.get("text") or "").strip()

        item = out.get(label)
        if item is None:
            item = SpeakerStats(label=label, name=display_name(label, mapping),
                                first_start=start)
            out[label] = item

        item.seconds += max(0.0, end - start)
        item.words += len(text.split())
        if label != previous:
            item.turns += 1
        # Nos quedamos con el fragmento mas largo como muestra de voz.
        if (end - start) > item.sample_duration and text:
            item.sample_duration = end - start
            item.sample_start = start
            item.sample_text = text
        previous = label

    return sorted(out.values(), key=lambda s: s.seconds, reverse=True)
