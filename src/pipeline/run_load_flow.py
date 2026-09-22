from __future__ import print_function
"""
Flujo de carga normal CYMDIST (sim.LoadFlow / COM Cymdist.LoadFlow).

Segun tutorial CYME «Flujo de carga en redes» (BalLoadFlowInd / IL917123ES):
  analiza el regimen permanente con las cargas YA definidas en el modelo.
NO reparte demanda de cabecera: eso es LoadAllocation (IL917115ES).

Escenarios RECYM (tras conectar SpotLoad §3) — independientes:
  - situacional: DESCONECTA fisicamente todas las cargas nuevas (§3) y corre flujo
  - proyectado: CONECTA fisicamente las cargas nuevas (§3) con su P/Q y corre flujo
Cada boton deja el modelo en ese estado (no se restaura automaticamente).

Anti-cuelgue UI (§5.1):
  - sin db.SaveProject en el proceso SPA
  - COM LoadFlow en SUBPROCESO con timeout
  - mensajes de progreso al job SSE
"""
import json
import os
from core.common import require_cympy, load_json, mkdir, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path
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
    Conmuta cargas nuevas del §4 (SpotLoad concentrada) según escenario.

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
    print("[LF] Cargas §4 a conmutar (%s): %d → %s" % (
        scen or "general",
        len(loads),
        ", ".join("%s(%.0fkW)" % (r["LoadID"], r["P_kW"]) for r in loads)[:200],
    ), flush=True)
    for r in loads:
        lid = r["LoadID"]
        try:
            if scen == "situacional":
                # Desconexion fisica: no aporta al flujo (ni a distribucion)
                conn = adapter.set_load_connected(lid, False)
                # Mantener P/Q en casilleros (solo desconectada)
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
                # proyectado / general: conectar y asegurar P/Q trifasico→por fase
                conn = adapter.set_load_connected(lid, True)
                if float(r.get("P_kW") or 0) > 0 or float(r.get("Q_kvar") or 0) > 0:
                    # lock=False: no dejar SpotLoad §3 Locked; 3.3 necesita
                    # residual Unlocked para repartir cabecera − fijos.
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
      - situacional = desconecta cargas §3 y ejecuta LoadFlow solo
      - proyectado  = conecta cargas §3 y ejecuta LoadFlow solo
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
    result = {
        "feeder_id": s.get("feeder_id"),
        "network_id": net,
        "module": "LoadFlow",
        "manual": "docs/cymdist/BalLoadFlowInd.txt (IL917123ES)",
        "scenario": scen or "general",
        "status": "ok",
        "note": (
            "Cada boton es independiente: situacional desconecta cargas §3; "
            "proyectado las conecta. No redistribuir tras SpotLoad."
        ),
    }
    if s.get("dry_run"):
        result["status"] = "dry_run"
        print("[%s] DRY_RUN: flujo no ejecutado." % s["feeder_id"])
        return result

    prefer_com = s.get("loadflow_engine", "COM").upper() != "CYMPY"
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

    # Pausar GUI si Cyme esta abierto (escritura CymPy de conexion §3)
    if keep or scen in ("situacional", "proyectado"):
        try:
            from core.cymdist_com import pause_cymdist_for_cympy
            pause_cymdist_for_cympy(s)
        except Exception as ex:
            print("AVISO pause CYMDIST:", ex)

    # Mitiga 480010 / 260035 — omitir si ya se aplicó (SaveProject colgaba aquí)
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
            print("[%s] Pre-fix LF warnings: %s" % (
                s["feeder_id"], "OK" if fix_res.get("ok") else "parcial"))
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
        _progress(s, "pre-fix omitido (ya aplicado)")

    adapter = None
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
            if touched:
                print("[%s] Cargas §3 escenario %s: %d (%s)" % (
                    s["feeder_id"],
                    target,
                    len(touched),
                    "DESCONECTADAS" if target == "situacional" else "CONECTADAS",
                ))
            # Persistir ConnectionStatus en .zxst para que el COM lo lea.
            # Sin SaveProject (skip_db_project_save).
            if touched and s.get("save_after_write", True):
                try:
                    adapter.save_study()
                except Exception as ex:
                    print("AVISO save pre-LF:", ex)
    except Exception as ex:
        result["scenario_prep_error"] = str(ex)
        print("[%s] AVISO preparar escenario cargas nuevas: %s" % (s["feeder_id"], ex))

    meta = {}
    ok = False
    err = None

    if prefer_com:
        from core.cympy_job import run_cympy_job
        from core import cympy_adapter as _cym_ad
        if adapter is not None:
            try:
                adapter.close_study(save=False)
            except Exception:
                pass
            adapter = None
        try:
            _cym_ad._PROCESS_STUDY_PATH = None
        except Exception:
            pass

        timeout_com = float(
            s.get("loadflow_com_timeout_sec")
            or s.get("cympy_job_timeout_sec")
            or 120
        )
        _progress(s, "COM LoadFlow (subproceso ≤%ss)..." % int(timeout_com))
        # leave_open=False en worker: no dejar Cyme colgado; resume_gui aparte si keep
        com = run_cympy_job(
            "loadflow_com",
            {
                "feeder_id": s.get("feeder_id"),
                "network_id": net,
                "study_path": s.get("study_path"),
                "database_mdb": s.get("database_mdb"),
                "database_connection_name": s.get("database_connection_name"),
                "leave_open": False,
            },
            settings=s,
            timeout_sec=timeout_com,
        )
        meta = {"engine": "COM", "com": com}
        ok = bool(com.get("ok"))
        err = None if ok else (com.get("error") or "LoadFlow COM falló/timeout")
        if ok:
            result["topo"] = com.get("topo") or {}
            result["source_node"] = com.get("source_node")
            result["saved"] = com.get("saved")
            result["warnings"] = com.get("warnings") or []
            result["warn_file"] = com.get("warn_file")
            result["cymdist_open"] = False
            result["calculation_method"] = com.get("calculation_method")
            result["log_errors"] = com.get("log_errors") or []
            result["com_elapsed_sec"] = com.get("elapsed_sec")
    else:
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

    # No restaurar tras situacional: el modelo queda desconectado hasta proyectado.
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

    result["engine"] = (meta or {}).get("engine")
    if ok:
        result["status"] = "ok"
        _progress(s, "LoadFlow OK (%s)" % (scen or "general"))
        print("[%s] LoadFlow OK via %s [%s]" % (
            s["feeder_id"], result.get("engine"), scen or "general"))
    else:
        result["status"] = "error"
        result["error"] = err
        result["ayuda"] = (
            "LoadFlow fallo. CymPy reporta 130013 cuando los complementos de "
            "simulacion no autentican; RECYM reintenta automaticamente via COM "
            "(Cymdist.Application). Verifique database_mdb, study_path y que no "
            "haya otra sesion Cyme bloqueando el estudio."
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
