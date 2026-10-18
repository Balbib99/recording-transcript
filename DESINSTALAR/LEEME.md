# Desinstalar RecordingCraft

**Doble clic en `DESINSTALAR.cmd`.**

Antes de borrar nada te enseña el inventario completo con tamaños, te ofrece
guardar una copia de tus transcripciones en el escritorio y te pide escribir
`BORRAR` para confirmar. Si escribes otra cosa, no toca nada.

Si solo quieres ver qué se borraría, doble clic en **`SIMULAR.cmd`**.

## Qué borra

| | |
|---|---|
| La carpeta entera del proyecto | `RecordingCraft\` (incluye `.venv`, que es casi todo el peso) |
| Los modelos descargados | `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-*`, `models--pyannote--*`, `models--jonatasgrosman--wav2vec2-*` |
| El modelo de alineación | `%USERPROFILE%\.cache\torch\hub\checkpoints\wav2vec2_*.pt` |

## Qué NO borra

- **ffmpeg** — es independiente y útil por su cuenta: `winget uninstall Gyan.FFmpeg`
- **Tu token de Hugging Face** — revócalo en <https://huggingface.co/settings/tokens>
- **Python** — sigue instalado en el sistema

## Opciones

Desde PowerShell, si quieres afinar:

```powershell
.\desinstalar.ps1 -Simular                   # no borra, solo informa
.\desinstalar.ps1 -ConservarModelos          # borra el proyecto, deja los modelos
.\desinstalar.ps1 -ConservarTranscripciones  # mueve data\meetings al escritorio
.\desinstalar.ps1 -SinPreguntar              # sin confirmación (ojo)
```

## Detalles

- El script comprueba que está dentro de un proyecto RecordingCraft de verdad
  (busca `pyproject.toml` con `name = "recordingcraft"`) y aborta si no.
- La carpeta del proyecto se borra en diferido, desde un proceso aparte, porque
  un script no puede borrar la carpeta en la que se está ejecutando. Reintenta
  durante unos 30 segundos.
- Si al final la carpeta sigue ahí, es que algo la tiene abierta: VS Code, el
  explorador de Windows o una terminal. Ciérralo y bórrala a mano.
- Los modelos sí se borran de inmediato, antes del proyecto.
