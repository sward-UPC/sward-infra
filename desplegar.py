# -*- coding: utf-8 -*-
"""Despliega uno o varios microservicios: mezcla a `deploy`, espera la imagen y
fuerza el despliegue en ECS.

    python desplegar.py                          # dice lo que haria, sin tocar nada
    python desplegar.py --aplicar                # los seis
    python desplegar.py --aplicar xai trazabilidad

Por que existe
--------------
Mezclar `main` en `deploy` dispara el flujo de GitHub, que construye la imagen y
la publica en GHCR. Ese flujo **no actualiza AWS**: su paso de despliegue esta
condicionado a unas credenciales que los repositorios no tienen configuradas, de
modo que sale «saltado» y la corrida queda en verde igual. Por eso hace falta el
`update-service` a mano, y por eso es facil creer que se desplego algo cuando
solo se publico la imagen.

El guion hace los tres pasos en orden y, sobre todo, **espera a que la
construccion termine antes de forzar el despliegue**. Si no se espera, ECS se
baja la imagen `latest` anterior y el despliegue no sirve de nada: parece que
funciono, pero corre el codigo viejo.

Orden
-----
Primero las seis mezclas, que son instantaneas, y despues las seis esperas en
paralelo: las construcciones corren a la vez en GitHub, asi que el total lo
marca la mas lenta (recomendacion, que instala torch, unos ocho minutos) y no la
suma de todas.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
CLUSTER = "sward-cluster"
ORG = "sward-UPC"

# El repositorio se llama sward-ms-<x> y el servicio de ECS, <x>.
SERVICIOS = [
    "cursos-recursos",
    "integracion-lms",
    "usuarios",
    "trazabilidad",
    "recomendacion",
    "xai",
]


def correr(*args, cwd=None, callar=False):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode and not callar:
        print("    FALLO:", " ".join(args))
        print("   ", (r.stderr or r.stdout).strip()[-400:])
        sys.exit(1)
    return r.stdout.strip()


def git(repo: Path, *args, callar=False):
    return correr("git", "-C", str(repo), *args, callar=callar)


def aws(*args):
    return correr("aws", *args, "--region", REGION)


def ultima_corrida(repo_nombre: str) -> dict | None:
    """La corrida mas reciente del flujo en la rama `deploy`, por la API publica."""
    url = (
        f"https://api.github.com/repos/{ORG}/{repo_nombre}/actions/runs"
        "?branch=deploy&per_page=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
    except Exception as e:
        print("    no pude consultar GitHub:", type(e).__name__)
        return None
    corridas = d.get("workflow_runs") or []
    return corridas[0] if corridas else None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "servicios",
        nargs="*",
        default=None,
        help="nombres de servicio; si no se dan, los seis",
    )
    p.add_argument(
        "--aplicar", action="store_true", help="sin esto solo se dice lo que se haria"
    )
    args = p.parse_args()

    elegidos = args.servicios or SERVICIOS
    desconocidos = [s for s in elegidos if s not in SERVICIOS]
    if desconocidos:
        sys.exit(
            "no conozco: %s\nconocidos: %s"
            % (", ".join(desconocidos), ", ".join(SERVICIOS))
        )

    print("servicios:", ", ".join(elegidos))
    print("modo:", "APLICAR" if args.aplicar else "solo listar")
    print()

    # ── 1. Comprobaciones y mezcla a deploy ─────────────────────────────────
    pendientes = {}
    for s in elegidos:
        repo = RAIZ / ("sward-ms-" + s)
        if not repo.is_dir():
            sys.exit("no existe %s" % repo)
        sucio = git(repo, "status", "--porcelain")
        if sucio:
            sys.exit("%s tiene cambios sin confirmar; confirma o guarda antes" % s)
        git(repo, "fetch", "origin", "--quiet", callar=True)
        falta = git(repo, "log", "--oneline", "origin/deploy..main")
        pendientes[s] = falta
        print(
            "%-18s %s"
            % (s, falta.replace("\n", " | ") if falta else "nada que desplegar")
        )

    hay = [s for s in elegidos if pendientes[s]]
    if not hay:
        print("\nNo hay nada pendiente de desplegar.")
        return
    if not args.aplicar:
        print(
            "\nVuelve a correrlo con --aplicar para desplegar %d servicio(s)."
            % len(hay)
        )
        return

    print("\n--- mezclando a deploy ---")
    marca = time.time()
    for s in hay:
        repo = RAIZ / ("sward-ms-" + s)
        git(repo, "checkout", "--quiet", "deploy")
        git(repo, "merge", "--no-edit", "--quiet", "main")
        git(repo, "push", "--quiet", "origin", "deploy")
        git(repo, "checkout", "--quiet", "main")
        print("   %-18s empujado" % s)

    # ── 2. Esperar a que cada imagen quede construida ───────────────────────
    print("\n--- esperando las construcciones (corren en paralelo) ---")
    listos, fallidos = set(), set()
    for _ in range(60):  # hasta 20 minutos
        for s in hay:
            if s in listos or s in fallidos:
                continue
            c = ultima_corrida("sward-ms-" + s)
            if not c:
                continue
            # Solo cuenta una corrida iniciada despues de la mezcla.
            if c["status"] == "completed" and c["created_at"] > time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(marca - 120)
            ):
                (listos if c["conclusion"] == "success" else fallidos).add(s)
                print("   %-18s %s" % (s, c["conclusion"]))
        if len(listos) + len(fallidos) == len(hay):
            break
        time.sleep(20)

    if fallidos:
        sys.exit(
            "\nLa construccion fallo en: %s. No se despliega nada mas."
            % ", ".join(sorted(fallidos))
        )
    faltan = [s for s in hay if s not in listos]
    if faltan:
        sys.exit(
            "\nSe acabo la espera con %s aun construyendo. Revisa GitHub y "
            "corre el update-service a mano." % ", ".join(faltan)
        )

    # ── 3. Forzar el despliegue en ECS ──────────────────────────────────────
    print("\n--- forzando el despliegue en ECS ---")
    for s in hay:
        aws(
            "ecs",
            "update-service",
            "--cluster",
            CLUSTER,
            "--service",
            s,
            "--force-new-deployment",
            "--query",
            "service.serviceName",
            "--output",
            "text",
        )
        print("   %-18s despliegue lanzado" % s)

    # ── 4. Esperar a que todos queden estables ──────────────────────────────
    print("\n--- esperando a que las tareas levanten ---")
    estables = set()
    for _ in range(40):  # hasta 20 minutos
        for s in hay:
            if s in estables:
                continue
            est = aws(
                "ecs",
                "describe-services",
                "--cluster",
                CLUSTER,
                "--services",
                s,
                "--query",
                "services[0].[length(deployments),deployments[0].rolloutState]",
                "--output",
                "text",
            ).split()
            if len(est) == 2 and est[0] == "1" and est[1] == "COMPLETED":
                estables.add(s)
                print("   %-18s estable" % s)
        if len(estables) == len(hay):
            break
        time.sleep(30)

    quedan = [s for s in hay if s not in estables]
    if quedan:
        print("\nSiguen desplegando: %s. Revisa en un rato." % ", ".join(quedan))
    else:
        print("\nListo: %d servicio(s) corriendo la imagen nueva." % len(hay))


if __name__ == "__main__":
    main()
