"""Utilidades de audio basadas en ffmpeg/ffprobe."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path


class AudioError(RuntimeError):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AudioError(
            f"No se encuentra '{name}' en el PATH. Instala ffmpeg "
            "(winget install Gyan.FFmpeg) y reinicia la terminal."
        )
    return path


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe(path: Path) -> dict:
    """Metadatos del fichero de audio via ffprobe."""
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise AudioError(f"ffprobe fallo con {path.name}: {out.stderr.strip()}")
    return json.loads(out.stdout or "{}")


def duration_seconds(info: dict) -> float:
    try:
        return float(info.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        return 0.0


_FILENAME_DATE_PATTERNS = [
    # Grabador del Pixel y variantes habituales de exportacion
    re.compile(r"(?P<y>20\d{2})[-_]?(?P<m>\d{2})[-_]?(?P<d>\d{2})[ _T-]+(?P<H>\d{2})[-_:]?(?P<M>\d{2})"),
    re.compile(r"(?P<y>20\d{2})[-_]?(?P<m>\d{2})[-_]?(?P<d>\d{2})"),
]


def recorded_at(path: Path, info: dict) -> dt.datetime:
    """Fecha de la grabacion: etiqueta del contenedor, nombre del fichero o mtime."""
    tags = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
    for key in ("creation_time", "date", "com.apple.quicktime.creationdate"):
        value = tags.get(key)
        if not value:
            continue
        try:
            text = str(value).replace("Z", "+00:00")
            stamp = dt.datetime.fromisoformat(text)
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone().replace(tzinfo=None)
            if stamp.year > 2000:
                return stamp
        except ValueError:
            continue

    for pattern in _FILENAME_DATE_PATTERNS:
        m = pattern.search(path.stem)
        if m:
            parts = m.groupdict()
            try:
                return dt.datetime(
                    int(parts["y"]), int(parts["m"]), int(parts["d"]),
                    int(parts.get("H") or 0), int(parts.get("M") or 0),
                )
            except ValueError:
                pass

    return dt.datetime.fromtimestamp(path.stat().st_mtime)


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def to_wav16k(src: Path, dest: Path) -> Path:
    """Convierte a WAV mono 16 kHz, que es lo que esperan WhisperX y pyannote."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(
        [_tool("ffmpeg"), "-nostdin", "-y", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        tail = "\n".join(out.stderr.strip().splitlines()[-5:])
        raise AudioError(f"ffmpeg no pudo convertir {src.name}:\n{tail}")
    return dest


def extract_clip(src: Path, dest: Path, start: float, duration: float) -> Path:
    """Recorta un fragmento de audio (para identificar hablantes de oido)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(
        [_tool("ffmpeg"), "-nostdin", "-y", "-ss", f"{max(0.0, start):.2f}",
         "-t", f"{max(0.5, duration):.2f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "22050", str(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        tail = "\n".join(out.stderr.strip().splitlines()[-5:])
        raise AudioError(f"ffmpeg no pudo extraer el fragmento: {tail}")
    return dest
