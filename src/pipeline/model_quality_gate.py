# -*- coding: utf-8 -*-
"""
Gate de calidad del modelo CYMDIST (capa 1 / previo a §2 UI).

Flujo:
  1. NetworkDiagnostic (API) → errores
  2. Proponer correcciones (tablas Correcciones / correcciones_propuestas)
  3. Aplicar bulk_fix + fix_base_voltages
  4. LoadFlow + IsValidResults → convergencia
  5. Repetir hasta converger o max_iters

No usa run_cympy_main (os._exit) — pensado para invocarse desde Flask.
"""
from __future__ import print_function
import csv
import json
import os
from collections import Counter

from core.common import require_cympy, load_json, write_csv, ts, truthy
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path
from pipeline.run_demand_allocation import load_session, save_session

# Listo solo si no quedan Error / Warning / Hint del NetworkDiagnostic
PROBLEM_SEVERITIES_LOCAL = ("Error", "Warning", "Hint")


def _pause_gui(settings):
    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(settings)
    except Exception as ex:
        print("AVISO pause CYMDIST:", ex)


def _read_csv(path):
    if not path or not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _is_problem_row(r):
    flag = (r.get("Requiere_Correccion") or "").strip().upper()
    if flag == "NO":
        return False
    if flag == "SI":
        return True
    return (r.get("Severidad") or "").strip() in PROBLEM_SEVERITIES_LOCAL


def _diag_summary_from_rows(rows, settings, phase="before"):
    by_code = Counter((r.get("Codigo") or "(sin_codigo)") for r in rows)
    by_sev = Counter((r.get("Severidad") or "") for r in rows)
    problems = [r for r in rows if _is_problem_row(r)]
    n_err = sum(1 for r in problems if (r.get("Severidad") or "") == "Error")
    n_warn = sum(1 for r in problems if (r.get("Severidad") or "") == "Warning")
    n_hint = sum(1 for r in problems if (r.get("Severidad") or "") == "Hint")
    return {
        "phase": phase,
        "feeder_id": settings.get("feeder_id"),
        "network_id": settings.get("network_id"),
        "timestamp": ts(),
        "total_messages": len(rows),
        "n_problems": len(problems),
        "n_errors": n_err,
        "n_warnings": n_warn,
        "n_hints": n_hint,
        "n_critical": n_err,  # compat: críticos = errores
        "by_code": dict(by_code.most_common(20)),
        "by_severity": dict(by_sev.most_common()),
        "top_errors": [
            {
                "Codigo": r.get("Codigo"),
                "Tipo": r.get("Tipo"),
                "ID_CYMDIST": r.get("ID_CYMDIST"),
                "Severidad": r.get("Severidad"),
                "Mensaje": (r.get("Mensaje") or "")[:180],
            }
            for r in problems[:40]
        ],
        "ready_model": len(problems) == 0,
    }


def run_network_diagnostic(settings=None, suffix=""):
    """Ejecuta NetworkDiagnostic del alimentador activo y escribe CSV/JSON canónicos.

    Independiente de §3 SpotLoad y §4 flujos de escenario. No requiere cabecera.
    """
    from analysis.run_network_diagnostic import main as diag_main

    s = settings or load_settings()
    _pause_gui(s)
    prev = os.environ.get("RECYM_DIAG_SUFFIX")
    try:
        if suffix:
            os.environ["RECYM_DIAG_SUFFIX"] = str(suffix)
        elif "RECYM_DIAG_SUFFIX" in os.environ:
            del os.environ["RECYM_DIAG_SUFFIX"]
        diag_main()
    finally:
        if prev is None:
            os.environ.pop("RECYM_DIAG_SUFFIX", None)
        else:
            os.environ["RECYM_DIAG_SUFFIX"] = prev

    tag = ("_" + suffix) if suffix else ""
    csv_path = output_path(s, "diagnostics", "cymdist_diagnostic_errors%s.csv" % tag)
    rows = _read_csv(csv_path)
    summary = _diag_summary_from_rows(rows, s, phase=suffix or "before")
    summary["csv"] = csv_path
    return {"ok": True, "summary": summary, "rows": rows, "csv": csv_path}


def run_system_network_diagnostic(settings=None, limit=0, network_ids=None):
    """Diagnóstico de TODAS las redes de la BD (sistema de distribución).

    No depende de §1 cabecera, §2 EA/Pot, §3 cargas nuevas ni §4 flujos.
    Usa redes + equipos ya en la MDB. Clasifica por tipo/código de error.
    """
    from analysis.run_system_network_diagnostic import run_system_diagnostic

    s = settings or load_settings()
    _pause_gui(s)
    result = run_system_diagnostic(
        s, network_ids=network_ids, limit=int(limit or 0)
    )
    # Persistir resumen sistema en sesión (no bloquea gate por-feeder)
    try:
        sess = load_session(s)
        sess["system_diagnostic"] = {
            "timestamp": (result.get("summary") or {}).get("timestamp"),
            "n_problems": (result.get("summary") or {}).get("n_problems"),
            "n_networks_ok": (result.get("summary") or {}).get("n_networks_ok"),
            "csv": result.get("csv"),
            "json": result.get("json"),
            "ready_model_system": (result.get("summary") or {}).get("ready_model_system"),
        }
        save_session(s, sess)
    except Exception as ex:
        print("AVISO session system_diagnostic:", ex)
    return result


def run_eld_network_diagnostic(settings=None, limit=0, network_ids=None):
    """Herramienta diagnóstica API sobre el estudio ELD.zxst (96 alimentadores).

    Misma herramienta que Análisis → Herramienta diagnóstica en la GUI.
    """
    from analysis.run_eld_diagnostic import run_eld_diagnostic

    s = settings or load_settings()
    _pause_gui(s)
    result = run_eld_diagnostic(
        s,
        study_path=s.get("eld_study_path"),
        limit=int(limit or 0),
        network_ids=network_ids,
    )
    try:
        sess = load_session(s)
        sess["eld_diagnostic"] = {
            "timestamp": (result.get("summary") or {}).get("timestamp"),
            "n_problems": (result.get("summary") or {}).get("n_problems"),
            "n_networks_ok": (result.get("summary") or {}).get("n_networks_ok"),
            "csv": result.get("csv"),
            "json": result.get("json"),
            "study_path": (result.get("summary") or {}).get("study_path"),
            "ready_model_eld": (result.get("summary") or {}).get("ready_model_eld"),
        }
        save_session(s, sess)
    except Exception as ex:
        print("AVISO session eld_diagnostic:", ex)
    return result


def propose_corrections(settings=None):
    """Genera correcciones_propuestas.csv desde el diagnóstico (tablas ya definidas)."""
    from pipeline.build_corrections_from_diagnostic import main as build_main

    s = settings or load_settings()
    _pause_gui(s)
    build_main()
    path = output_path(s, "diagnostics", "correcciones_propuestas.csv")
    rows = _read_csv(path)
    activos = [r for r in rows if truthy(r.get("Activo"))]
    return {
        "ok": True,
        "csv": path,
        "n_total": len(rows),
        "n_activas": len(activos),
        "n_revisar": sum(1 for r in rows if (r.get("Accion_Sugerida") or "") == "revisar"),
        "rows": rows[:200],
    }


def apply_corrections(settings=None, fix_voltages=True):
    """Aplica correcciones (CSV propuesto o hoja Correcciones) + tensiones base."""
    from pipeline.bulk_fix import main as bulk_main
    from pipeline.fix_base_voltages import ensure_base_voltages

    s = settings or load_settings()
    _pause_gui(s)
    bulk_main()
    preview = _read_csv(output_path(s, "preview_changes.csv"))
    ok_n = sum(1 for r in preview if (r.get("Estado") or "") in ("OK", "DRY_RUN"))
    err_n = sum(1 for r in preview if (r.get("Estado") or "") == "ERROR")

    volt = None
    if fix_voltages and not s.get("dry_run"):
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        a.open_study()
        volt = ensure_base_voltages(c, s, a)
        if s.get("save_after_fix", True):
            try:
                a.save_study()
            except Exception as ex:
                volt = dict(volt or {})
                volt["save_error"] = str(ex)
        try:
            a.close_study(save=False)
        except Exception:
            pass

    return {
        "ok": err_n == 0,
        "n_ok": ok_n,
        "n_error": err_n,
        "preview_csv": output_path(s, "preview_changes.csv"),
        "preview": preview[:100],
        "base_voltages": volt,
    }


def check_convergence(settings=None, run_lf=True):
    """LoadFlow (opcional) + IsValidResults → Converge SI/NO."""
    s = settings or load_settings()
    result = {
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "converge": None,
        "loadflow": None,
        "status": "ok",
    }
    if s.get("dry_run"):
        result["converge"] = "DRY_RUN"
        result["status"] = "dry_run"
        return result

    lf = None
    if run_lf:
        from pipeline.run_load_flow import run_load_flow
        # Flujo de calidad del modelo: sin escenario de SpotLoad §3
        lf = run_load_flow(s, scenario=None)
        result["loadflow"] = {
            "status": lf.get("status"),
            "engine": lf.get("engine"),
            "error": lf.get("error"),
            "topo": lf.get("topo"),
        }
        if lf.get("status") not in ("ok", "dry_run"):
            result["converge"] = "NO"
            result["status"] = "lf_error"
            result["error"] = lf.get("error")
            _persist_gate(s, result)
            return result

    _pause_gui(s)
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    try:
        valid = c.sim.IsValidResults(str(s.get("network_id")), c.enums.SimulationType.LoadFlow)
        result["converge"] = "SI" if valid else "NO"
    except Exception as ex:
        result["converge"] = "DESCONOCIDO"
        result["status"] = "check_error"
        result["error"] = str(ex)
    finally:
        try:
            a.close_study(save=False)
        except Exception:
            pass

    out = output_path(s, "diagnostics", "diagnostico_tecnico.csv")
    write_csv(out, [{
        "Utility": s.get("utility_name"),
        "Feeder": s.get("feeder_id"),
        "Escenario": "calidad_modelo",
        "Converge": result["converge"],
        "Estado": "OK" if result["converge"] == "SI" else "REVISAR",
        "Timestamp": ts(),
    }], ["Utility", "Feeder", "Escenario", "Converge", "Estado", "Timestamp"])
    result["csv"] = out
    _persist_gate(s, result)
    return result


def _persist_gate(settings, converge_result, extra=None):
    sess = load_session(settings)
    extra = extra or {}
    converge_ok = converge_result.get("converge") == "SI"
    if "ready_model" in extra:
        ready = converge_ok and bool(extra.get("ready_model"))
    elif "n_problems" in extra:
        ready = converge_ok and int(extra.get("n_problems") or 0) == 0
    else:
        ready = converge_ok
    gate = {
        "converge": converge_result.get("converge"),
        "ready": ready,
        "timestamp": ts(),
        "status": converge_result.get("status"),
    }
    gate.update(extra)
    sess["model_quality_gate"] = gate
    save_session(settings, sess)
    return gate


def get_gate_status(settings=None):
    s = settings or load_settings()
    sess = load_session(s)
    gate = sess.get("model_quality_gate") or {}
    system_diag = sess.get("system_diagnostic") or {}
    diag = output_path(s, "diagnostics", "dashboard_summary.json")
    corr = output_path(s, "diagnostics", "correcciones_propuestas.csv")
    summary = None
    if os.path.isfile(diag):
        try:
            with open(diag, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            summary = None
    corr_rows = _read_csv(corr) if os.path.isfile(corr) else []
    return {
        "ok": True,
        "gate": gate,
        "ready": bool(gate.get("ready")),
        "converge": gate.get("converge"),
        "diagnostic_summary": summary,
        "system_diagnostic": system_diag,
        "n_correcciones": len(corr_rows),
        "n_correcciones_activas": sum(1 for r in corr_rows if truthy(r.get("Activo"))),
        "paths": {
            "diagnostic_csv": output_path(s, "diagnostics", "cymdist_diagnostic_errors.csv"),
            "correcciones_csv": corr,
            "preview_csv": output_path(s, "preview_changes.csv"),
            "system_csv": system_diag.get("csv") or "",
        },
    }


def run_until_converges(settings=None, max_iters=3, skip_initial_lf=False):
    """
    Diagnostica → propone → corrige → verifica convergencia, hasta Converge=SI.

    max_iters: ciclos de corrección (default 3).
    """
    s = settings or load_settings()
    max_iters = max(1, int(max_iters or 3))
    log = []
    final = {
        "ok": False,
        "converge": "NO",
        "ready": False,
        "iterations": [],
        "feeder_id": s.get("feeder_id"),
    }

    # Paso 0: diagnóstico + intento de convergencia (ver errores presentes)
    step0 = {"iter": 0, "action": "diagnostico_inicial"}
    try:
        d0 = run_network_diagnostic(s, suffix="")
        step0["diagnostic"] = d0.get("summary")
        log.append("Diagnóstico inicial: %s msgs, problemas=%s (E=%s W=%s H=%s)" % (
            d0["summary"]["total_messages"],
            d0["summary"].get("n_problems"),
            d0["summary"].get("n_errors"),
            d0["summary"].get("n_warnings"),
            d0["summary"].get("n_hints"),
        ))
    except Exception as ex:
        step0["error"] = str(ex)
        final["iterations"].append(step0)
        final["error"] = "Fallo NetworkDiagnostic: %s" % ex
        _persist_gate(s, {"converge": "NO", "status": "diag_error"}, {"last_error": str(ex), "n_problems": -1})
        return final

    if not skip_initial_lf:
        try:
            c0 = check_convergence(s, run_lf=True)
            step0["convergence"] = {
                "converge": c0.get("converge"),
                "loadflow": c0.get("loadflow"),
                "error": c0.get("error"),
            }
            log.append("Convergencia inicial: %s" % c0.get("converge"))
            if c0.get("converge") == "SI" and d0["summary"].get("ready_model"):
                step0["done"] = True
                final["iterations"].append(step0)
                final["ok"] = True
                final["converge"] = "SI"
                final["ready"] = True
                final["log"] = log
                final["msg"] = (
                    "Modelo converge y sin Error/Warning/Hint en NetworkDiagnostic "
                    "(catálogo cymdist.cymsg completo)."
                )
                _persist_gate(s, c0, {
                    "n_problems": d0["summary"].get("n_problems"),
                    "ready_model": True,
                    "iters": 0,
                })
                return final
        except Exception as ex:
            step0["convergence_error"] = str(ex)
            log.append("AVISO convergencia inicial: %s" % ex)

    final["iterations"].append(step0)

    for i in range(1, max_iters + 1):
        step = {"iter": i, "action": "corregir_todos_y_verificar"}
        try:
            if i > 1:
                d = run_network_diagnostic(s, suffix="")
                step["diagnostic"] = d.get("summary")
            else:
                step["diagnostic"] = d0.get("summary")

            prop = propose_corrections(s)
            step["proposed"] = {
                "n_total": prop.get("n_total"),
                "n_activas": prop.get("n_activas"),
                "n_revisar": prop.get("n_revisar"),
                "csv": prop.get("csv"),
            }
            log.append("Iter %s: %s correcciones activas / %s total" % (
                i, prop.get("n_activas"), prop.get("n_total")))

            if prop.get("n_activas"):
                applied = apply_corrections(s, fix_voltages=True)
                step["applied"] = {
                    "ok": applied.get("ok"),
                    "n_ok": applied.get("n_ok"),
                    "n_error": applied.get("n_error"),
                    "base_voltages": applied.get("base_voltages"),
                }
                log.append("Iter %s: aplicadas OK=%s ERR=%s" % (
                    i, applied.get("n_ok"), applied.get("n_error")))
            else:
                step["note"] = (
                    "Sin correcciones auto-aplicables; quedan filas 'revisar' "
                    "segun manual CYME o falta biblioteca de equipos."
                )

            d_after = run_network_diagnostic(s, suffix="after")
            step["diagnostic_after"] = d_after.get("summary")

            conv = check_convergence(s, run_lf=True)
            step["convergence"] = {
                "converge": conv.get("converge"),
                "loadflow": conv.get("loadflow"),
                "error": conv.get("error"),
            }
            n_prob = (d_after.get("summary") or {}).get("n_problems") or 0
            ready_m = bool((d_after.get("summary") or {}).get("ready_model"))
            log.append("Iter %s: converge=%s problemas_after=%s" % (
                i, conv.get("converge"), n_prob))

            if conv.get("converge") == "SI" and ready_m:
                step["done"] = True
                final["iterations"].append(step)
                final["ok"] = True
                final["converge"] = "SI"
                final["ready"] = True
                final["log"] = log
                final["msg"] = (
                    "Modelo limpio (0 Error/Warning/Hint) y converge tras %s ciclo(s)."
                    % i
                )
                _persist_gate(s, conv, {
                    "n_problems": n_prob,
                    "ready_model": True,
                    "iters": i,
                })
                return final

            final["iterations"].append(step)
            # Si solo quedan 'revisar' y ya no hay activas, no tiene sentido iterar más
            if not prop.get("n_activas") and n_prob > 0:
                log.append("Stop: quedan problemas sin auto-fix (revisar manual).")
                break
        except Exception as ex:
            step["error"] = str(ex)
            final["iterations"].append(step)
            log.append("ERROR iter %s: %s" % (i, ex))
            final["error"] = str(ex)
            break

    last_conv = "NO"
    last_prob = None
    for it in reversed(final["iterations"]):
        c = (it.get("convergence") or {}).get("converge")
        if c and last_conv == "NO":
            last_conv = c
        da = it.get("diagnostic_after") or it.get("diagnostic") or {}
        if last_prob is None and da.get("n_problems") is not None:
            last_prob = da.get("n_problems")
    final["converge"] = last_conv
    final["ready"] = False
    final["log"] = log
    final["msg"] = (
        "No se limpio el diagnostico (Error/Warning/Hint) y/o no converge en %s ciclo(s). "
        "Revise correcciones Accion=revisar y el catalogo cymdist.cymsg."
        % max_iters
    )
    _persist_gate(s, {"converge": last_conv, "status": "max_iters"}, {
        "iters": max_iters,
        "n_problems": last_prob,
        "ready_model": False,
        "last_error": final.get("error"),
    })
    return final
