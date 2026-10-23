"""Carga de configuracion y resolucion de rutas del proyecto."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def project_root() -> Path:
    """Raiz del proyecto (dos niveles por encima de este fichero)."""
    return Path(__file__).resolve().parents[2]


DEFAULTS: dict = {
    "paths": {
        "inbox": "data/inbox",
        "meetings": "data/meetings",
        "archive": "data/archive",
    },
    "input": {
        "extensions": [".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".amr"],
        "on_success": "archive",
        "keep_audio_in_meeting": True,
    },
    "whisper": {
        "model": "large-v3",
        "language": "es",
        "device": "cuda",
        "compute_type": "int8_float16",
        "batch_size": 4,
        "initial_prompt": "",
        "vocabulario": "",
    },
    "align": {"enabled": True},
    "diarization": {
        "enabled": True,
        "model": "pyannote/speaker-diarization-community-1",
        "num_speakers": 0,
        "min_speakers": 0,
        "max_speakers": 0,
    },
    "privacy": {
        "telemetry": False,
        "offline": False,
    },
    "output": {
        "formats": ["md", "txt", "srt", "json"],
        "merge_gap_seconds": 1.5,
        "timestamps": True,
        "sample_clip_seconds": 12,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_env_file(path: Path) -> None:
    """Carga un .env sencillo en os.environ sin pisar variables ya definidas."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    root: Path
    data: dict = field(default_factory=dict)

    # --- rutas ---------------------------------------------------------
    def _path(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p)

    @property
    def inbox(self) -> Path:
        return self._path(self.data["paths"]["inbox"])

    @property
    def meetings(self) -> Path:
        return self._path(self.data["paths"]["meetings"])

    @property
    def archive(self) -> Path:
        return self._path(self.data["paths"]["archive"])

    # --- secciones -----------------------------------------------------
    @property
    def input(self) -> dict:
        return self.data["input"]

    @property
    def whisper(self) -> dict:
        return self.data["whisper"]

    @property
    def align(self) -> dict:
        return self.data["align"]

    @property
    def diarization(self) -> dict:
        return self.data["diarization"]

    @property
    def output(self) -> dict:
        return self.data["output"]

    @property
    def privacy(self) -> dict:
        return self.data["privacy"]

    def apply_privacy_env(self) -> None:
        """Fija las variables de entorno que controlan telemetria y red.

        Se llama antes de importar whisperx/pyannote: pyannote.audio 4.x lee
        PYANNOTE_METRICS_ENABLED al importar su modulo de telemetria, y manda
        trazas a https://otel.pyannote.ai si vale "true".
        """
        if not self.privacy.get("telemetry", False):
            os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            os.environ["DO_NOT_TRACK"] = "1"
        if self.privacy.get("offline", False):
            # Nada de red: solo se usan los modelos ya descargados en la cache.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

    @property
    def hf_token(self) -> str | None:
        for var in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            token = os.environ.get(var)
            if token:
                return token.strip()
        return None

    def ensure_dirs(self) -> None:
        for path in (self.inbox, self.meetings, self.archive):
            path.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> Config:
    root = project_root()
    load_env_file(root / ".env")

    if path is None:
        candidate = root / "config.toml"
        path = candidate if candidate.is_file() else None

    data = DEFAULTS
    if path is not None:
        with open(path, "rb") as fh:
            data = _deep_merge(DEFAULTS, tomllib.load(fh))

    cfg = Config(root=root, data=data)
    cfg.apply_privacy_env()
    return cfg
