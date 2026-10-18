"""Generacion de las salidas legibles (md, txt, srt, json) de una reunion."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from recordingcraft import speakers as spk
from recordingcraft.store import Meeting


def fmt_clock(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_srt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_duration(seconds: float) -> str:
    seconds = int(max(0.0, float(seconds)))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h} h {m} min {s} s"
    if m:
        return f"{m} min {s} s"
    return f"{s} s"


@dataclass
class Turn:
    label: str
    name: str
    start: float
    end: float
    text: str


def merge_turns(segments: list[dict], mapping: dict[str, str], gap: float = 1.5) -> list[Turn]:
    """Agrupa segmentos consecutivos del mismo hablante en intervenciones."""
    turns: list[Turn] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        label = seg.get("speaker") or spk.UNKNOWN
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)

        last = turns[-1] if turns else None
        if last is not None and last.label == label and (start - last.end) <= gap:
            last.text = f"{last.text} {text}".strip()
            last.end = max(last.end, end)
        else:
            turns.append(Turn(label=label, name=spk.display_name(label, mapping),
                              start=start, end=end, text=text))
    return turns


def _meta_lines(meeting: Meeting) -> list[str]:
    d = meeting.data
    recorded = d.get("recorded_at", "")
    try:
        recorded = dt.datetime.fromisoformat(recorded).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        pass
    diar = d.get("diarization") or {}
    diar_txt = diar.get("model", "desactivada") if diar.get("enabled") else "desactivada"
    return [
        f"- **Grabacion**: {recorded}",
        f"- **Duracion**: {fmt_duration(d.get('duration', 0))}",
        f"- **Fichero original**: `{d.get('source_file', '?')}`",
        f"- **Modelo**: {d.get('model', '?')} · idioma `{d.get('language', '?')}`"
        + (" · alineado" if d.get("aligned") else " · sin alineacion"),
        f"- **Diarizacion**: {diar_txt}",
        f"- **Procesado**: {d.get('processed_at', '?')[:19].replace('T', ' ')}",
    ]


def render_markdown(meeting: Meeting, mapping: dict[str, str], gap: float,
                    timestamps: bool) -> str:
    turns = merge_turns(meeting.segments, mapping, gap)
    stats = spk.stats(meeting.segments, mapping)
    total = sum(s.seconds for s in stats) or 1.0

    titulo = (meeting.data.get("title") or "").strip() or meeting.id
    lines = [f"# {titulo}", ""]
    if titulo != meeting.id:
        lines += [f"`{meeting.id}`", ""]
    lines += _meta_lines(meeting)
    lines += ["", "## Hablantes", "",
              "| Hablante | Etiqueta | Tiempo | % | Intervenciones |",
              "| --- | --- | ---: | ---: | ---: |"]
    for s in stats:
        lines.append(
            f"| {s.name} | `{s.label}` | {fmt_duration(s.seconds)} | "
            f"{100 * s.seconds / total:.0f}% | {s.turns} |"
        )

    lines += ["", "## Transcripcion", ""]
    for turn in turns:
        stamp = f" `[{fmt_clock(turn.start)}]`" if timestamps else ""
        lines.append(f"**{turn.name}**{stamp}")
        lines.append("")
        lines.append(turn.text)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_text(meeting: Meeting, mapping: dict[str, str], gap: float) -> str:
    turns = merge_turns(meeting.segments, mapping, gap)
    return "\n".join(
        f"[{fmt_clock(t.start)}] {t.name}: {t.text}" for t in turns
    ) + "\n"


def render_srt(meeting: Meeting, mapping: dict[str, str]) -> str:
    blocks = []
    index = 1
    for seg in meeting.segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        name = spk.display_name(seg.get("speaker"), mapping)
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start + 1.0)
        blocks.append(
            f"{index}\n{fmt_srt(start)} --> {fmt_srt(end)}\n{name}: {text}\n"
        )
        index += 1
    return "\n".join(blocks)


def render_json(meeting: Meeting, mapping: dict[str, str], gap: float) -> str:
    turns = merge_turns(meeting.segments, mapping, gap)
    stats = spk.stats(meeting.segments, mapping)
    payload = {
        "id": meeting.id,
        "recorded_at": meeting.data.get("recorded_at"),
        "duration": meeting.data.get("duration"),
        "language": meeting.data.get("language"),
        "speakers": [
            {"label": s.label, "name": s.name, "seconds": round(s.seconds, 2),
             "turns": s.turns, "words": s.words}
            for s in stats
        ],
        "turns": [
            {"speaker": t.name, "label": t.label, "start": round(t.start, 2),
             "end": round(t.end, 2), "text": t.text}
            for t in turns
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_outputs(meeting: Meeting, mapping: dict[str, str], output_cfg: dict) -> list[Path]:
    """Escribe las salidas configuradas y devuelve las rutas generadas."""
    formats = [f.lower() for f in output_cfg.get("formats", ["md"])]
    gap = float(output_cfg.get("merge_gap_seconds", 1.5))
    timestamps = bool(output_cfg.get("timestamps", True))
    written: list[Path] = []

    if "md" in formats:
        target = meeting.path / "transcript.md"
        target.write_text(render_markdown(meeting, mapping, gap, timestamps), encoding="utf-8")
        written.append(target)
    if "txt" in formats:
        target = meeting.path / "transcript.txt"
        target.write_text(render_text(meeting, mapping, gap), encoding="utf-8")
        written.append(target)
    if "srt" in formats:
        target = meeting.path / "transcript.srt"
        target.write_text(render_srt(meeting, mapping), encoding="utf-8")
        written.append(target)
    if "json" in formats:
        target = meeting.path / "transcript.json"
        target.write_text(render_json(meeting, mapping, gap), encoding="utf-8")
        written.append(target)

    return written
