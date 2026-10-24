"""Cliente de linea de comandos para la API de la Pi.

Sirve para subir grabaciones y leer transcripciones desde el PC mientras no
existe la app del movil. Abre el tunel SSH el mismo, igual que el worker.

    python worker/cliente.py subir "D:\\audios\\reunion.m4a" --titulo "Comite"
    python worker/cliente.py lista
    python worker/cliente.py ver <id>
    python worker/cliente.py guardar <id>
    python worker/cliente.py reencolar <id>
    python worker/cliente.py borrar <id>
    python worker/cliente.py perfiles
    python worker/cliente.py perfil Empresa --vocabulario "Alfa, Beta"
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


def buscar_perfil(nombre: str) -> dict | None:
    """Encuentra un perfil por su nombre (sin importar mayusculas) o por su id."""
    r = api("GET", "/api/perfiles")
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return None
    buscado = nombre.strip().lower()
    for perfil in r.json()["perfiles"]:
        if perfil["id"] == nombre or perfil["nombre"].lower() == buscado:
            return perfil
    return None


def perfil_o_error(nombre: str) -> dict | None:
    perfil = buscar_perfil(nombre)
    if perfil is None:
        log(f"No hay ningun perfil llamado '{nombre}'. Mira cuales hay con: perfiles")
    return perfil


def cmd_subir(args) -> int:
    ruta = Path(args.fichero).expanduser()
    if not ruta.is_file():
        log(f"No existe: {ruta}")
        return 1
    datos = {}
    if args.perfil:
        perfil = perfil_o_error(args.perfil)
        if perfil is None:
            return 1
        datos["perfil"] = perfil["id"]
    if args.contexto:
        datos["contexto"] = args.contexto
    if args.titulo:
        datos["titulo"] = args.titulo
    if args.vocabulario:
        datos["vocabulario"] = args.vocabulario
    if args.hablantes:
        datos["esperados"] = str(args.hablantes)
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


def cmd_ajustes(args) -> int:
    """Cambia el vocabulario o el numero de hablantes de un trabajo pendiente."""
    datos = {}
    if args.vocabulario is not None:
        datos["vocabulario"] = args.vocabulario
    if args.hablantes is not None:
        datos["esperados"] = args.hablantes
    if args.titulo is not None:
        datos["titulo"] = args.titulo
    if args.contexto is not None:
        datos["contexto"] = args.contexto
    if args.perfil is not None:
        if args.perfil.strip().lower() in ("", "ninguno", "-"):
            datos["perfil"] = ""
        else:
            perfil = perfil_o_error(args.perfil)
            if perfil is None:
                return 1
            datos["perfil"] = perfil["id"]
    if not datos:
        log("Indica --vocabulario, --hablantes, --titulo, --contexto o --perfil")
        return 1

    r = api("POST", f"/api/jobs/{args.id}/ajustes", json=datos)
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return 1
    job = r.json()
    log(f"{job['id']}  hablantes esperados: {job['esperados'] or '-'}")
    log(f"            vocabulario: {job['vocabulario'] or '-'}")
    log(f"            contexto: {job.get('contexto') or '-'}")
    if job.get("aviso"):
        log(f"  ! {job['aviso']}")
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


def cmd_perfiles(args) -> int:
    r = api("GET", "/api/perfiles")
    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return 1
    perfiles = r.json()["perfiles"]
    if not perfiles:
        log("No hay perfiles. Crea uno con: perfil <nombre> --nuevo")
        return 0
    for perfil in perfiles:
        n = perfil.get("grabaciones") or 0
        log(f"{perfil['nombre']}  ({n} grabacion{'' if n == 1 else 'es'})")
        log(f"    vocabulario:   {perfil['vocabulario'] or '-'}")
        log(f"    participantes: {', '.join(perfil['participantes']) or '-'}")
    return 0


def cmd_perfil(args) -> int:
    """Crea un perfil o cambia su vocabulario y sus participantes."""
    datos = {}
    vocabulario = args.vocabulario
    if args.desde_config:
        # Para mudar de una vez el vocabulario general del config.toml a un
        # perfil, sin tener que copiarlo a mano.
        from recordingcraft.config import load_config
        vocabulario = str(load_config().whisper.get("vocabulario") or "")
    if vocabulario is not None:
        datos["vocabulario"] = vocabulario
    if args.participantes is not None:
        datos["participantes"] = args.participantes
    if args.renombrar:
        datos["nombre"] = args.renombrar

    actual = buscar_perfil(args.nombre)
    if actual is None:
        if not args.nuevo:
            log(f"No hay ningun perfil llamado '{args.nombre}'. Para crearlo, anade --nuevo")
            return 1
        r = api("POST", "/api/perfiles", json={**datos, "nombre": args.nombre})
    else:
        if not datos:
            log("Indica --vocabulario, --participantes, --desde-config o --renombrar")
            return 1
        r = api("PUT", f"/api/perfiles/{actual['id']}", json=datos)

    if not r.ok:
        log(f"Error {r.status_code}: {r.text[:200]}")
        return 1
    perfil = r.json()
    terminos = [x for x in perfil["vocabulario"].split(",") if x.strip()]
    log(f"{perfil['nombre']}: {len(terminos)} termino(s), "
        f"{len(perfil['participantes'])} participante(s)")
    return 0


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
    p.add_argument("--vocabulario", help="terminos separados por comas")
    p.add_argument("--hablantes", type=int, help="cuantas personas hablan")
    p.add_argument("--perfil", help="nombre del perfil (Empresa, Casa...)")
    p.add_argument("--contexto", help="de que va la reunion, en una frase")
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

    p = sub.add_parser("ajustes", help="vocabulario y hablantes de un trabajo pendiente")
    p.add_argument("id")
    p.add_argument("--vocabulario")
    p.add_argument("--hablantes", type=int)
    p.add_argument("--titulo")
    p.add_argument("--contexto", help="de que va la reunion, en una frase")
    p.add_argument("--perfil", help="nombre del perfil, o 'ninguno' para quitarlo")
    p.set_defaults(func=cmd_ajustes)

    p = sub.add_parser("hablante", help="pone nombre a un hablante")
    p.add_argument("id")
    p.add_argument("etiqueta", help="SPEAKER_00, SPEAKER_01...")
    p.add_argument("nombre", nargs="+")
    p.set_defaults(func=cmd_hablante)

    p = sub.add_parser("reencolar", help="reintenta un trabajo fallido")
    p.add_argument("id")
    p.set_defaults(func=cmd_reencolar)

    p = sub.add_parser("perfiles", help="lista los perfiles de trabajo")
    p.set_defaults(func=cmd_perfiles)

    p = sub.add_parser("perfil", help="crea un perfil o cambia su vocabulario y participantes")
    p.add_argument("nombre")
    p.add_argument("--nuevo", action="store_true", help="crearlo si no existe")
    p.add_argument("--vocabulario", help="terminos separados por comas")
    p.add_argument("--desde-config", action="store_true",
                   help="usa el vocabulario general de config.toml")
    p.add_argument("--participantes", help="nombres separados por comas")
    p.add_argument("--renombrar", help="nuevo nombre del perfil")
    p.set_defaults(func=cmd_perfil)

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
