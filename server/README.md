# API de RecordingCraft

Servicio que recibe grabaciones, las guarda y mantiene la cola de trabajos. Pensado
para correr en la Raspberry Pi; la transcripción la hace un worker aparte en un equipo
con GPU, que pide trabajo a esta API.

No transcribe nada por sí mismo: aquí no hay ni PyTorch ni modelos.

## Diseño

- **FastAPI + SQLite**, sin ORM. El modelo son unos pocos campos y una tabla, y así el
  servidor no arrastra dependencias que compilar en ARM.
- **Escucha solo en `127.0.0.1`**. No se expone a la red: quien publica es Caddy, y
  solo hacia la LAN y la VPN. Es la única forma fiable de cerrar un puerto en una
  máquina con Docker, porque Docker escribe sus reglas por delante de las de ufw.
- **Autenticación por token compartido** (`Authorization: Bearer ...`), comparado en
  tiempo constante.
- **Subidas por trozos**: el fichero nunca se carga entero en memoria, que en la Pi
  sería un problema con reuniones largas.
- **Deduplicación por SHA-256**: subir dos veces el mismo audio devuelve el trabajo
  que ya existía en lugar de duplicarlo.
- **Reparto de cola a prueba de carreras**: el trabajo se entrega con un `UPDATE ...
  WHERE estado = 'pendiente'`, así que si dos workers preguntan a la vez, solo uno se
  lo lleva. Lo reclamado y nunca terminado vuelve a la cola pasado `RC_CLAIM_TIMEOUT`.

## Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/health` | Vivo o no. Sin token |
| GET | `/api/estado` | Recuento por estado y uso de disco |
| POST | `/api/jobs` | Subir una grabación (multipart: `file`, `titulo` opcional) |
| GET | `/api/jobs` | Listar (`estado`, `limite`, `desplazamiento`) |
| GET | `/api/jobs/{id}` | Detalle |
| GET | `/api/jobs/{id}/audio` | Descargar el audio (lo usa el worker) |
| GET | `/api/jobs/{id}/transcripcion` | Resultado, cuando exista |
| POST | `/api/jobs/{id}/ajustes` | Cambiar `titulo`, `vocabulario` o `esperados`. El título se puede cambiar siempre (si ya hay transcripción, también se rehace su JSON y su Markdown); vocabulario y personas solo cuentan antes de transcribir |
| DELETE | `/api/jobs/{id}` | Borrar trabajo, audio y transcripción, en cualquier estado (también uno atascado en `procesando`) |

Documentación interactiva en `/api/docs`.

Estados: `pendiente` → `procesando` → `hecho` | `fallido`.

## Despliegue en la Pi

Como usuario `rcraft`:

```bash
git clone https://github.com/Balbib99/recording-transcript.git /srv/recordingcraft/app
cd /srv/recordingcraft/app/server
cp .env.example .env
```

Genera el token y escríbelo en el `.env` (`RC_API_TOKEN`), y pon
`RC_DATA_HOST=/srv/recordingcraft/data`:

```bash
openssl rand -hex 32
```

Levanta el servicio (esto lo hace el usuario administrador, porque `rcraft` no está
—ni debe estar— en el grupo `docker`):

```bash
docker compose -f /srv/recordingcraft/app/server/docker-compose.yml up -d --build
```

Comprueba:

```bash
curl -s localhost:8000/api/health
```

## Despertar el PC desde el móvil

La app muestra si el PC que transcribe está disponible y, si no lo está, un botón para
encenderlo. Lo dispara siempre el usuario: no hay nada que encienda el PC solo.

| | |
|---|---|
| `POST /api/despertar` | Deja la petición en `data/despertar.peticion` |
| Servicio `despertador` | La recoge cada 2 s y manda el paquete mágico |
| `GET /api/estado` | Devuelve `worker: {vivo, visto, segundos}` |

**Por qué hay un servicio aparte.** Un contenedor en red puente no puede mandar una
difusión a la red de casa: Linux no reenvía difusiones dirigidas entre interfaces.
Comprobado — la API enviaba cuatro paquetes sin un solo error y no llegaba ninguno. El
`despertador` es el mismo contenedor con `network_mode: host` y otro comando, y sí ve
la red real. No escucha en ningún puerto; se comunica con la API por un fichero.

**Cómo se sabe que el PC despertó.** El worker deja un latido cada vez que pregunta por
trabajo, así que la Pi sabe de verdad si está vivo. Tras pulsar, la app consulta cada
cinco segundos durante dos minutos hasta verlo volver. No es un "enviado" a ciegas.

Requiere `RC_WOL_MAC` en el `.env`, y que la tarjeta de red tenga activado el despertar
por paquete mágico.

## Desplegar cambios

El código y la web están montados como volúmenes, así que casi nunca hace falta
reconstruir:

| Qué cambió | Qué hacer |
|---|---|
| La web (`web/`) | `git pull` y recargar el navegador |
| El código (`app/`) | `git pull` + `docker compose restart api` |
| El `.env` o el compose | `docker compose up -d` |
| `requirements.txt` | `docker compose up -d --build` |

Ojo con `up -d`: solo recrea los contenedores cuya configuración cambió. Si tocas el
código y haces `up -d`, Python sigue con el módulo que cargó al arrancar — hace falta
`restart`.

## Datos en disco

```
/srv/recordingcraft/data/
├── recordingcraft.db      cola de trabajos (SQLite, en modo WAL)
├── audio/<id>.<ext>       grabaciones subidas
└── resultados/<id>.json   transcripciones que devuelve el worker
```

Vive **fuera** del clon de git a propósito: así ningún `git clean` o redespliegue se
lleva por delante las grabaciones.

## Pruebas

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
.venv/bin/python tests/test_api.py
```

Recorre el flujo entero (autenticación, subida, validaciones, duplicados, descarga,
reparto de cola y borrado) contra una carpeta temporal. No toca datos reales ni
necesita servidor levantado.

## Variables de entorno

| Variable | Por defecto | |
|---|---|---|
| `RC_API_TOKEN` | — | Obligatoria; sin ella el servicio no arranca |
| `RC_DATA_HOST` | `./data` | Carpeta de datos en el host |
| `RC_MAX_UPLOAD_MB` | `500` | Límite de subida |
| `RC_CLAIM_TIMEOUT` | `10800` | Segundos antes de dar por abandonado un trabajo |
