# Worker de transcripción

Corre en el PC con GPU. Pide trabajo a la API de la Pi, transcribe con WhisperX y
devuelve el resultado. Es el mismo pipeline que usa el CLI: comparte `config.toml`,
así que el modelo, el idioma y la diarización se configuran en un único sitio.

## Cómo llega a la Pi

La API solo escucha en el loopback de la Pi, así que **el worker abre un túnel SSH él
mismo** con la clave de `rcraft` y lo reabre si se cae. Para ti es un solo proceso.

```
PC                                  Pi
worker ──► 127.0.0.1:8000 ══SSH══► 127.0.0.1:8000 ──► API
```

Ventajas sobre publicar la API en la red: no hay ningún puerto nuevo abierto, el token
nunca viaja en claro por la LAN y reutiliza una clave que ya existe y que da acceso a
un usuario sin privilegios.

## Configuración

```bash
cp worker/.env.example worker/.env
```

El token es el mismo que generó la Pi. Cópialo sin que pase por ningún sitio raro:

```powershell
ssh pi-rcraft "grep RC_API_TOKEN /srv/recordingcraft/app/server/.env"
```

## Uso

```powershell
.venv\Scripts\python.exe worker\worker.py            # bucle: espera trabajo y lo procesa
.venv\Scripts\python.exe worker\worker.py --once     # un trabajo y termina
.venv\Scripts\python.exe worker\worker.py --estado   # qué hay en la cola
```

Con `--sin-tunel` no abre el túnel, para cuando la API ya es accesible (por ejemplo,
durante pruebas en local).

## Qué devuelve

Un JSON que la Pi guarda en `data/resultados/<id>.json` y que ya trae todo masticado
para el cliente:

| Campo | |
|---|---|
| `turnos` | Intervenciones agrupadas por hablante, con tiempos |
| `hablantes` | Tiempo de voz, intervenciones y palabras de cada uno |
| `segmentos` | Datos crudos, con timestamps por palabra si hubo alineación |
| `markdown` | Transcripción lista para leer |
| `texto` | Versión en texto plano |

El móvil no tendrá que renderizar nada: recibe el texto ya hecho.

## Si algo falla

El worker marca el trabajo como `fallido` con el motivo, y sigue con el siguiente en
lugar de pararse. Para reintentarlo:

```powershell
.venv\Scripts\python.exe worker\worker.py --estado    # localiza el id
```

Y desde la Pi, o con cualquier cliente HTTP:

```bash
curl -X POST localhost:8000/api/jobs/<id>/reencolar -H "Authorization: Bearer $RC_API_TOKEN"
```

Un trabajo que un worker reclama y nunca termina (porque el PC se apagó a media
transcripción) vuelve solo a la cola pasadas tres horas, configurable con
`RC_CLAIM_TIMEOUT` en el servidor.

## Dejarlo siempre en marcha

Para que arranque con Windows, lo más simple es el Programador de tareas: acción
`.venv\Scripts\pythonw.exe` con argumento `worker\worker.py`, disparador "al iniciar
sesión", y marcar que se reinicie si falla. No hace falta servicio ni permisos de
administrador.
