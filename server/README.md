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
| DELETE | `/api/jobs/{id}` | Borrar trabajo, audio y transcripción |

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
