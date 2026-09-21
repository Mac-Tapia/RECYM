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
from core.feeder_context import load_settings, output_path, list_feeders, feeder_config_path
from pipeline.run_demand_allocation import load_session, save_session

# Listo solo si no quedan Error / Warning / Hint del NetworkDiagnostic
PROBLEM_SEVERITIES_LOCAL = ("Error", "Warning", "Hint")

_NETWORKS_CACHE = {"ts": 0, "items": []}

# CymPy/COM no es reentrante: a lo sumo 1 operación pesada a la vez.
# Las APIs ligeras (ping, listas en disco) NO deben esperar este lock.
import threading
_CYMPY_LOCK = threading.RLock()
_CYMPY_HOLDER = {"who": None, "since": 0.0, "depth": 0}


def cympy_busy():
    """True si hay una operación CYMDIST en curso (para responder 503 rápido)."""
    return bool(_CYMPY_HOLDER.get("depth"))


def cympy_holder():
    return dict(_CYMPY_HOLDER)


def with_cympy_lock(who, fn, timeout_sec=0.5):
    """Ejecuta fn bajo lock COM. Si ocupado, retorna dict busy sin bloquear el worker."""
    import time
    # RLock.acquire(blocking, timeout) disponible en Py3.2+
    got = _CYMPY_LOCK.acquire(True, float(timeout_sec))
    if not got:
        return {
            "ok": False,
            "busy": True,
            "error": "CYMDIST ocupado (%s). Espere o pulse Restablecer." % (
                _CYMPY_HOLDER.get("who") or "otra operación"
            ),
            "holder": cympy_holder(),
        }
    _CYMPY_HOLDER["who"] = who or _CYMPY_HOLDER.get("who")
    _CYMPY_HOLDER["since"] = _CYMPY_HOLDER.get("since") or time.time()
    _CYMPY_HOLDER["depth"] = int(_CYMPY_HOLDER.get("depth") or 0) + 1
    try:
        return fn()
    finally:
        _CYMPY_HOLDER["depth"] = max(0, int(_CYMPY_HOLDER.get("depth") or 1) - 1)
        if not _CYMPY_HOLDER["depth"]:
            _CYMPY_HOLDER["who"] = None
            _CYMPY_HOLDER["since"] = 0.0
        try:
            _CYMPY_LOCK.release()
        except Exception:
            pass


def _networks_disk_path():
    """Catálogo de redes en disco (la UI arranca sin abrir CYMDIST)."""
    try:
        from core.common import p
        return p("data", "output", "system", "bd_networks.json")
    except Exception:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(root, "data", "output", "system", "bd_networks.json")


def _load_networks_disk():
    path = _networks_disk_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("networks") or []
        if items:
            return items
    except Exception:
        pass
    return None


def _save_networks_disk(items, connection=""):
    path = _networks_disk_path()
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "connection": connection,
                "n": len(items or []),
                "networks": items or [],
                "ts": ts(),
            }, f, indent=2, ensure_ascii=False)
    except Exception as ex:
        print("AVISO save bd_networks:", ex)


def clear_networks_cache():
    """Limpia caché de redes BD (para Restablecer UI). No borra el catálogo en disco."""
    _NETWORKS_CACHE["ts"] = 0
    _NETWORKS_CACHE["items"] = []
    return True


def feeder_id_from_network(network_id):
    """NET_2030_179_PA217 → PA217; NET_2030_156_SL141 → SL141."""
    parts = str(network_id or "").split("_")
    return parts[-1] if parts else str(network_id or "")


def list_bd_networks(settings=None, force=False, cache_ttl_sec=300, soft=False):
    """Lista redes de la BD CYMDIST (alimentadores del estudio compartido).

    soft=True  → solo memoria/disco (NO abre CYMDIST). Arranque UI instantáneo.
    force=True → fuerza lectura vía CymPy/COM y actualiza disco.
    Returns: {ok, connection, n, networks:[{network_id, feeder_id, has_config}]}
    """
    import time

    s = settings or load_settings()
    now = time.time()
    conn = s.get("database_connection_name") or ""

    # 1) memoria
    if (
        not force
        and _NETWORKS_CACHE["items"]
        and (now - float(_NETWORKS_CACHE["ts"] or 0)) < float(cache_ttl_sec)
    ):
        return {
            "ok": True,
            "cached": True,
            "source": "memory",
            "connection": conn,
            "n": len(_NETWORKS_CACHE["items"]),
            "networks": list(_NETWORKS_CACHE["items"]),
        }

    # 2) disco (sin CYMDIST)
    if not force:
        disk_items = _load_networks_disk()
        if disk_items:
            _NETWORKS_CACHE["ts"] = now
            _NETWORKS_CACHE["items"] = disk_items
            return {
                "ok": True,
                "cached": True,
                "source": "disk",
                "connection": conn,
                "n": len(disk_items),
                "networks": list(disk_items),
            }
        if soft:
            return {
                "ok": True,
                "cached": False,
                "source": "none",
                "soft": True,
                "connection": conn,
                "n": 0,
                "networks": [],
                "msg": "Sin catálogo local. Pulse «Actualizar lista» (abre CYMDIST una vez).",
            }

    # 3) CymPy — bajo lock (una sola operación COM)
    def _fetch():
        _pause_gui(s)
        import cympy.db as db

        cname = s.get("database_connection_name") or "20260919"
        db.ConnectDatabaseByName(cname)
        raw = [str(n) for n in list(db.ListNetworks())]
        configured = set(list_feeders())
        items = []
        for nid in sorted(raw):
            fid = feeder_id_from_network(nid)
            items.append({
                "network_id": nid,
                "feeder_id": fid,
                "has_config": fid in configured,
                "label": "%s · %s" % (fid, nid),
            })
        _NETWORKS_CACHE["ts"] = time.time()
        _NETWORKS_CACHE["items"] = items
        _save_networks_disk(items, cname)
        return {
            "ok": True,
            "cached": False,
            "source": "cympy",
            "connection": cname,
            "n": len(items),
            "networks": items,
        }

    result = with_cympy_lock("list_bd_networks", _fetch, timeout_sec=1.0)
    return result


def resolve_selected_networks(settings, networks=None, feeders=None):
    """Resuelve selección UI → lista de network_id.

    Acepta network_ids crudos y/o códigos feeder (PA217). Si solo hay feeder,
    busca el network_id en la BD.
    """
    nets = []
    seen = set()
    for n in list(networks or []):
        n = str(n or "").strip()
        if n and n not in seen:
            seen.add(n)
            nets.append(n)
    feeder_codes = [str(f or "").strip().upper() for f in (feeders or []) if str(f or "").strip()]
    if feeder_codes:
        catalog = list_bd_networks(settings)
        by_feeder = {}
        for item in catalog.get("networks") or []:
            by_feeder.setdefault(str(item.get("feeder_id") or "").upper(), []).append(item["network_id"])
        for fid in feeder_codes:
            matches = by_feeder.get(fid) or []
            if not matches:
                # Si parece un NetworkID completo, úsalo
                if fid.startswith("NET_") or "_" in fid:
                    if fid not in seen:
                        seen.add(fid)
                        nets.append(fid)
                continue
            for nid in matches:
                if nid not in seen:
                    seen.add(nid)
                    nets.append(nid)
    return nets


def run_selected_until_converges(settings=None, networks=None, feeders=None, max_iters=4):
    """Diagnostica/corrige los alimentadores seleccionados del estudio.

    - Varios o sin config RECYM: NetworkDiagnostic del subconjunto (BD).
    - Uno con config/feeders/<ID>.json: ciclo completo hasta limpio + converge.
    - Varios con config: cicla run_until_converges por cada uno.
    """
    s = settings or load_settings()
    selected = resolve_selected_networks(s, networks=networks, feeders=feeders)
    if not selected:
        return {"ok": False, "error": "Seleccione al menos un alimentador del estudio."}

    configured = set(list_feeders())
    selected_feeders = []
    for nid in selected:
        fid = feeder_id_from_network(nid)
        if fid in configured and os.path.isfile(feeder_config_path(fid)):
            if fid not in selected_feeders:
                selected_feeders.append(fid)

    # Si hay configs RECYM para los seleccionados → ciclo completo por feeder
    if selected_feeders:
        results = []
        all_ok = True
        log = []
        for fid in selected_feeders:
            log.append("--- %s ---" % fid)
            try:
                fs = load_settings(feeder_id=fid)
                one = run_until_converges(
                    fs, max_iters=int(max_iters or 4), skip_initial_lf=False
                )
                one["feeder_id"] = fid
                results.append(one)
                all_ok = all_ok and bool(one.get("ok"))
                log.extend(one.get("log") or [])
                log.append(one.get("msg") or one.get("error") or "")
            except Exception as ex:
                all_ok = False
                results.append({"ok": False, "feeder_id": fid, "error": str(ex)})
                log.append("%s ERROR: %s" % (fid, ex))
        return {
            "ok": all_ok,
            "mode": "until_clean_per_feeder",
            "selected_networks": selected,
            "selected_feeders": selected_feeders,
            "results": results,
            "log": log,
            "msg": (
                "Seleccionados OK" if all_ok else "Seleccionados con pendientes"
            ) + (": %s" % ", ".join(selected_feeders)),
            "ready": all_ok,
            "n_selected": len(selected),
        }

    # Sin config RECYM: solo diagnóstico del subconjunto en la BD
    diag = run_system_network_diagnostic(s, network_ids=selected)
    sum_ = diag.get("summary") or {}
    return {
        "ok": bool(diag.get("ok", True)) and int(sum_.get("n_problems") or 0) == 0,
        "mode": "diagnose_selected_networks",
        "selected_networks": selected,
        "selected_feeders": [feeder_id_from_network(n) for n in selected],
        "summary": sum_,
        "rows": diag.get("rows") or sum_.get("by_code_detail") or sum_.get("top_errors") or [],
        "csv": diag.get("csv") or sum_.get("csv"),
        "system_diagnostic": sum_,
        "msg": (
            "Diagnóstico de %d alimentador(es) seleccionados · problemas=%s"
            % (len(selected), sum_.get("n_problems"))
        ),
        "ready": bool(sum_.get("ready_model_system")),
        "n_selected": len(selected),
    }


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
    Respeta settings.feeder_id / network_id del request UI (no el active_feeder global).
    """
    from analysis.run_network_diagnostic import main as diag_main

    s = settings or load_settings()
    _pause_gui(s)
    prev_suf = os.environ.get("RECYM_DIAG_SUFFIX")
    prev_feeder = os.environ.get("RECYM_FEEDER")
    try:
        os.environ["RECYM_FEEDER"] = str(s.get("feeder_id") or "")
        if suffix:
            os.environ["RECYM_DIAG_SUFFIX"] = str(suffix)
        elif "RECYM_DIAG_SUFFIX" in os.environ:
            del os.environ["RECYM_DIAG_SUFFIX"]
        diag_main(s)
    finally:
        if prev_suf is None:
            os.environ.pop("RECYM_DIAG_SUFFIX", None)
        else:
            os.environ["RECYM_DIAG_SUFFIX"] = prev_suf
        if prev_feeder is None:
            os.environ.pop("RECYM_FEEDER", None)
        else:
            os.environ["RECYM_FEEDER"] = prev_feeder

    tag = ("_" + suffix) if suffix else ""
    csv_path = output_path(s, "diagnostics", "cymdist_diagnostic_errors%s.csv" % tag)
    rows = _read_csv(csv_path)
    summary = _diag_summary_from_rows(rows, s, phase=suffix or "before")
    summary["csv"] = csv_path
    summary["config_synthesized"] = bool(s.get("config_synthesized"))
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
    from pipeline.diagnostic_registry import load_catalog

    s = settings or load_settings()
    load_catalog(force=True)  # recargar catálogo (p.ej. 480067 recién agregado)
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
    """LoadFlow (opcional) + resultados validos → Converge SI/NO.

    Con motor COM, IsValidResults de CymPy no ve la sesion Cyme (procesos distintos):
    se usa KWTOT numerico del topo COM. Con CymPy, IsValidResults.
    """
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

    def _topo_numeric_ok(topo):
        if not topo:
            return False
        raw = topo.get("KWTOT")
        if raw is None:
            return False
        sraw = str(raw)
        if sraw.startswith("ERR:") or "Invalid Simulation" in sraw:
            return False
        try:
            float(sraw.replace(",", "."))
            return True
        except Exception:
            return False

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
            "calculation_method": lf.get("calculation_method"),
        }
        if lf.get("status") not in ("ok", "dry_run"):
            result["converge"] = "NO"
            result["status"] = "lf_error"
            result["error"] = lf.get("error")
            _persist_gate(s, result)
            return result
        # COM: resultados viven en el proceso Cyme ya cerrado → confiar en topo
        if (lf.get("engine") or "").upper() == "COM":
            if _topo_numeric_ok(lf.get("topo") or {}):
                result["converge"] = "SI"
                result["status"] = "ok_com_topo"
            else:
                result["converge"] = "NO"
                result["status"] = "com_invalid_topo"
                result["error"] = lf.get("error") or "LoadFlow COM sin KWTOT numerico"
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
        "feeder_id": s.get("feeder_id") or (summary or {}).get("feeder_id"),
        "network_id": s.get("network_id") or (summary or {}).get("network_id"),
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


def isolate_feeder_sources(settings=None):
    """Deja SOLO la red del alimentador activo para el ciclo de calidad.

    Los .zxst Electro Dunas traen muchas redes (10 kV + 22.9 kV). NetworkDiagnostic
    ve fuentes cruzadas (p.ej. 480067). UnloadNetworks / LoadNetwork(NoDependencies)
    no aíslan: CYME vuelve a traer las 15 redes. DeleteNetwork sí deja 1 red.

    IMPORTANTE: nunca Guardar el .zxst de producción tras DeleteNetwork.
    Se escribe una copia de trabajo y se apunta settings['study_path'] a ella
    para que el resto del ciclo (diagnóstico / correcciones / LF) use 1 sola red.
    """
    s = settings or load_settings()
    if s.get("dry_run"):
        return {"ok": True, "dry_run": True, "unloaded": []}
    keep = str(s.get("network_id") or "").strip()
    if not keep:
        return {"ok": False, "error": "Sin network_id para aislar"}
    fid = str(s.get("feeder_id") or "feeder").strip() or "feeder"
    orig_path = str(s.get("study_path") or "").strip()
    if not orig_path or not os.path.isfile(orig_path):
        return {"ok": False, "error": "Sin study_path de origen para aislar"}

    # Ya estamos sobre una copia de trabajo de 1 red
    if s.get("isolated_work_study") and orig_path.lower().endswith("_isolated.zxst"):
        return {
            "ok": True,
            "method": "already_work_copy",
            "keep": keep,
            "work_path": orig_path,
            "unloaded": [],
            "n_unloaded": 0,
            "after": [keep],
        }

    work_dir = output_path(s, "diagnostics")
    try:
        os.makedirs(work_dir, exist_ok=True)
    except Exception:
        pass
    work_path = os.path.join(work_dir, "%s_isolated.zxst" % fid)

    _pause_gui(s)
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    # Abrir siempre el estudio de producción (no la copia previa)
    a.open_study(study_path=orig_path, force_backup=False)
    try:
        before = [str(n) for n in list(c.study.ListNetworks())]
        others = [n for n in before if n != keep]
        if not others:
            s["study_path_original"] = orig_path
            s["isolated_work_study"] = False
            return {
                "ok": True,
                "method": "already_isolated",
                "keep": keep,
                "before": before,
                "after": before,
                "unloaded": [],
                "n_unloaded": 0,
                "work_path": orig_path,
            }

        deleted = []
        delete_errors = []
        for o in others:
            try:
                c.study.DeleteNetwork(o)
                deleted.append(o)
            except Exception as ex_del:
                delete_errors.append("%s: %s" % (o, ex_del))
                print("AVISO DeleteNetwork", o, ex_del)

        after = [str(n) for n in list(c.study.ListNetworks())]
        if keep not in after or len(after) != 1:
            return {
                "ok": False,
                "error": "DeleteNetwork no dejó solo %s (after=%s). Errores: %s" % (
                    keep, after, "; ".join(delete_errors[:5]) or "ninguno"),
                "method": "delete_other_networks",
                "keep": keep,
                "before": before,
                "after": after,
                "unloaded": deleted,
                "n_unloaded": len(deleted),
                "delete_errors": delete_errors,
            }

        # Guardar SOLO a copia de trabajo (sin db.SaveProject)
        try:
            c.study.Save(work_path)
        except Exception:
            try:
                from cympy.enums import SaveStudyEquipmentOption
                c.study.Save(work_path, True, True, SaveStudyEquipmentOption.AllEquipments)
            except Exception as ex_save:
                return {
                    "ok": False,
                    "error": "No se pudo guardar estudio aislado: %s" % ex_save,
                    "method": "delete_other_networks",
                    "keep": keep,
                    "before": before,
                    "after": after,
                    "unloaded": deleted,
                    "n_unloaded": len(deleted),
                }

        if not os.path.isfile(work_path):
            return {
                "ok": False,
                "error": "Copia aislada no existe tras Save: %s" % work_path,
                "unloaded": deleted,
                "n_unloaded": len(deleted),
            }

        # El resto del ciclo abre esta copia (1 red). Producción intacta.
        s["study_path_original"] = orig_path
        s["study_path"] = work_path
        s["isolated_work_study"] = True
        s["skip_db_project_save"] = True

        return {
            "ok": True,
            "method": "delete_other_networks_work_copy",
            "keep": keep,
            "before": before,
            "after": after,
            "unloaded": deleted,
            "n_unloaded": len(deleted),
            "work_path": work_path,
            "orig_path": orig_path,
            "after_msg": "Estudio trabajo 1 red: %s" % work_path,
        }
    finally:
        try:
            a.close_study(save=False)
        except Exception:
            pass


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

    # Paso -1: aislar SOLO la red del alimentador (estudios multi-red 10/22.9 kV)
    try:
        iso = isolate_feeder_sources(s)
        log.append("Aislamiento redes: method=%s keep=%s unloaded=%s after=%s work=%s" % (
            iso.get("method"), iso.get("keep"), iso.get("n_unloaded"),
            iso.get("after"), iso.get("work_path") or s.get("study_path")))
        final["isolation"] = iso
        if not iso.get("ok"):
            log.append("AVISO aislamiento incompleto: %s" % (iso.get("error") or iso))
            # Sin aislamiento fiable el ciclo multi-red no puede limpiar 480067
            final["error"] = "Aislamiento de red falló: %s" % (iso.get("error") or iso.get("method"))
            final["log"] = log
            _persist_gate(s, {"converge": "NO", "status": "isolate_error"}, {
                "n_problems": -1,
                "ready_model": False,
                "last_error": final["error"],
            })
            return final
        elif s.get("isolated_work_study"):
            log.append("Ciclo usa estudio trabajo (1 red): %s" % s.get("study_path"))
    except Exception as ex:
        log.append("AVISO aislamiento redes: %s" % ex)
        final["isolation_error"] = str(ex)

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
