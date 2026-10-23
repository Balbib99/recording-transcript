"""Interfaz de linea de comandos de RecordingCraft."""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

from recordingcraft import __version__, audio as au, outputs, speakers as spk, store
from recordingcraft.config import Config, load_config


def _force_utf8_output() -> None:
    """Evita que la codepage de Windows rompa los acentos en el terminal."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def log(message: str = "") -> None:
    print(message, flush=True)


# ---------------------------------------------------------------- utilidades

def _resolve_meeting(cfg: Config, needle: str) -> store.Meeting:
    try:
        meeting = store.find_meeting(cfg.meetings, needle)
    except LookupError as exc:
        raise SystemExit(str(exc))
    if meeting is None:
        raise SystemExit(f"No encuentro ninguna reunion que coincida con '{needle}'.")
    return meeting


def _unique_target(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while target.exists():
        target = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return target


def _collect_inputs(cfg: Config, paths: list[str]) -> list[Path]:
    extensions = {e.lower() for e in cfg.input.get("extensions", [])}
    files: list[Path] = []

    if paths:
        for raw in paths:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (Path.cwd() / p).resolve()
            if p.is_dir():
                files += [f for f in sorted(p.rglob("*"))
                          if f.is_file() and f.suffix.lower() in extensions]
            elif p.is_file():
                files.append(p)
            else:
                log(f"! No existe: {p}")
    else:
        files = [f for f in sorted(cfg.inbox.rglob("*"))
                 if f.is_file() and f.suffix.lower() in extensions]

    return files


# ------------------------------------------------------------------ comandos

def cmd_doctor(args: argparse.Namespace, cfg: Config) -> int:
    ok = True

    def check(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        mark = "OK   " if good else "FALLA"
        log(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")

    log(f"RecordingCraft {__version__}")
    log(f"Proyecto: {cfg.root}")
    log("")
    log("Entorno:")
    v = sys.version_info
    check(f"Python {v.major}.{v.minor}.{v.micro}", v >= (3, 10),
          "" if v >= (3, 10) else "se necesita 3.10 o superior")
    check("ffmpeg / ffprobe", au.have_ffmpeg(),
          "" if au.have_ffmpeg() else "instala ffmpeg y reinicia la terminal")

    try:
        import torch

        cuda = torch.cuda.is_available()
        detail = ""
        if cuda:
            props = torch.cuda.get_device_properties(0)
            detail = f"{props.name}, {props.total_memory / 1024 ** 3:.1f} GB"
        check(f"PyTorch {torch.__version__}", True)
        check("CUDA disponible", cuda, detail or "se usara CPU (mucho mas lento)")
    except ImportError:
        check("PyTorch", False, "no instalado: ejecuta scripts/install.ps1")

    try:
        from importlib.metadata import version

        import whisperx  # noqa: F401

        try:
            wx_version = version("whisperx")
        except Exception:
            wx_version = "?"
        check(f"WhisperX {wx_version}", True)
    except Exception as exc:
        check("WhisperX", False, f"{type(exc).__name__}: {exc}")

    log("")
    log("Configuracion:")
    cfg_file = cfg.root / "config.toml"
    check("config.toml", cfg_file.is_file(),
          "" if cfg_file.is_file() else "no existe: se usan valores por defecto (copia config.example.toml)")
    token = cfg.hf_token
    check("HF_TOKEN", bool(token),
          "" if token else "sin token no hay diarizacion, es decir, no se sabe quien dice que")

    log("")
    log("Privacidad:")
    telemetry = bool(cfg.privacy.get("telemetry", False))
    offline = bool(cfg.privacy.get("offline", False))
    check("Telemetria de pyannote desactivada", not telemetry,
          "" if not telemetry else "privacy.telemetry = true: se envian trazas a otel.pyannote.ai")
    log(f"  [{'OK   ' if offline else 'info '}] Modo sin red: "
        + ("activado, no se contacta con ningun servidor"
           if offline else "desactivado (se consulta huggingface.co al cargar modelos)"))

    if token and not offline:
        # auth_check comprueba el acceso REAL al contenido del repo: model_info
        # responde igual aunque no hayas aceptado las condiciones del modelo.
        from recordingcraft.pipeline import DEFAULT_DIARIZATION_MODEL

        diar_model = str(cfg.diarization.get("model") or DEFAULT_DIARIZATION_MODEL)
        repos = [diar_model]
        if "3.1" in diar_model:
            # El pipeline antiguo tira ademas de estos dos repos.
            repos += ["pyannote/segmentation-3.0", DEFAULT_DIARIZATION_MODEL]
        for repo in repos:
            try:
                from huggingface_hub import HfApi

                HfApi().auth_check(repo, token=token)
                check(f"Acceso a {repo}", True)
            except Exception as exc:
                name = type(exc).__name__
                hint = (f"https://huggingface.co/{repo} -> boton 'Agree and access repository'"
                        if "Gated" in name or "403" in str(exc)
                        else f"{name}: {exc}")
                check(f"Acceso a {repo}", False, hint)
    elif token and offline:
        log("  [info ] Acceso a los modelos: no se comprueba en modo sin red")

    log("")
    log("Carpetas:")
    for label, path in (("inbox", cfg.inbox), ("meetings", cfg.meetings), ("archive", cfg.archive)):
        check(f"{label}: {path}", path.is_dir(), "" if path.is_dir() else "se creara al procesar")

    log("")
    log("Ajustes activos:")
    w = cfg.whisper
    log(f"  modelo={w['model']}  idioma={w['language'] or 'auto'}  device={w['device']}  "
        f"compute_type={w['compute_type']}  batch_size={w['batch_size']}")
    log(f"  alineacion={'si' if cfg.align.get('enabled') else 'no'}  "
        f"diarizacion={'si' if cfg.diarization.get('enabled') else 'no'}  "
        f"formatos={','.join(cfg.output.get('formats', []))}")

    log("")
    log("Todo listo." if ok else "Hay cosas pendientes (ver las lineas FALLA).")
    return 0 if ok else 1


def cmd_process(args: argparse.Namespace, cfg: Config) -> int:
    from recordingcraft import pipeline

    cfg.ensure_dirs()

    # Sobrescrituras puntuales desde la linea de comandos.
    if args.model:
        cfg.whisper["model"] = args.model
    if args.language:
        cfg.whisper["language"] = args.language
    if args.device:
        cfg.whisper["device"] = args.device
    if args.speakers is not None:
        cfg.diarization["num_speakers"] = args.speakers
    if args.min_speakers is not None:
        cfg.diarization["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        cfg.diarization["max_speakers"] = args.max_speakers
    if args.no_diarization:
        cfg.diarization["enabled"] = False
    if args.vocabulario:
        cfg.whisper["vocabulario"] = args.vocabulario

    files = _collect_inputs(cfg, args.paths)
    if not files:
        log(f"No hay grabaciones nuevas en {cfg.inbox}")
        return 0

    done = store.processed_hashes(cfg.meetings)
    processed = skipped = failed = 0

    for index, src in enumerate(files, start=1):
        log(f"[{index}/{len(files)}] {src.name}")
        try:
            digest = au.sha256(src)
            if digest in done and not args.force:
                log(f"  · ya procesado como {done[digest]} (usa --force para repetirlo)")
                skipped += 1
                log("")
                continue

            info = au.probe(src)
            recorded = au.recorded_at(src, info)
            title = args.title if (args.title and len(files) == 1) else src.stem
            meeting_dir = store.unique_dir(cfg.meetings, store.meeting_id(recorded, title))

            data = pipeline.transcribe(src, cfg, log)
            data["id"] = meeting_dir.name
            data["title"] = title
            data["recorded_at"] = recorded.isoformat(timespec="seconds")
            data["sha256"] = digest

            meeting_dir.mkdir(parents=True, exist_ok=True)

            if cfg.input.get("keep_audio_in_meeting", True):
                audio_copy = meeting_dir / f"audio{src.suffix.lower()}"
                shutil.copy2(src, audio_copy)
                data["audio_file"] = audio_copy.name

            meeting = store.Meeting(path=meeting_dir, data=data)
            meeting.save()

            labels = data.get("speaker_labels") or []
            mapping = spk.ensure_map(meeting.speakers_file, labels, meeting.id)
            written = outputs.write_outputs(meeting, mapping, cfg.output)

            # Si el original ya estaba en el archivo (reproceso), no se mueve.
            already_archived = src.parent.resolve() == cfg.archive.resolve()
            if (cfg.input.get("on_success", "archive") == "archive"
                    and src.is_file() and not already_archived):
                try:
                    shutil.move(str(src), str(_unique_target(cfg.archive, src.name)))
                except OSError as exc:
                    log(f"  ! no se pudo archivar el original: {exc}")

            done[digest] = meeting.id
            processed += 1
            log(f"  · {len(labels)} hablante(s), {len(data['segments'])} segmentos, "
                f"{data['processing_seconds']:.0f}s de proceso")
            log(f"  -> {meeting_dir}")
            for path in written:
                log(f"     {path.name}")
            if labels:
                log(f"  Siguiente paso: rc speakers {meeting.id} --clips")
        except Exception as exc:
            failed += 1
            log(f"  ! ERROR: {exc}")
            if args.debug:
                traceback.print_exc()
        log("")

    log(f"Hecho: {processed} procesada(s), {skipped} omitida(s), {failed} con error.")
    return 1 if failed else 0


def cmd_list(args: argparse.Namespace, cfg: Config) -> int:
    meetings = list(store.iter_meetings(cfg.meetings))
    if not meetings:
        log(f"No hay reuniones en {cfg.meetings}")
        return 0
    log(f"{len(meetings)} reunion(es) en {cfg.meetings}")
    log("")
    for meeting in meetings:
        mapping = spk.read_map(meeting.speakers_file)
        names = [s.name for s in spk.stats(meeting.segments, mapping)]
        pending = sum(1 for n in names if n.startswith("SPEAKER_"))
        log(f"  {meeting.id}")
        log(f"      {outputs.fmt_duration(meeting.data.get('duration', 0))} · "
            f"{len(names)} hablante(s)"
            + (f" · {pending} sin nombrar" if pending else "")
            + (f" · {', '.join(names[:6])}" if names else ""))
    return 0


def cmd_show(args: argparse.Namespace, cfg: Config) -> int:
    meeting = _resolve_meeting(cfg, args.meeting)
    md = meeting.path / "transcript.md"
    if md.is_file():
        log(md.read_text(encoding="utf-8"))
    else:
        mapping = spk.read_map(meeting.speakers_file)
        log(outputs.render_markdown(meeting, mapping,
                                    float(cfg.output.get("merge_gap_seconds", 1.5)),
                                    bool(cfg.output.get("timestamps", True))))
    return 0


def cmd_speakers(args: argparse.Namespace, cfg: Config) -> int:
    meeting = _resolve_meeting(cfg, args.meeting)
    labels = meeting.data.get("speaker_labels") or []
    mapping = spk.ensure_map(meeting.speakers_file, labels, meeting.id)

    if args.set:
        for pair in args.set:
            if "=" not in pair:
                raise SystemExit(f"Formato invalido: '{pair}'. Usa ETIQUETA=Nombre")
            label, _, name = pair.partition("=")
            label, name = label.strip(), name.strip()
            if not name:
                raise SystemExit(f"Falta el nombre para '{label}'.")
            if label not in mapping:
                raise SystemExit(
                    f"'{label}' no existe en esta reunion. "
                    f"Etiquetas disponibles: {', '.join(mapping) or '(ninguna)'}"
                )
            mapping[label] = name
        spk.write_map(meeting.speakers_file, mapping, meeting.id)
        written = outputs.write_outputs(meeting, mapping, cfg.output)
        log(f"Nombres guardados en {meeting.speakers_file.name}")
        for path in written:
            log(f"  regenerado: {path.name}")
        log("")

    stats = spk.stats(meeting.segments, mapping)
    if not stats:
        log("Esta reunion no tiene hablantes detectados "
            "(diarizacion desactivada o fallida).")
        return 0

    total = sum(s.seconds for s in stats) or 1.0
    log(meeting.id)
    log("")
    for s in stats:
        pending = "  <- sin nombrar" if s.name == s.label else ""
        log(f"  {s.label} -> {s.name}{pending}")
        log(f"      {outputs.fmt_duration(s.seconds)} ({100 * s.seconds / total:.0f}%) · "
            f"{s.turns} {'intervencion' if s.turns == 1 else 'intervenciones'} · "
            f"{s.words} palabras · "
            f"primera vez en {outputs.fmt_clock(s.first_start)}")
        if s.sample_text:
            sample = s.sample_text[:160] + ("..." if len(s.sample_text) > 160 else "")
            log(f"      muestra [{outputs.fmt_clock(s.sample_start)}]: {sample}")
        log("")

    if args.clips:
        source = meeting.audio_file
        if source is None:
            log("! No hay audio guardado en la carpeta de la reunion "
                "(activa input.keep_audio_in_meeting y vuelve a procesar).")
        else:
            clips_dir = meeting.path / "clips"
            seconds = float(cfg.output.get("sample_clip_seconds", 12))
            log(f"Fragmentos de voz en {clips_dir}:")
            for s in stats:
                dest = clips_dir / f"{s.label}.mp3"
                try:
                    au.extract_clip(source, dest, s.sample_start,
                                    min(seconds, max(2.0, s.sample_duration)))
                    log(f"  {dest.name}")
                except au.AudioError as exc:
                    log(f"  ! {s.label}: {exc}")
            log("")

    log(f"Para poner nombres:  rc speakers {meeting.id} --set {stats[0].label}=Nombre")
    return 0


def cmd_render(args: argparse.Namespace, cfg: Config) -> int:
    targets = (list(store.iter_meetings(cfg.meetings)) if args.all
               else [_resolve_meeting(cfg, args.meeting)])
    if not targets:
        log("No hay reuniones que regenerar.")
        return 0
    for meeting in targets:
        mapping = spk.ensure_map(meeting.speakers_file,
                                 meeting.data.get("speaker_labels") or [], meeting.id)
        written = outputs.write_outputs(meeting, mapping, cfg.output)
        log(f"{meeting.id}: {', '.join(p.name for p in written)}")
    return 0


# -------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rc",
        description="RecordingCraft - transcribe reuniones con WhisperX y separa quien dice que.",
    )
    parser.add_argument("--version", action="version", version=f"RecordingCraft {__version__}")
    parser.add_argument("--config", type=Path, default=None,
                        help="ruta a un config.toml alternativo")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("doctor", help="comprueba el entorno y la configuracion")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("process", help="procesa el inbox (o los ficheros indicados)")
    p.add_argument("paths", nargs="*", help="ficheros o carpetas; vacio = carpeta inbox")
    p.add_argument("--force", action="store_true", help="reprocesa aunque ya estuviera hecho")
    p.add_argument("--title", help="titulo de la reunion (solo con un fichero)")
    p.add_argument("--model", help="modelo Whisper solo para esta ejecucion")
    p.add_argument("--language", help="idioma: es, en, auto...")
    p.add_argument("--device", choices=["cuda", "cpu"], help="dispositivo de computo")
    p.add_argument("--speakers", type=int, help="numero exacto de personas en la reunion")
    p.add_argument("--min-speakers", type=int, help="minimo de personas")
    p.add_argument("--max-speakers", type=int, help="maximo de personas")
    p.add_argument("--vocabulario",
                   help="terminos separados por comas: nombres propios, marcas, modelos")
    p.add_argument("--no-diarization", action="store_true",
                   help="solo transcribir, sin separar hablantes")
    p.add_argument("--debug", action="store_true", help="muestra la traza completa de los errores")
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("list", help="lista las reuniones procesadas")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="muestra la transcripcion en el terminal")
    p.add_argument("meeting", help="id de la reunion (admite coincidencia parcial)")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("speakers", help="ver, renombrar y extraer muestras de los hablantes")
    p.add_argument("meeting")
    p.add_argument("--set", action="append", metavar="ETIQUETA=Nombre",
                   help="asigna un nombre a una etiqueta (se puede repetir)")
    p.add_argument("--clips", action="store_true",
                   help="extrae un fragmento de audio por hablante para identificarlos de oido")
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("render", help="regenera las salidas sin volver a transcribir")
    p.add_argument("meeting", nargs="?")
    p.add_argument("--all", action="store_true", help="todas las reuniones")
    p.set_defaults(func=cmd_render)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    if args.command == "render" and not args.all and not args.meeting:
        parser.error("indica una reunion o usa --all")

    cfg = load_config(args.config)
    try:
        return args.func(args, cfg)
    except KeyboardInterrupt:
        log("")
        log("Interrumpido.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
