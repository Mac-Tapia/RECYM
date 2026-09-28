from __future__ import print_function
"""
Flujo de carga normal CYMDIST (COM Cymdist.LoadFlow; CymPy solo si se fuerza).

Segun tutorial CYME «Flujo de carga en redes» (BalLoadFlowInd / IL917123ES):
  analiza el regimen permanente con las cargas YA definidas en el modelo.
NO reparte demanda de cabecera: eso es LoadAllocation (IL917115ES).

Escenarios RECYM (tras conectar SpotLoad §4) — independientes:
  - situacional: DESCONECTA fisicamente todas las cargas nuevas (§4) y corre flujo
  - proyectado: CONECTA fisicamente las cargas nuevas (§4) con su P/Q y corre flujo
Cada boton deja el modelo en ese estado (no se restaura automaticamente).

Anti-AV §5 (mismo patron que §3.3):
  - motor COM in-process (sin require_cympy / SetValue ConnectionStatus)
  - sin SaveProject MDB grande
  - leave_open / attach a la sesion GUI §1
"""
import json
import os
from core.common import require_cympy, load_json, mkdir, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path
from core.report_provenance import tag_context
from pipeline.add_spot_load import list_connected_spot_loads


def _safe_query(adapter, keyword, network_id):
    try:
        return adapter.query_topo(keyword, network_id)
    except Exception as ex:
        return "ERR:%s" % ex


def _progress(settings, msg):
    print("[LF]", msg, flush=True)
    try:
        cb = (settings or {}).get("_job_progress")
        if callable(cb):
            cb(msg)
    except Exception:
        pass


def _apply_scenario_new_loads(adapter, settings, scenario):
    """
    Conmuta cargas nuevas del §4 (SpotLoad concentrada) según escenario (ruta CymPy).

    situacional → ConnectionStatus=Disconnected (no aportan al flujo)
    proyectado  → ConnectionStatus=Connected + P/Q del reporte §4

    Devuelve lista de cargas tocadas [{LoadID, P_kW, Q_kvar, connected}].
    """
    loads = list_connected_spot_loads(settings)
    touched = [
        {"LoadID": r["LoadID"], "P_kW": r["P_kW"], "Q_kvar": r["Q_kvar"]}
        for r in loads
    ]
    if not loads:
        print("[LF] AVISO: sin cargas §4 guardadas (4.2 o 4.3) — escenario no conmuta SpotLoad nueva")
        return touched, []
    notes = []
    scen = (scenario or "").strip().lower()
    print("[LF] Cargas §4 a conmutar (%s): %d -> %s" % (
        scen or "general",
        len(loads),
        ", ".join("%s(%.0fkW)" % (r["LoadID"], r["P_kW"]) for r in loads)[:200],
    ), flush=True)
    for r in loads:
        lid = r["LoadID"]
        try:
            if scen == "situacional":
                conn = adapter.set_load_connected(lid, False)
                notes.append({
                    "LoadID": lid,
                    "ConnectionStatus": conn.get("after"),
                    "connected": False,
                    "P_kW": r["P_kW"],
                    "Q_kvar": r["Q_kvar"],
                    "role": "situacional",
                    "Fuente": r.get("Fuente"),
                })
            else:
                conn = adapter.set_load_connected(lid, True)
                if float(r.get("P_kW") or 0) > 0 or float(r.get("Q_kvar") or 0) > 0:
                    adapter.set_load_pq(lid, r["P_kW"], r["Q_kvar"], lock=False)
                notes.append({
                    "LoadID": lid,
                    "ConnectionStatus": conn.get("after"),
                    "connected": True,
                    "set": "%.3f/%.3f" % (r["P_kW"], r["Q_kvar"]),
                    "P_kW": r["P_kW"],
                    "Q_kvar": r["Q_kvar"],
                    "role": scen or "proyectado",
                    "Fuente": r.get("Fuente"),
                })
        except Exception as ex:
            notes.append({"LoadID": lid, "error": str(ex)})
    return touched, notes


def run_load_flow(settings=None, scenario=None):
    """
    scenario: None | 'situacional' | 'proyectado'
      - situacional = desconecta cargas §4 y ejecuta LoadFlow solo
      - proyectado  = conecta cargas §4 y ejecuta LoadFlow solo
    Guarda loadflow_result.json y, si hay scenario, loadflow_<scenario>.json
    """
    s = dict(settings or load_settings())
    # Evitar SaveProject en MDB grande (cuelga 5.1)
    s["skip_db_project_save"] = True
    s.setdefault("auto_backup", False)
    api = load_json("config/cympy_api_map.json")
    net = str(s.get("network_id") or "")
    scen = (scenario or "").strip().lower() or None
    if scen and scen not in ("situacional", "proyectado"):
        scen = None
    result = tag_context(s, {
        "feeder_id": s.get("feeder_id"),
        "network_id": net,
        "module": "LoadFlow",
        "manual": "docs/cymdist/BalLoadFlowInd.txt (IL917123ES)",
        "scenario": scen or "general",
        "status": "ok",
        "note": (
            "Cada boton es independiente: situacional desconecta cargas §4; "
            "proyectado las conecta. No redistribuir tras SpotLoad."
        ),
    })
    if s.get("dry_run"):
        result["status"] = "dry_run"
        print("[%s] DRY_RUN: flujo no ejecutado." % s["feeder_id"])
        return result

    # Default COM (como §3.3). Solo CymPy si loadflow_engine=CYMPY.
    prefer_com = str(s.get("loadflow_engine") or "COM").upper() != "CYMPY"
    print("[%s] Ejecutando LoadFlow (flujo de carga normal)%s..." % (
        s["feeder_id"],
        (" [%s]" % scen) if scen else "",
    ))
    _progress(s, "5 · %s · iniciando..." % (scen or "general"))

    keep = False
    try:
        from pipeline.run_demand_allocation import load_session
        sess = load_session(s)
        keep = bool(sess.get("cymdist_keep_open"))
        lf_fixed = bool(
            sess.get("lf_params_fixed_130013")
            or sess.get("loadallocation_com_ok")
            or sess.get("lf_warnings_fixed")
        )
    except Exception:
        keep = False
        lf_fixed = False

    meta = {}
    ok = False
    err = None
    adapter = None

    if prefer_com:
        # --- Ruta COM-first (anti AV 0xC0000005): sin require_cympy ---
        # No fix_lf_warnings ni open_study CymPy: provocan Access Violation
        # en el worker aislado tras §3.2/§3.3.
        from core.cymdist_com import run_loadflow_com

        spot_loads = []
        try:
            spot_loads = list_connected_spot_loads(s)
        except Exception as ex_sl:
            print("[LF] AVISO list_connected_spot_loads:", ex_sl)

        leave_open = bool(keep) or bool(s.get("cymdist_leave_open", True))
        _progress(
            s,
            "COM LoadFlow [%s] (sin CymPy, leave_open=%s)..."
            % (scen or "general", leave_open),
        )
        com = run_loadflow_com(
            s,
            network_id=net,
            leave_open=leave_open,
            kill_existing=False,
            scenario=scen,
            spot_loads=spot_loads if scen else None,
        )
        meta = {"engine": "COM", "com": com}
        ok = bool(com.get("ok"))
        err = None if ok else (com.get("error") or "LoadFlow COM fallo")
        result["engine"] = "COM"
        result["topo"] = com.get("topo") or {}
        result["source_node"] = com.get("source_node")
        result["saved"] = com.get("saved")
        result["warnings"] = com.get("warnings") or []
        result["warn_file"] = com.get("warn_file")
        result["cymdist_open"] = bool(com.get("cymdist_open"))
        result["calculation_method"] = com.get("calculation_method")
        result["log_errors"] = com.get("log_errors") or []
        result["com_elapsed_sec"] = com.get("elapsed_sec")
        result["attach_mode"] = com.get("attach_mode")
        result["new_loads_scenario"] = com.get("new_loads_scenario") or []
        result["n_new_loads"] = com.get("n_new_loads") or 0
        result["new_loads_connected"] = com.get("new_loads_connected")
        if not ok:
            result["lf_warnings_fix"] = {"ok": True, "skipped": True, "reason": "prefer_COM"}
    else:
        # --- Ruta CymPy legacy (solo si loadflow_engine=CYMPY) ---
        if keep or scen in ("situacional", "proyectado"):
            try:
                from core.cymdist_com import pause_cymdist_for_cympy
                pause_cymdist_for_cympy(s)
            except Exception as ex:
                print("AVISO pause CYMDIST:", ex)

        do_fix = bool(s.get("auto_fix_lf_warnings", True)) and not (
            lf_fixed and not s.get("force_fix_lf_warnings")
        )
        if do_fix:
            try:
                _progress(s, "pre-fix avisos LF...")
                from pipeline.fix_lf_warnings import run as fix_lf_warnings
                fix_res = fix_lf_warnings(s)
                result["lf_warnings_fix"] = {
                    "ok": fix_res.get("ok"),
                    "notes": (fix_res.get("notes") or [])[:20],
                }
                try:
                    from pipeline.run_demand_allocation import load_session, save_session
                    sess2 = load_session(s)
                    sess2["lf_warnings_fixed"] = True
                    save_session(s, sess2)
                except Exception:
                    pass
            except Exception as ex:
                result["lf_warnings_fix"] = {"ok": False, "error": str(ex)}
                print("[%s] AVISO fix_lf_warnings: %s" % (s["feeder_id"], ex))
        else:
            result["lf_warnings_fix"] = {
                "ok": True,
                "skipped": True,
                "reason": "ya_aplicado_en_sesion",
            }

        try:
            _progress(s, "estudio / escenario %s..." % (scen or "general"))
            c = require_cympy(s)
            adapter = CymPyAdapter(c, api, s)
            adapter.open_study(force_backup=False)
            if scen in ("situacional", "proyectado") or list_connected_spot_loads(s):
                target = scen or "proyectado"
                touched, scen_notes = _apply_scenario_new_loads(adapter, s, target)
                result["new_loads_scenario"] = scen_notes
                result["n_new_loads"] = len(touched)
                result["new_loads_connected"] = (target != "situacional")
                if touched and s.get("save_after_write", True):
                    try:
                        adapter.save_study()
                    except Exception as ex:
                        print("AVISO save pre-LF:", ex)
        except Exception as ex:
            result["scenario_prep_error"] = str(ex)
            print("[%s] AVISO preparar escenario cargas nuevas: %s" % (s["feeder_id"], ex))

        if adapter is None:
            c = require_cympy(s)
            adapter = CymPyAdapter(c, api, s)
            adapter.open_study(force_backup=False)
        from core.sim_params import run_loadflow_safe
        _progress(s, "LoadFlow CymPy...")
        ok, err, meta = run_loadflow_safe(adapter.cympy, net, settings=s)
        if ok and meta.get("engine") == "CymPy":
            keys = (api.get("result_keywords") or {})
            result["topo"] = {
                "KWTOT": _safe_query(adapter, keys.get("network_kw") or "KWTOT", net),
                "KVARTOT": _safe_query(adapter, keys.get("network_kvar") or "KVARTOT", net),
            }
            if s.get("save_after_write", True):
                try:
                    adapter.save_study()
                    result["saved"] = True
                except Exception as ex:
                    result["saved"] = False
                    result["save_error"] = str(ex)
        elif ok and meta.get("engine") == "COM":
            com = (meta.get("com") or {})
            result["topo"] = com.get("topo") or {}
            result["source_node"] = com.get("source_node")
            result["saved"] = com.get("saved")

        if adapter is not None:
            try:
                adapter.close_study(save=False)
            except Exception:
                pass

        if keep:
            try:
                from core.cymdist_com import resume_cymdist_gui
                _progress(s, "reabriendo GUI Cyme...")
                com_r = resume_cymdist_gui(
                    s,
                    reason="post_loadflow_%s" % (scen or "general"),
                )
                result["cymdist_open"] = bool(com_r.get("cymdist_open"))
            except Exception as ex:
                result["resume_error"] = str(ex)

    result["engine"] = (meta or {}).get("engine") or result.get("engine")
    if ok:
        result["status"] = "ok"
        _progress(s, "LoadFlow OK (%s)" % (scen or "general"))
        print("[%s] LoadFlow OK via %s [%s]" % (
            s["feeder_id"], result.get("engine"), scen or "general"))
    else:
        result["status"] = "error"
        result["error"] = err
        result["ayuda"] = (
            "LoadFlow fallo. Por defecto RECYM usa motor COM (Cymdist.Application) "
            "como en §3.3. Verifique database_mdb, study_path y que no haya otra "
            "sesion Cyme bloqueando el estudio. Si forzo CYMPY, el worker puede "
            "caer con Access Violation 0xC0000005."
        )
        _progress(s, "ERROR LoadFlow: %s" % err)
        print("ERROR LoadFlow:", err)

    out_dir = os.path.dirname(output_path(s, "demand", "loadflow_result.json"))
    mkdir(out_dir)
    out = os.path.join(out_dir, "loadflow_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    result["saved_to"] = out
    print(out)
    if scen:
        tagged = os.path.join(out_dir, "loadflow_%s.json" % scen)
        with open(tagged, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        result["saved_scenario_to"] = tagged
        print(tagged)
    return result


def main():
    import sys
    scenario = None
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--scenario" and i + 1 < len(argv):
            scenario = argv[i + 1]
        elif a.startswith("--scenario="):
            scenario = a.split("=", 1)[1]
    result = run_load_flow(scenario=scenario)
    print(result)
    if result.get("status") == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    run_cympy_main(main)
