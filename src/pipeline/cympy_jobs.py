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
    vll = payload.get("Vll_kV")
    va = payload.get("Va_kV")
    vb = payload.get("Vb_kV")
    vc = payload.get("Vc_kV")
    try:
        pause_cymdist_for_cympy(s)
    except Exception as ex:
        print("AVISO pause:", ex)
    info = apply_cabecera_medicion(
        s, p, q, save=True,
        vll_kv=vll, va_kv=va, vb_kv=vb, vc_kv=vc,
    )
    return {
        "ok": True,
        "cymdist": info,
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "study_path": s.get("study_path"),
        "P_kW": p,
        "Q_kvar": q,
        "Vll_kV": vll,
        "Va_kV": va,
        "Vb_kV": vb,
        "Vc_kV": vc,
        "msg": "SetDemand + tensiones fuente OK",
    }


def job_loadallocation_com(payload):
    """LoadAllocation vía COM Cyme.exe en proceso aislado (evita cuelgue UI)."""
    from core.feeder_context import load_settings
    from core.cymdist_com import run_loadallocation_com, _kill_cyme

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in ("study_path", "database_mdb", "network_id", "database_connection_name"):
        if payload.get(k):
            s[k] = payload[k]
    # Asegurar que no quede Cyme zombie bloqueando OpenStudy
    try:
        _kill_cyme()
    except Exception:
        pass
    return run_loadallocation_com(
        s,
        network_id=payload.get("network_id") or s.get("network_id"),
        p_kw=payload.get("P_kW"),
        q_kvar=payload.get("Q_kvar"),
        method=payload.get("method") or "KWH",
        kill_existing=True,
    )


def job_loadflow_com(payload):
    """LoadFlow vía COM Cyme.exe en proceso aislado (evita cuelgue UI §5)."""
    from core.feeder_context import load_settings
    from core.cymdist_com import run_loadflow_com, _kill_cyme

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in ("study_path", "database_mdb", "network_id", "database_connection_name", "output_dir"):
        if payload.get(k):
            s[k] = payload[k]
    leave_open = bool(payload.get("leave_open"))
    try:
        _kill_cyme()
    except Exception:
        pass
    return run_loadflow_com(
        s,
        network_id=payload.get("network_id") or s.get("network_id"),
        leave_open=leave_open,
        kill_existing=True,
    )


def job_capture_informe_color(payload):
    """
    Capturas CYMDIST del informe (VoltageLevel/LoadingLevel) en Python 32-bit.
    Evita fallos de comtypes/CymPy cuando la UI corre en Python 64-bit.
    """
    import os as _os
    _os.environ["RECYM_CAPTURE_WORKER"] = "1"
    from core.feeder_context import load_settings
    from pipeline.capture_informe_color_views import capture_informe_color_views

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in (
        "study_path", "database_mdb", "network_id", "database_connection_name",
        "output_dir", "cyme_root",
    ):
        if payload.get(k):
            s[k] = payload[k]
    scenarios = payload.get("scenarios")
    open_gui = payload.get("open_gui")
    if open_gui is None:
        open_gui = True
    force = bool(payload.get("force", True))
    return capture_informe_color_views(
        settings=s,
        scenarios=scenarios,
        open_gui=bool(open_gui),
        force=force,
    )


JOBS = {
    "cabecera": job_cabecera,
    "loadallocation_com": job_loadallocation_com,
    "loadflow_com": job_loadflow_com,
    "capture_informe_color": job_capture_informe_color,
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
