# -*- coding: utf-8 -*-
"""Ejecuta ciclo calidad hasta converger para un feeder (CLI)."""
from __future__ import print_function
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))
sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))

from core.feeder_context import load_settings
from pipeline.diagnostic_registry import load_catalog
from pipeline.model_quality_gate import run_until_converges


def main():
    feeder = (sys.argv[1] if len(sys.argv) > 1 else "IN112").strip().upper()
    max_iters = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    load_catalog(force=True)
    s = load_settings(feeder_id=feeder)
    print("FEEDER", feeder, "net", s.get("network_id"), "max_iters", max_iters, flush=True)
    result = run_until_converges(s, max_iters=max_iters, skip_initial_lf=False)
    out = os.path.join(ROOT, "data", "output", "feeders", feeder, "diagnostics", "cycle_until_clean.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("OK", result.get("ok"), "converge", result.get("converge"), "ready", result.get("ready"), flush=True)
    print("MSG", result.get("msg") or result.get("error"), flush=True)
    for line in (result.get("log") or []):
        print(" ", line, flush=True)
    print("OUT", out, flush=True)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    try:
        code = main()
    except Exception as ex:
        import traceback
        traceback.print_exc()
        code = 1
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)
