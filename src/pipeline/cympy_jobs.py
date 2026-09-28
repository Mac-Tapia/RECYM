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
    from core.cymdist_com import set_network_demand_com, open_cymdist_gui
    from pipeline.run_demand_allocation import apply_cabecera_medicion

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    # Override rutas si vienen del UI
    for k in ("study_path", "database_mdb", "network_id", "ui_study_path",
              "database_connection_name"):
        if payload.get(k):
            s[k] = payload[k]
    # Conservar elección UI exacta (.xst) para OpenStudy COM / GUI
    ui_sp = (payload.get("ui_study_path") or payload.get("study_path") or "").strip()
    if ui_sp and os.path.isfile(ui_sp):
        s["ui_study_path"] = ui_sp
    sp = ui_sp or s.get("study_path") or ""
    if sp:
        s["ui_study_path"] = sp
        s["study_path"] = sp
        s["study_file"] = os.path.basename(sp)
    # Obligatorio: persistir en estudio + MDB para reabrir desde CYMDIST
    s["skip_db_project_save"] = False
    s["isolated_work_study"] = False
    s["persist_cabecera_to_db"] = True
    p = float(payload["P_kW"])
    q = float(payload["Q_kvar"])
    vll = payload.get("Vll_kV")
    va = payload.get("Va_kV")
    vb = payload.get("Vb_kV")
    vc = payload.get("Vc_kV")

    # 1) Cerrar/pausar GUI antes del commit: el backup debe existir antes de la
    #    primera escritura y no puede haber un Save COM previo no auditado.
    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(s)
    except Exception as ex:
        print("AVISO pause Cyme cabecera:", ex)
    info_com = {"ok": False, "skipped": True, "reason": "coordinated_cympy_commit"}

    # 2) CymPy opcional: tensiones fuente + persistencia MDB (sin matar Cyme si COM ok)
    info = {}
    info["com"] = info_com
    cympy_err = None
    try:
        # No pause/kill: el SetDemand ya está en la GUI; CymPy puede fallar si
        # el archivo está bloqueado — no es bloqueante si COM ok.
        info_py = apply_cabecera_medicion(
            s, p, q, save=True,
            vll_kv=vll, va_kv=va, vb_kv=vb, vc_kv=vc,
        )
        info["cympy"] = info_py
        info["commit"] = info_py.get("commit")
        if info_py.get("saved"):
            info["saved"] = True
        if info_py.get("db_updated"):
            info["db_updated"] = True
        if info_py.get("project_saved"):
            info["project_saved"] = True
        if info_py.get("source_voltage"):
            info["source_voltage"] = info_py.get("source_voltage")
    except Exception as ex_py:
        cympy_err = str(ex_py)
        print("AVISO CymPy cabecera (COM ya escribió GUI):", ex_py)
        info["cympy_error"] = cympy_err

    try:
        open_cymdist_gui(s, kill_existing=False, reason="cabecera_post_commit")
    except Exception as ex_gui:
        info["gui_reopen_error"] = str(ex_gui)

    ok = bool((info.get("commit") or {}).get("reopen_verified"))
    persist = (info.get("cympy") or {}).get("persist") or {}
    return {
        "ok": ok,
        "cymdist": info,
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "study_path": info_com.get("study_path") or s.get("ui_study_path") or s.get("study_path"),
        "ui_study_path": s.get("ui_study_path") or payload.get("study_path"),
        "database_mdb": info_com.get("database_mdb") or s.get("database_mdb"),
        "P_kW": p,
        "Q_kvar": q,
        "Vll_kV": vll,
        "Va_kV": va,
        "Vb_kV": vb,
        "Vc_kV": vc,
        "study_saved": bool(info_com.get("saved") or info.get("saved")),
        "db_updated": bool(info.get("db_updated")),
        "project_saved": bool(info.get("project_saved")),
        "persist": persist,
        "commit": info.get("commit"),
        "attach_mode": info_com.get("attach_mode"),
        "P_sum_kW": info_com.get("P_sum_kW"),
        "msg": (
            info_com.get("msg")
            or (
                "Cabecera persistida en estudio + BD"
                if info.get("saved") and info.get("db_updated")
                else (
                    "Cabecera en estudio (BD parcial)"
                    if info.get("saved")
                    else "SetDemand OK pero Save incompleto"
                )
            )
        ),
        "error": None if ok else (info_com.get("error") or cympy_err),
    }


def job_loadallocation_com(payload):
    """LoadAllocation vía COM Cyme.exe en proceso aislado (evita cuelgue UI)."""
    from core.feeder_context import load_settings
    from core.cymdist_com import run_loadallocation_com

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in ("study_path", "database_mdb", "network_id", "database_connection_name",
              "ui_study_path"):
        if payload.get(k):
            s[k] = payload[k]
    # NO matar Cyme: CreateObject reusa la GUI con BD/estudio §1
    return run_loadallocation_com(
        s,
        network_id=payload.get("network_id") or s.get("network_id"),
        p_kw=payload.get("P_kW"),
        q_kvar=payload.get("Q_kvar"),
        method=payload.get("method") or "KWH",
        kill_existing=False,
        leave_open=True,
        disconnect_load_ids=payload.get("disconnect_load_ids") or [],
    )


def job_loadflow_com(payload):
    """LoadFlow vía COM Cyme.exe (mismo patrón soft que §3.3 LoadAllocation)."""
    from core.feeder_context import load_settings
    from core.cymdist_com import run_loadflow_com

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in (
        "study_path",
        "database_mdb",
        "network_id",
        "database_connection_name",
        "output_dir",
        "ui_study_path",
    ):
        if payload.get(k):
            s[k] = payload[k]
    leave_open = payload.get("leave_open")
    if leave_open is None:
        leave_open = True
    kill_existing = bool(payload.get("kill_existing", False))
    scenario = (payload.get("scenario") or "").strip().lower() or None
    # NO matar Cyme: CreateObject reusa la GUI con BD/estudio §1
    return run_loadflow_com(
        s,
        network_id=payload.get("network_id") or s.get("network_id"),
        leave_open=bool(leave_open),
        kill_existing=kill_existing,
        scenario=scenario,
        spot_loads=payload.get("spot_loads"),
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


def job_deliver_informe(payload):
    """Entrega autonoma del informe (LF opcional + capturas + Word/Excel/PDF + OCR)."""
    from core.feeder_context import load_settings
    from pipeline.deliver_informe import deliver_informe

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in (
        "study_path", "database_mdb", "network_id", "database_connection_name",
        "output_dir", "cyme_root",
    ):
        if payload.get(k):
            s[k] = payload[k]
    ocr_review = payload.get("ocr_review")
    if ocr_review is None:
        ocr_review = True
    return deliver_informe(
        settings=s,
        ensure_lf=bool(payload.get("ensure_lf", True)),
        force_captures=bool(payload.get("force_captures", False)),
        require_delivery=bool(payload.get("require_delivery", True)),
        scenarios_lf=payload.get("scenarios") or payload.get("scenarios_lf"),
        ocr_review=bool(ocr_review),
        ocr_review_rounds=int(payload.get("ocr_rounds") or payload.get("ocr_review_rounds") or 3),
        informe_mode=payload.get("mode") or payload.get("informe_mode") or "completo",
    )


def job_review_informe_ocr(payload):
    """Revision OCR del PDF con correccion (hasta 3 rondas)."""
    from core.feeder_context import load_settings
    from pipeline.review_informe_pdf import review_and_correct_informe, review_informe_pdf

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    if payload.get("review_only"):
        return review_informe_pdf(s, max_pages=int(payload.get("max_pages") or 10))
    return review_and_correct_informe(
        s,
        max_rounds=int(payload.get("rounds") or payload.get("ocr_rounds") or 3),
        max_pages=int(payload.get("max_pages") or 10),
    )


def job_max_demand_multi(payload):
    """Extrae y escribe máxima demanda en todas las redes del estudio (p.ej. CA101V2)."""
    from core.feeder_context import load_settings, resolve_writable_study_path
    from pipeline.apply_max_demand_multi import apply_max_demand_multi

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in ("study_path", "database_mdb", "network_id", "ui_study_path",
              "database_connection_name", "network_ids"):
        if payload.get(k):
            s[k] = payload[k]
    ui_sp = (payload.get("ui_study_path") or payload.get("study_path") or "").strip()
    if ui_sp and os.path.isfile(ui_sp):
        s["ui_study_path"] = ui_sp
    sp = s.get("study_path") or ui_sp or ""
    if sp:
        alt = resolve_writable_study_path(sp, s)
        if alt and alt != sp:
            s["ui_study_path"] = s.get("ui_study_path") or sp
            s["study_path"] = alt
            s["study_file"] = os.path.basename(alt)
    s["skip_db_project_save"] = False
    s["persist_cabecera_to_db"] = True
    return apply_max_demand_multi(
        s,
        network_ids=payload.get("network_ids"),
        medicion_file=payload.get("medicion_file"),
        write_cymdist=payload.get("write_cymdist", True) is not False,
        save=payload.get("save", True) is not False,
        use_com=bool(payload.get("use_com")),
        run_allocation=payload.get("run_allocation", True) is not False,
    )


def job_transfer_voltage_quality(payload):
    """Evalúa transferencia por calidad de tensión sobre transfer_pair (pico)."""
    from core.feeder_context import load_settings, resolve_writable_study_path
    from pipeline.transfer_voltage_quality import evaluate_transfer_voltage_quality

    feeder = (payload.get("feeder_id") or "").strip() or None
    s = load_settings(feeder_id=feeder, synthesize=True)
    for k in ("study_path", "database_mdb", "network_id", "ui_study_path",
              "database_connection_name", "network_ids", "transfer_pair"):
        if payload.get(k):
            s[k] = payload[k]
    sp = s.get("study_path") or ""
    if sp:
        alt = resolve_writable_study_path(sp, s)
        if alt:
            s["study_path"] = alt
    return evaluate_transfer_voltage_quality(
        s,
        vmin_limit_pu=float(payload.get("vmin_limit_pu") or 0.95),
        vmax_limit_pu=float(payload.get("vmax_limit_pu") or 1.05),
        apply_switch=bool(payload.get("apply_switch")),
        ensure_max_demand=bool(payload.get("ensure_max_demand")),
    )


JOBS = {
    "cabecera": job_cabecera,
    "max_demand_multi": job_max_demand_multi,
    "transfer_voltage_quality": job_transfer_voltage_quality,
    "loadallocation_com": job_loadallocation_com,
    "loadflow_com": job_loadflow_com,
    "capture_informe_color": job_capture_informe_color,
    "deliver_informe": job_deliver_informe,
    "review_informe_ocr": job_review_informe_ocr,
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
