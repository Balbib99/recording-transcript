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

Lo normal es doble clic en **`INICIAR-WORKER.cmd`** (en la raíz del proyecto): abre su
consola y se queda procesando lo que llegue. `Ctrl+C` para pararlo.

Desde la terminal, con los atajos:

```powershell
.\worker.cmd                 # bucle: espera trabajo y lo procesa
.\worker.cmd --once          # un trabajo y termina
.\worker.cmd --estado        # qué hay en la cola
```

Y el cliente, para manejar la cola sin tocar el móvil:

```powershell
.\cliente.cmd lista
.\cliente.cmd subir "D:\grabaciones\reunion.m4a" --titulo "Reunion"
.\cliente.cmd ver <id>
.\cliente.cmd guardar <id>
.\cliente.cmd hablante <id> SPEAKER_00 Ana Ruiz
.\cliente.cmd reencolar <id>
.\cliente.cmd borrar <id>
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

## Detalles de funcionamiento

**Solo puede haber un worker.** Al arrancar reserva un puerto local como candado; si ya
hay otro, el segundo se cierra en lugar de competir por la GPU. El candado se libera al
morir el proceso, pase lo que pase.

**Comprueba su entorno antes de nada.** Si lo lanzas con un Python sin las
dependencias, lo dice y no arranca. Antes de esto, un worker mal lanzado podía reclamar
un trabajo y marcarlo como fallido al no poder importar WhisperX.

**Impide que el PC se duerma mientras transcribe.** Una reunión larga son veinte
minutos sin tocar el teclado, justo lo que tarda Windows en suspenderse; si pasaba a
mitad, el trabajo se quedaba colgado tres horas. Fuera de la transcripción el equipo
duerme con normalidad.

**Sobrevive a una suspensión.** Al despertar, el túnel SSH está muerto: lo detecta en
la siguiente consulta, lo reabre y sigue. Comprobado.

**Deja traza en `worker/worker.log`** si `RC_LOG_FILE` está definido, que es lo que
permite saber qué pasó cuando corre sin consola a la vista.

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
