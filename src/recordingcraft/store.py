"""Organizacion en disco de las reuniones procesadas."""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MEETING_JSON = "meeting.json"


def slugify(text: str, max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:max_len].strip("-") or "reunion"


def meeting_id(recorded_at: dt.datetime, title: str) -> str:
    return f"{recorded_at:%Y-%m-%d_%H%M}_{slugify(title)}"


@dataclass
class Meeting:
    path: Path
    data: dict

    @property
    def id(self) -> str:
        return self.data.get("id", self.path.name)

    @property
    def segments(self) -> list[dict]:
        return self.data.get("segments", [])

    @property
    def speakers_file(self) -> Path:
        return self.path / "speakers.toml"

    @property
    def audio_file(self) -> Path | None:
        name = self.data.get("audio_file")
        if name:
            candidate = self.path / name
            if candidate.is_file():
                return candidate
        for ext in (".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".amr"):
            hits = sorted(self.path.glob(f"audio{ext}"))
            if hits:
                return hits[0]
        return None

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / MEETING_JSON).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> "Meeting":
        payload = json.loads((path / MEETING_JSON).read_text(encoding="utf-8"))
        return cls(path=path, data=payload)


def iter_meetings(meetings_dir: Path):
    if not meetings_dir.is_dir():
        return
    for child in sorted(meetings_dir.iterdir()):
        if (child / MEETING_JSON).is_file():
            yield Meeting.load(child)


def find_meeting(meetings_dir: Path, needle: str) -> Meeting | None:
    """Busca por id exacto, por prefijo o por coincidencia parcial."""
    exact = meetings_dir / needle
    if (exact / MEETING_JSON).is_file():
        return Meeting.load(exact)

    needle_low = needle.lower()
    matches = [m for m in iter_meetings(meetings_dir) if needle_low in m.id.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        starts = [m for m in matches if m.id.lower().startswith(needle_low)]
        if len(starts) == 1:
            return starts[0]
        raise LookupError(
            "Varias reuniones coinciden con '%s':\n  %s"
            % (needle, "\n  ".join(m.id for m in matches))
        )
    return None


def processed_hashes(meetings_dir: Path) -> dict[str, str]:
    """sha256 del audio original -> id de la reunion, para no reprocesar."""
    out: dict[str, str] = {}
    for meeting in iter_meetings(meetings_dir):
        digest = meeting.data.get("sha256")
        if digest:
            out[digest] = meeting.id
    return out


def unique_dir(meetings_dir: Path, base_id: str) -> Path:
    candidate = meetings_dir / base_id
    counter = 2
    while candidate.exists():
        candidate = meetings_dir / f"{base_id}-{counter}"
        counter += 1
    return candidate
