"""Cliente de linea de comandos para la API de la Pi.

Sirve para subir grabaciones y leer transcripciones desde el PC mientras no
existe la app del movil. Abre el tunel SSH el mismo, igual que el worker.

    python worker/cliente.py subir "D:\\audios\\reunion.m4a" --titulo "Comite"
    python worker/cliente.py lista
    python worker/cliente.py ver <id>
    python worker/cliente.py guardar <id>
    python worker/cliente.py reencolar <id>
    python worker/cliente.py borrar <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comun import API_TOKEN, RAIZ, Tunel, api, esperar_api, log  # noqa: E402


def segundos(valor) -> str:
    if not valor:
        return "-"
    total = int(valor)
    return f"{total // 60}:{total % 60:02d}"


def cmd_subir(args) -> int:
    ruta = Path(args.fichero).expanduser()
    if not ruta.is_file():
        log(f"No existe: {ruta}")
        return 1
    datos = {"titulo": args.titulo} if args.titulo else {}
    with open(ruta, "rb") as fichero:
        r = api("POST", "/api/jobs", files={"file": (ruta.name, fichero)},
                data=datos, timeout=900)
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:300]}")
        return 1
    job = r.json()
    if job.get("duplicado"):
        log(f"Ese audio ya estaba subido: {job['id']} ({job['estado']})")
    else:
        log(f"Subido: {job['id']}  {job['titulo']}  ({job['bytes'] / 1e6:.1f} MB)")
        log("El worker lo cogera en cuanto este en marcha.")
    return 0


def cmd_lista(args) -> int:
    estado = api("GET", "/api/estado").json()
    cola = estado["trabajos"]
    log(f"pendientes: {cola['pendiente']}  procesando: {cola['procesando']}  "
        f"hechos: {cola['hecho']}  fallidos: {cola['fallido']}  "
        f"({estado['bytes_en_disco'] / 1e6:.0f} MB en disco)")
    trabajos = api("GET", "/api/jobs", params={"limite": args.limite}).json()["trabajos"]
    if not trabajos:
        log("(la cola esta vacia)")
        return 0
    log("")
    for t in trabajos:
        marca = {"pendiente": "...", "procesando": ">>>", "hecho": " ok",
                 "fallido": "  !"}.get(t["estado"], "   ")
        log(f"{marca} {t['id']}  {t['estado']:<11} {segundos(t['duracion']):>6}  "
            f"{t['titulo']}")
        if t["error"]:
            log(f"      {t['error'][:160]}")
    return 0


def cmd_ver(args) -> int:
    r = api("GET", f"/api/jobs/{args.id}/transcripcion")
    if r.status_code == 409:
        detalle = api("GET", f"/api/jobs/{args.id}").json()
        log(f"Todavia no hay transcripcion (estado: {detalle['estado']})")
        return 1
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return 1
    print(r.json()["markdown"])
    return 0


def cmd_guardar(args) -> int:
    r = api("GET", f"/api/jobs/{args.id}/transcripcion")
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return 1
    datos = r.json()
    carpeta = Path(args.carpeta or (RAIZ / "data" / "meetings"))
    nombre = f"{datos.get('titulo') or datos['id']}".replace("/", "-")[:60]
    destino = carpeta / f"{datos['id']}_{nombre}"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "transcript.md").write_text(datos["markdown"], encoding="utf-8")
    (destino / "transcript.txt").write_text(datos["texto"], encoding="utf-8")
    (destino / "transcripcion.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Guardado en {destino}")
    return 0


def cmd_hablante(args) -> int:
    """Pone nombre a una etiqueta: cliente.cmd hablante <id> SPEAKER_00 Ana"""
    r = api("POST", f"/api/jobs/{args.id}/hablantes",
            json={args.etiqueta: " ".join(args.nombre)})
    if not r.ok:
        detalle = r.json().get("detail", r.text[:200]) if r.text else r.status_code
        log(f"Error: {detalle}")
        return 1
    for h in r.json()["hablantes"]:
        log(f"  {h['etiqueta']:<12} -> {h['nombre']}")
    return 0


def cmd_reencolar(args) -> int:
    r = api("POST", f"/api/jobs/{args.id}/reencolar")
    log(f"{args.id}: {r.json()['estado']}" if r.ok else f"Error {r.status_code}")
    return 0 if r.ok else 1


def cmd_borrar(args) -> int:
    r = api("DELETE", f"/api/jobs/{args.id}")
    log(f"borrado {args.id}" if r.ok else f"Error {r.status_code}: {r.text[:200]}")
    return 0 if r.ok else 1


def main() -> int:
    # Las transcripciones llevan acentos: sin esto, redirigir la salida a un
    # fichero en Windows los rompe.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(description="Cliente de la API de RecordingCraft")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("subir", help="sube una grabacion a la cola")
    p.add_argument("fichero")
    p.add_argument("--titulo")
    p.set_defaults(func=cmd_subir)

    p = sub.add_parser("lista", help="estado de la cola")
    p.add_argument("--limite", type=int, default=20)
    p.set_defaults(func=cmd_lista)

    p = sub.add_parser("ver", help="imprime la transcripcion")
    p.add_argument("id")
    p.set_defaults(func=cmd_ver)

    p = sub.add_parser("guardar", help="guarda la transcripcion en el PC")
    p.add_argument("id")
    p.add_argument("carpeta", nargs="?")
    p.set_defaults(func=cmd_guardar)

    p = sub.add_parser("hablante", help="pone nombre a un hablante")
    p.add_argument("id")
    p.add_argument("etiqueta", help="SPEAKER_00, SPEAKER_01...")
    p.add_argument("nombre", nargs="+")
    p.set_defaults(func=cmd_hablante)

    p = sub.add_parser("reencolar", help="reintenta un trabajo fallido")
    p.add_argument("id")
    p.set_defaults(func=cmd_reencolar)

    p = sub.add_parser("borrar", help="borra trabajo, audio y transcripcion")
    p.add_argument("id")
    p.set_defaults(func=cmd_borrar)

    args = parser.parse_args()

    if not API_TOKEN:
        log("Falta RC_API_TOKEN en worker/.env")
        return 1

    tunel = Tunel()
    try:
        tunel.abrir()
        if not esperar_api():
            log("La API no responde. Comprueba que el contenedor esta arriba en la Pi.")
            return 1
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    finally:
        tunel.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
