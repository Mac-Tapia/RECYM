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


def _apply_scenario_new_loads(adapter, settings, scenario):
    """
    Conmuta cargas §3 segun escenario (fisico en CYMDIST).

    situacional → ConnectionStatus=Disconnected (todas las nuevas)
    proyectado  → ConnectionStatus=Connected + P/Q del reporte §3

    Devuelve lista de cargas tocadas [{LoadID, P_kW, Q_kvar, connected}].
    """
    loads = list_connected_spot_loads(settings)
    touched = [
        {"LoadID": r["LoadID"], "P_kW": r["P_kW"], "Q_kvar": r["Q_kvar"]}
        for r in loads
    ]
    if not loads:
        return touched, []
    notes = []
    scen = (scenario or "").strip().lower()
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
                })
            else:
                # proyectado / general: conectar y asegurar P/Q trifasico→por fase
                conn = adapter.set_load_connected(lid, True)
                adapter.set_load_pq(lid, r["P_kW"], r["Q_kvar"], lock=True)
                notes.append({
                    "LoadID": lid,
                    "ConnectionStatus": conn.get("after"),
                    "connected": True,
                    "set": "%.3f/%.3f" % (r["P_kW"], r["Q_kvar"]),
                    "P_kW": r["P_kW"],
                    "Q_kvar": r["Q_kvar"],
                    "role": scen or "proyectado",
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
    s = settings or load_settings()
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

    keep = False
    try:
        from pipeline.run_demand_allocation import load_session
        keep = bool(load_session(s).get("cymdist_keep_open"))
    except Exception:
        keep = False

    # Pausar GUI si Cyme esta abierto (escritura CymPy de conexion §3)
    if keep or scen in ("situacional", "proyectado"):
        try:
            from core.cymdist_com import pause_cymdist_for_cympy
            pause_cymdist_for_cympy(s)
        except Exception as ex:
            print("AVISO pause CYMDIST:", ex)

    # Mitiga 480010 / 260035
    if s.get("auto_fix_lf_warnings", True):
        try:
            from pipeline.fix_lf_warnings import run as fix_lf_warnings
            fix_res = fix_lf_warnings(s)
            result["lf_warnings_fix"] = {
                "ok": fix_res.get("ok"),
                "notes": fix_res.get("notes") or [],
            }
            print("[%s] Pre-fix LF warnings: %s" % (
                s["feeder_id"], "OK" if fix_res.get("ok") else "parcial"))
        except Exception as ex:
            result["lf_warnings_fix"] = {"ok": False, "error": str(ex)}
            print("[%s] AVISO fix_lf_warnings: %s" % (s["feeder_id"], ex))

    adapter = None
    try:
        c = require_cympy(s)
        adapter = CymPyAdapter(c, api, s)
        adapter.open_study()
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
            if s.get("save_after_write", True):
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
        from core.cymdist_com import run_loadflow_com
        if adapter is not None:
            try:
                adapter.close_study(save=False)
            except Exception:
                pass
            adapter = None
        com = run_loadflow_com(s, net, leave_open=keep, kill_existing=not keep)
        meta = {"engine": "COM", "com": com}
        ok = bool(com.get("ok"))
        err = None if ok else com.get("error")
        if ok:
            result["topo"] = com.get("topo") or {}
            result["source_node"] = com.get("source_node")
            result["saved"] = com.get("saved")
            result["warnings"] = com.get("warnings") or []
            result["warn_file"] = com.get("warn_file")
            result["cymdist_open"] = com.get("cymdist_open")
            result["calculation_method"] = com.get("calculation_method")
            result["log_errors"] = com.get("log_errors") or []
    else:
        if adapter is None:
            c = require_cympy(s)
            adapter = CymPyAdapter(c, api, s)
            adapter.open_study()
        from core.sim_params import run_loadflow_safe
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
