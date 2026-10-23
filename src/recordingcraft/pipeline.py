"""Pipeline de transcripcion: WhisperX (ASR + alineacion) + pyannote (diarizacion)."""

from __future__ import annotations

import datetime as dt
import gc
import logging
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any, Callable

from recordingcraft import audio as au
from recordingcraft.config import Config

Logger = Callable[[str], None]


def silenciar_ruido() -> None:
    """Calla los avisos conocidos e inofensivos de la pila de WhisperX.

    Ninguno afecta al resultado, pero tapan los mensajes utiles:
      - torchcodec: pyannote avisa de que no puede decodificar audio el mismo.
        Da igual: le pasamos la forma de onda ya decodificada con ffmpeg.
      - TF32 desactivado: decision de pyannote por reproducibilidad.
      - std() con 0 grados de libertad: ocurre con segmentos de voz muy cortos.
      - Lightning: migra el checkpoint de version en cada carga.

    Con RC_VERBOSE=1 no se filtra nada.
    """
    if os.environ.get("RC_VERBOSE", "").strip() in ("1", "true", "si"):
        return
    # Los patrones llevan "(?s).*" delante porque filterwarnings ancla al
    # principio del mensaje, y alguno de estos avisos empieza con un salto de
    # linea; sin eso, el filtro no llega a aplicarse nunca.
    for patron in (
        r"torchcodec is not installed correctly",
        r"TensorFloat-32 \(TF32\) has been disabled",
        r"degrees of freedom is <= 0",
        r"Lightning automatically upgraded",
        r"`torchaudio\..*` has been deprecated",
    ):
        warnings.filterwarnings("ignore", message=f"(?s).*{patron}")
    logging.getLogger("pytorch_lightning.utilities.migration").setLevel(logging.ERROR)
    logging.getLogger("lightning.pytorch.utilities.migration").setLevel(logging.ERROR)
    logging.getLogger("speechbrain").setLevel(logging.ERROR)


silenciar_ruido()

DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"


class PipelineError(RuntimeError):
    pass


def _free(device: str) -> None:
    gc.collect()
    if device == "cuda":
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass


def resolve_device(device: str, log: Logger) -> tuple[str, str | None]:
    """Devuelve (device efectivo, aviso) comprobando que CUDA este disponible."""
    if device != "cuda":
        return device, None
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - entorno sin torch
        raise PipelineError(
            "PyTorch no esta instalado. Ejecuta scripts/install.ps1 o revisa `rc doctor`."
        ) from exc
    if not torch.cuda.is_available():
        return "cpu", "CUDA no disponible: se usara CPU (mucho mas lento)."
    return "cuda", None


def _normalize_compute_type(device: str, compute_type: str) -> tuple[str, str | None]:
    if device == "cpu" and "float16" in compute_type:
        return "int8", f"compute_type '{compute_type}' no vale en CPU: se usa 'int8'."
    return compute_type, None


def _diarization_pipeline_cls():
    try:
        from whisperx.diarize import DiarizationPipeline  # whisperx >= 3.2

        return DiarizationPipeline
    except ImportError:
        pass
    import whisperx

    cls = getattr(whisperx, "DiarizationPipeline", None)
    if cls is None:
        raise PipelineError(
            "Esta version de WhisperX no expone DiarizationPipeline. "
            "Actualiza con: pip install -U whisperx"
        )
    return cls


def _build_diarizer(model_name: str, token: str, device: str):
    """WhisperX 3.8 usa el parametro `token`; las versiones antiguas, `use_auth_token`."""
    cls = _diarization_pipeline_cls()
    try:
        return cls(model_name=model_name, token=token, device=device)
    except TypeError:
        return cls(model_name=model_name, use_auth_token=token, device=device)


def _assign_word_speakers():
    import whisperx

    fn = getattr(whisperx, "assign_word_speakers", None)
    if fn is None:
        from whisperx.diarize import assign_word_speakers as fn  # type: ignore
    return fn


def _clean_segments(raw: list[dict]) -> list[dict]:
    out: list[dict] = []
    for seg in raw:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        words = []
        for word in seg.get("words") or []:
            entry = {"word": word.get("word", "")}
            for key in ("start", "end", "score", "speaker"):
                if word.get(key) is not None:
                    entry[key] = word[key]
            words.append(entry)
        item = {
            "start": round(float(seg.get("start") or 0.0), 3),
            "end": round(float(seg.get("end") or 0.0), 3),
            "text": text,
            "speaker": seg.get("speaker"),
        }
        if words:
            item["words"] = words
        out.append(item)
    return out


def transcribe(source: Path, cfg: Config, log: Logger,
               ajustes: dict | None = None) -> dict:
    """Procesa un fichero de audio y devuelve el dict que se guarda en meeting.json.

    `ajustes` permite afinar una grabacion concreta sin tocar la configuracion:
      vocabulario: terminos que el modelo tiene presentes en todo el audio
                   (nombres propios, modelos de aparatos, jerga del sector)
      hablantes:   cuantas personas hay, si se sabe
    """
    ajustes = ajustes or {}
    import whisperx

    wcfg = cfg.whisper
    device, warning = resolve_device(str(wcfg.get("device", "cuda")), log)
    if warning:
        log(f"  ! {warning}")
    compute_type, warning = _normalize_compute_type(device, str(wcfg.get("compute_type", "int8_float16")))
    if warning:
        log(f"  ! {warning}")

    language = str(wcfg.get("language") or "").strip().lower()
    language = None if language in ("", "auto") else language
    batch_size = int(wcfg.get("batch_size", 4))
    model_name = str(wcfg.get("model", "large-v3"))
    prompt = str(wcfg.get("initial_prompt") or "").strip()

    # El vocabulario de la reunion se suma al general, sin repetir terminos.
    terminos: list[str] = []
    for origen in (wcfg.get("vocabulario"), ajustes.get("vocabulario")):
        if not origen:
            continue
        trozos = origen.split(",") if isinstance(origen, str) else origen
        for termino in trozos:
            termino = str(termino).strip()
            if termino and termino.lower() not in {x.lower() for x in terminos}:
                terminos.append(termino)
    vocabulario = ", ".join(terminos)

    info = au.probe(source)
    duration = au.duration_seconds(info)
    started = dt.datetime.now()

    with tempfile.TemporaryDirectory(prefix="recordingcraft-") as tmp:
        wav = au.to_wav16k(source, Path(tmp) / "audio16k.wav")
        log(f"  · audio preparado ({fmt_hms(duration)})")

        asr_options: dict[str, Any] = {}
        if prompt:
            asr_options["initial_prompt"] = prompt
        if vocabulario:
            # hotwords pesa en todos los segmentos; initial_prompt solo al principio.
            asr_options["hotwords"] = vocabulario
            log(f"  · vocabulario: {len(terminos)} termino(s)")
        log(f"  · cargando modelo {model_name} en {device} ({compute_type})")
        # El token tambien lo necesita el VAD de pyannote que usa WhisperX por dentro.
        model = whisperx.load_model(
            model_name, device, compute_type=compute_type,
            language=language, asr_options=asr_options or None,
            use_auth_token=cfg.hf_token,
        )
        wave = whisperx.load_audio(str(wav))

        log("  · transcribiendo")
        result = model.transcribe(wave, batch_size=batch_size, print_progress=True)
        detected = result.get("language") or language or "es"
        del model
        _free(device)

        aligned = False
        if cfg.align.get("enabled", True):
            log(f"  · alineando palabras ({detected})")
            try:
                model_a, metadata = whisperx.load_align_model(
                    language_code=detected, device=device
                )
                result = whisperx.align(
                    result["segments"], model_a, metadata, wave, device,
                    return_char_alignments=False, print_progress=True,
                )
                aligned = True
                del model_a
                _free(device)
            except Exception as exc:
                log(f"  ! alineacion omitida: {exc}")

        diar_info = {"enabled": False, "model": None, "speakers_found": 0}
        if cfg.diarization.get("enabled", True):
            token = cfg.hf_token
            if not token:
                log("  ! sin HF_TOKEN: se omite la diarizacion (no habra hablantes)")
            else:
                log("  · identificando hablantes (pyannote)")
                try:
                    kwargs = {}
                    esperados = int(ajustes.get("hablantes") or 0) or int(
                        cfg.diarization.get("num_speakers", 0) or 0)
                    if esperados > 0:
                        kwargs["num_speakers"] = esperados
                        log(f"  · se esperan {esperados} hablante(s)")
                    else:
                        if int(cfg.diarization.get("min_speakers", 0) or 0) > 0:
                            kwargs["min_speakers"] = int(cfg.diarization["min_speakers"])
                        if int(cfg.diarization.get("max_speakers", 0) or 0) > 0:
                            kwargs["max_speakers"] = int(cfg.diarization["max_speakers"])

                    diar_model = str(cfg.diarization.get("model") or DEFAULT_DIARIZATION_MODEL)
                    diarizer = _build_diarizer(diar_model, token, device)
                    diarize_segments = diarizer(wave, **kwargs)
                    result = _assign_word_speakers()(diarize_segments, result)
                    diar_info = {"enabled": True, "model": diar_model,
                                 "speakers_found": 0}
                    del diarizer
                    _free(device)
                except Exception as exc:
                    log(f"  ! diarizacion fallida: {exc}")

    segments = _clean_segments(result.get("segments", []))
    labels = sorted({s["speaker"] for s in segments if s.get("speaker")})
    diar_info["speakers_found"] = len(labels)

    return {
        "schema": 1,
        "source_file": source.name,
        "duration": round(duration, 2),
        "language": detected,
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "aligned": aligned,
        "vocabulario": vocabulario or None,
        "diarization": diar_info,
        "speaker_labels": labels,
        "processed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "processing_seconds": round((dt.datetime.now() - started).total_seconds(), 1),
        "segments": segments,
    }


def fmt_hms(seconds: float) -> str:
    seconds = int(max(0.0, seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
