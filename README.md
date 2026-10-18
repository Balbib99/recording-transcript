# RecordingCraft

Transcribe grabaciones de reuniones en local (sin enviar nada a internet) y deja
registrado **quién dice qué y cuándo**.

- **WhisperX** para la transcripción y la alineación palabra a palabra.
- **pyannote 3.1** para la diarización: separa las voces en `SPEAKER_00`, `SPEAKER_01`…
- Tú pones los nombres reales una vez y todas las salidas se regeneran sin volver a
  procesar el audio.
- Pensado para los `.m4a` de la Grabadora del Pixel, pero traga cualquier formato que
  entienda ffmpeg.

Cada reunión acaba siendo una carpeta con la transcripción en Markdown, texto plano,
subtítulos y JSON.

---

## 1. Requisitos

| | |
|---|---|
| Python | 3.10 o superior (aquí: 3.12) |
| ffmpeg | en el PATH (`winget install Gyan.FFmpeg`) |
| GPU | opcional pero muy recomendable. Detectada: GTX 1660, 6 GB |
| Cuenta Hugging Face | gratuita, solo para descargar el modelo de diarización |

## 2. Instalación

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

El script crea `.venv`, instala PyTorch con CUDA, WhisperX y el propio paquete, copia
`config.example.toml` a `config.toml` y `.env.example` a `.env`, y termina ejecutando
el diagnóstico. Con `-Cpu` instala la versión sin GPU.

### Token de Hugging Face (necesario para saber quién habla)

La transcripción funciona sin token; la **diarización no**. Una sola vez:

1. Acepta las condiciones de los modelos, con tu cuenta, pulsando *Agree and access
   repository*. El formulario pide empresa y web: es una auto-declaracion que nadie
   verifica y la aprobacion es automatica (vale `Particular` y la URL de tu propio
   perfil de Hugging Face).
   - <https://huggingface.co/pyannote/speaker-diarization-community-1> — **el que usa
     el proyecto**
   - <https://huggingface.co/pyannote/segmentation-3.0> y
     <https://huggingface.co/pyannote/speaker-diarization-3.1> — solo si cambias
     `diarization.model` al pipeline antiguo (que, con pyannote-audio 4.x, sigue
     necesitando ademas el de community-1)
2. Crea el token en <https://huggingface.co/settings/tokens>. Solo necesita **lectura**:
   - **Token de tipo *Read*** (la opción sencilla): no hay nada más que marcar.
   - **Token *Fine-grained***: marca únicamente, en el apartado *Repositories*,
     **"Read access to contents of all public gated repos you can access"**. Si
     prefieres acotarlo, dale acceso de lectura solo a `pyannote/speaker-diarization-3.1`
     y `pyannote/segmentation-3.0`.

   No hace falta nada de escritura (*write*), ni permisos de *Inference*, *Endpoints*,
   *Billing*, *Collections*, *Discussions* ni de organización. El token tiene que ser de
   la misma cuenta con la que aceptaste las condiciones del paso 1.
3. Pega el token en el fichero `.env`:

   ```
   HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx
   ```

Comprueba que todo está en su sitio:

```powershell
.\rc.cmd doctor
```

## 3. Pasar las grabaciones del Pixel al PC

En la app **Grabadora** del Pixel 9 Pro XL, abre la grabación y usa la opción de
compartir o guardar una copia eligiendo el **archivo de audio** (`.m4a`), no la
transcripción. Formas habituales de que llegue al PC:

- **Cable USB**: el móvil en modo *Transferencia de archivos* y copias el `.m4a` desde
  `Almacenamiento interno\Recordings` (o `Download`).
- **Google Drive / Fotos / Telegram "mensajes guardados"**: compartes el audio desde el
  móvil y lo descargas en el PC.

Deja el fichero en `data\inbox\`. Da igual el nombre: la fecha se saca de los metadatos
del audio y, si no los tiene, del nombre del fichero o de la fecha de modificación.

## 4. Uso diario

```powershell
.\rc.cmd process                 # procesa todo lo nuevo que haya en data\inbox
.\rc.cmd list                    # reuniones procesadas
.\rc.cmd speakers <id> --clips   # quién es quién (+ fragmentos de voz en mp3)
.\rc.cmd speakers <id> --set SPEAKER_00=Ana --set "SPEAKER_01=Carlos Ruiz"
.\rc.cmd show <id>               # transcripción en el terminal
```

`<id>` admite coincidencias parciales: si la reunión es
`2026-10-17_1900_grabacion-12`, con `.\rc.cmd show grabacion-12` basta.

### El flujo completo, paso a paso

1. Copias los audios a `data\inbox\`.
2. `.\rc.cmd process` → transcribe, alinea y separa voces. El original se mueve a
   `data\archive\` y queda una copia dentro de la carpeta de la reunión.
3. `.\rc.cmd speakers <id> --clips` → te lista cada `SPEAKER_xx` con su tiempo de voz,
   su primera intervención, una frase de muestra y un `.mp3` de unos segundos en
   `clips\` para reconocer la voz si la frase no te basta.
4. `.\rc.cmd speakers <id> --set SPEAKER_00=Ana …` → los nombres se guardan en
   `speakers.toml` y las cuatro salidas se reescriben al instante (la GPU no vuelve a
   tocarse).

También puedes editar `speakers.toml` a mano y luego `.\rc.cmd render <id>`.

### Opciones útiles de `process`

```powershell
.\rc.cmd process "D:\audios\reunion.m4a" --title "Comite de direccion"
.\rc.cmd process --speakers 4          # sabes que erais exactamente 4: mejora mucho
.\rc.cmd process --min-speakers 2 --max-speakers 6
.\rc.cmd process --model medium        # más rápido, algo menos preciso
.\rc.cmd process --no-diarization      # solo transcribir
.\rc.cmd process --force               # reprocesar algo ya hecho
.\rc.cmd process --debug               # traza completa si algo falla
```

Si conoces el número de personas, pásalo: es lo que más mejora la separación de voces.

## 5. Qué queda en disco

```
data/
├── inbox/                      # tú dejas aquí los audios
├── archive/                    # originales ya procesados
└── meetings/
    └── 2026-10-17_1900_grabacion-12/
        ├── meeting.json        # datos crudos: segmentos, palabras, tiempos, etiquetas
        ├── speakers.toml       # SPEAKER_xx -> nombre real (editable)
        ├── transcript.md       # metadatos + tabla de hablantes + conversación
        ├── transcript.txt      # [00:12:30] Ana: ...
        ├── transcript.srt      # subtítulos con nombre
        ├── transcript.json     # intervenciones ya con nombres, para scripts
        ├── audio.m4a           # copia del original
        └── clips/              # muestras de voz por hablante (con --clips)
```

`meeting.json` es la fuente de la verdad y nunca se pierde: guarda los timestamps por
palabra y la etiqueta de hablante de cada una. El resto de ficheros se puede regenerar
siempre con `rc render`.

## 6. Configuración (`config.toml`)

Lo que más vas a tocar:

| Opción | Por defecto | Para qué |
|---|---|---|
| `whisper.model` | `large-v3` | `medium` o `distil-large-v3` si quieres ir más rápido |
| `whisper.language` | `es` | `auto` si hay reuniones en varios idiomas |
| `whisper.compute_type` | `int8_float16` | Elegido para los 6 GB de la 1660. Si ves texto raro, prueba `int8`; en CPU se fuerza `int8` |
| `whisper.batch_size` | `4` | Bájalo a `2` si te quedas sin VRAM, súbelo si te sobra |
| `diarization.min/max_speakers` | `0` | Acota el número de personas habituales |
| `output.merge_gap_seconds` | `1.5` | Cuánto silencio admite antes de partir una intervención |
| `input.on_success` | `archive` | `keep` si prefieres que el original no se mueva del inbox |

Las rutas de `[paths]` pueden ser absolutas: por ejemplo, apuntar `inbox` directamente a
la carpeta donde Drive sincroniza las grabaciones.

## 7. Problemas frecuentes

**`CUDA out of memory`** — baja `batch_size` a 2, o `model` a `medium`. El pipeline ya
libera la VRAM entre etapas (transcripción → alineación → diarización).

**`rc doctor` dice "CUDA disponible: FALLA" y el PyTorch acaba en `+cpu`** — algo ha
reinstalado PyTorch desde PyPI (en Windows esa rueda no trae CUDA). Pasa si instalas o
actualizas WhisperX por tu cuenta. Se arregla volviendo a poner las mismas versiones
desde el índice CUDA:

```powershell
.venv\Scripts\python.exe -m pip install --force-reinstall --no-cache-dir `
    torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 `
    --index-url https://download.pytorch.org/whl/cu126
```

(sustituye las versiones por las que tengas; `scripts\install.ps1` ya lo hace solo y en
el orden correcto)

**La diarización no se ejecuta** — `rc doctor` te dirá si falta el `HF_TOKEN` o si no has
aceptado las condiciones de los modelos de pyannote. Sin eso la transcripción sale
igualmente, pero sin hablantes.

**Dice que ya está procesado** — se reconoce por el hash del audio, no por el nombre.
Usa `--force` para repetirlo.

**Hay más hablantes de los que hubo** — pasa con audio malo o con gente que interrumpe
mucho. Usa `--speakers N`. Si aun así parte a una persona en dos etiquetas, dale el mismo
nombre a las dos en `speakers.toml`: en las salidas aparecerán como una sola.

**La primera ejecución tarda muchísimo** — está descargando los modelos (varios GB) a
`%USERPROFILE%\.cache\huggingface`. Solo ocurre una vez.

## 8. Privacidad: que sale de tu equipo

El audio y las transcripciones **nunca salen del PC**. No hay ninguna API de terceros
en el flujo: Whisper y pyannote se ejecutan en tu GPU y escriben en tu disco.

Lo que si hace trafico de red, y como se corta:

| Que | Cuando | Contenido |
|---|---|---|
| Descarga de modelos (huggingface.co) | La primera vez que usas cada modelo | Solo bajada |
| Comprobacion de version del modelo | Al cargar el pipeline en cada ejecucion | Metadatos del repo |
| `rc doctor` | Solo al ejecutarlo | Valida el token contra la API de HF |
| **Telemetria de pyannote** | Al cargar modelos y al diarizar | Ver abajo |

### Telemetria de pyannote

`pyannote.audio 4.x` envia por defecto trazas OpenTelemetry a
`https://otel.pyannote.ai/v1/traces` cada vez que inicializa un modelo o procesa un
fichero. Manda: version de pyannote, un identificador de sesion aleatorio, el nombre
del pipeline, la **duracion del audio** y el numero de hablantes. No manda el audio,
ni el texto, ni el nombre del fichero. Los fallos de envio se silencian
(`telemetry_log_level: CRITICAL`), asi que no te enterarias de que ocurre.

**RecordingCraft lo desactiva por defecto** (`privacy.telemetry = false`), poniendo
`PYANNOTE_METRICS_ENABLED=false` antes de importar nada de pyannote. `rc doctor` te
confirma el estado en su apartado *Privacidad*.

### Modo sin red

Una vez descargados los modelos, el proyecto funciona sin internet. En `config.toml`:

```toml
[privacy]
telemetry = false
offline = true
```

Con `offline = true` se fija `HF_HUB_OFFLINE=1` y `TRANSFORMERS_OFFLINE=1`: no se
contacta con ningun servidor, ni siquiera para comprobar versiones. Si falta un modelo
en la cache, el proceso falla en vez de descargarlo, que es justo lo que quieres de un
modo offline. Comprobado: con `offline = true` cargan tanto `large-v3` como
`speaker-diarization-community-1` desde la cache local.

Si quieres la garantia a nivel de sistema y no de configuracion, bloquea `python.exe`
del `.venv` en el Firewall de Windows (Reglas de salida -> Nueva regla -> Programa ->
Bloquear). El proyecto seguira funcionando con los modelos ya descargados.

## 9. Desinstalar

Doble clic en `DESINSTALAR\DESINSTALAR.cmd`. Enseña el inventario con tamaños, ofrece
copiar tus transcripciones al escritorio y pide escribir `BORRAR` para confirmar. Borra
el proyecto entero y los modelos descargados (~10 GB en total); no toca ffmpeg, Python
ni tu token. `DESINSTALAR\SIMULAR.cmd` hace lo mismo sin borrar nada. Más detalles en
[DESINSTALAR/LEEME.md](DESINSTALAR/LEEME.md).

## 10. Rendimiento orientativo

Con la GTX 1660 (6 GB) y `large-v3` + `int8_float16`, cuenta con algo así como entre un
cuarto y la mitad del tiempo real: una reunión de una hora, del orden de 15–30 minutos
de proceso, más la diarización. Con `medium` baja bastante. En CPU es varias veces el
tiempo real: úsalo solo para pruebas.
