# -*- coding: utf-8 -*-
"""Worker CymPy (proceso hijo). Uso interno vía core.cympy_job.run_cympy_job."""
from __future__ import print_function

import argparse
import json
import os
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))
sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))


def _out(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("JOB_RESULT", json.dumps({"ok": data.get("ok"), "error": data.get("error")}, ensure_ascii=False))


def job_cabecera(payload):
    from core.feeder_context import load_settings
    from core.cymdist_com import pause_cymdist_for_cympy
    from pipeline.run_demand_allocation import apply_cabecera_medicion

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    # Override rutas si vienen del UI
    for k in ("study_path", "database_mdb", "network_id"):
        if payload.get(k):
            s[k] = payload[k]
    p = float(payload["P_kW"])
    q = float(payload["Q_kvar"])
    try:
        pause_cymdist_for_cympy(s)
    except Exception as ex:
        print("AVISO pause:", ex)
    info = apply_cabecera_medicion(s, p, q, save=True)
    return {
        "ok": True,
        "cymdist": info,
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "study_path": s.get("study_path"),
        "P_kW": p,
        "Q_kvar": q,
        "msg": "SetDemand OK",
    }


JOBS = {
    "cabecera": job_cabecera,
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out", dest="out_path", required=True)
    args = ap.parse_args(argv)
    try:
        with open(args.in_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        job = (payload.get("job") or "").strip()
        if job not in JOBS:
            _out(args.out_path, {"ok": False, "error": "Job desconocido: %s" % job})
            return 2
        print("JOB_START", job, flush=True)
        result = JOBS[job](payload)
        if not isinstance(result, dict):
            result = {"ok": False, "error": "Job sin dict"}
        _out(args.out_path, result)
        # 0 aunque CymPy vaya a crashear al salir: el JSON ya está en disco
        return 0 if result.get("ok") else 1
    except Exception as ex:
        traceback.print_exc()
        try:
            _out(args.out_path, {"ok": False, "error": str(ex), "trace": traceback.format_exc()[-2000:]})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    # Importante: salir ANTES del teardown COM destructivo si ya escribimos out.json
    code = main()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    # os._exit evita destructores CymPy que hacen ACCESS_VIOLATION
    os._exit(code)
