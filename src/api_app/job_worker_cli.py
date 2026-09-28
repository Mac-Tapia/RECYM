# -*- coding: utf-8 -*-
"""CLI worker: ejecuta un job CymPy en proceso hijo y escribe JSON de resultado.

Uso (interno):
  python -u src/api_app/job_worker_cli.py --action calidad_diagnosticar \\
      --feeder PA217 --payload payload.json --out result.json
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = os.path.join(ROOT, "src")
for p in (_SRC, os.path.join(_SRC, "core"), os.path.join(_SRC, "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

# Marca: el hijo corre in-process; evita re-aislar.
os.environ["RECYM_JOB_WORKER"] = "1"
os.environ.setdefault("RECYM_SPA", "1")


def write_result_and_exit(out_path, result, exit_code):
    """Persiste el resultado y termina sin ejecutar destructores nativos.

    CymPy/COM puede fallar durante el teardown del interprete. El fsync garantiza
    que el padre pueda leer el JSON antes de os._exit; aun si CYME falla al
    descargar su DLL, el padre conserva el resultado y el código nativo.
    """
    raw = json.dumps(
        result, ensure_ascii=False, indent=2, default=str
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(out_path, flags, 0o600)
    offset = 0
    while offset < len(raw):
        offset += os.write(fd, raw[offset:])
    os.fsync(fd)
    # No cerrar fd ni retornar: Windows libera el handle al terminar el proceso.
    os._exit(int(exit_code))


def main(argv=None):
    ap = argparse.ArgumentParser(description="RECYM job worker aislado")
    ap.add_argument("--action", required=True)
    ap.add_argument("--feeder", default="")
    ap.add_argument("--payload", default="", help="JSON inline o path a .json")
    ap.add_argument("--payload-file", default="")
    ap.add_argument("--out", required=True, help="Archivo JSON de salida")
    args = ap.parse_args(argv)

    payload = {}
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as f:
            payload = json.load(f) or {}
    elif args.payload:
        p = args.payload.strip()
        if p.startswith("{") or p.startswith("["):
            payload = json.loads(p)
        elif os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}

    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    result = {"ok": False, "error": "sin ejecutar"}
    try:
        from api_app.jobs import run_action_inprocess

        result = run_action_inprocess(
            args.action,
            payload,
            (args.feeder or "").strip() or None,
            job_id=None,
        )
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
    except Exception as ex:
        traceback.print_exc()
        result = {
            "ok": False,
            "error": "%s: %s" % (type(ex).__name__, ex),
            "traceback": traceback.format_exc(),
        }

    # Salida inmediata: persistir antes del posible teardown CymPy/COM.
    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
    if isinstance(result, dict) and result.get("ok") is False:
        ok = False
    try:
        write_result_and_exit(out_path, result, 0 if ok else 1)
    except Exception as ex_w:
        sys.stderr.write("No se pudo escribir out: %s\n" % ex_w)
        return 2


if __name__ == "__main__":
    sys.exit(main() or 0)
