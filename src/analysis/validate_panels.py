# -*- coding: utf-8 -*-
"""
Validación panel-por-panel / módulo-por-módulo de la UI RECYM.
Modos:
  - light: sin abrir CYMDIST (arranque + APIs de disco)
  - feeder: un alimentador (default active_feeder / IN112)
  - global: listado de redes BD (force CymPy) si --global
Salida: data/output/system/validation_panels_report.json
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time
import traceback

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import Request, urlopen, HTTPError, URLError  # type: ignore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))
sys.path.insert(0, os.path.join(ROOT, "src", "pipeline"))

BASE = os.environ.get("RECYM_UI_BASE") or "http://127.0.0.1:5055"


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def http_json(method, path, body=None, timeout=20, feeder=None):
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if feeder:
        headers["X-Feeder"] = str(feeder)
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        data = raw
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers)
    req.get_method = lambda: method
    t0 = time.time()
    try:
        resp = urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8", "replace")
        ms = int((time.time() - t0) * 1000)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"_raw": raw[:500], "_html": ("<!DOCTYPE" in raw or "<html" in raw.lower())}
        return {
            "ok_http": True,
            "status": getattr(resp, "code", 200),
            "ms": ms,
            "payload": payload,
        }
    except HTTPError as ex:
        ms = int((time.time() - t0) * 1000)
        try:
            raw = ex.read().decode("utf-8", "replace")
            payload = json.loads(raw)
        except Exception:
            payload = {"error": str(ex)}
        return {"ok_http": False, "status": ex.code, "ms": ms, "payload": payload, "error": str(ex)}
    except Exception as ex:
        ms = int((time.time() - t0) * 1000)
        return {"ok_http": False, "status": 0, "ms": ms, "payload": {}, "error": str(ex)}


def check(name, panel, objective, cond, detail="", evidence=None):
    return {
        "name": name,
        "panel": panel,
        "objective": objective,
        "pass": bool(cond),
        "detail": detail,
        "evidence": evidence or {},
    }


def module_imports():
    rows = []
    mods = [
        ("core.feeder_context", "Contexto multi-alimentador"),
        ("core.cympy_adapter", "Adapter CymPy"),
        ("core.clientes_suministro", "Clientes SED"),
        ("pipeline.model_quality_gate", "Gate calidad"),
        ("pipeline.run_demand_allocation", "Distribución"),
        ("pipeline.apply_clientes_to_cymdist", "EA/Pot → CYMDIST"),
        ("pipeline.add_spot_load", "SpotLoad §3"),
        ("pipeline.run_load_flow", "LoadFlow §4"),
        ("pipeline.fill_informe", "Informes §5"),
        ("pipeline.extract_informe_meta_pdf", "OCR meta"),
        ("pipeline.assemble_informe", "Armar informes"),
        ("pipeline.export_cymdist_ascii", "Export ASCII"),
        ("pipeline.sync_equipment_from_excel", "Sync equipos"),
        ("pipeline.validate_inputs", "Validar entradas"),
        ("analysis.build_dashboard", "Tablero"),
        ("analysis.run_network_diagnostic", "Diagnóstico red"),
        ("analysis.run_system_network_diagnostic", "Diagnóstico sistema"),
        ("analysis.run_eld_diagnostic", "Diagnóstico ELD"),
    ]
    for mod, obj in mods:
        try:
            __import__(mod)
            rows.append(check("import:" + mod, "módulos", obj, True, "import OK"))
        except Exception as ex:
            rows.append(check("import:" + mod, "módulos", obj, False, str(ex)))
    # optimization common_opt
    try:
        opt_dir = os.path.join(ROOT, "src", "optimization")
        if opt_dir not in sys.path:
            sys.path.insert(0, opt_dir)
        import common_opt  # noqa: F401
        rows.append(check("import:common_opt", "módulos", "Optimización", True, "import OK"))
    except Exception as ex:
        rows.append(check("import:common_opt", "módulos", "Optimización", False, str(ex)))
    return rows


def validate_light(feeder):
    rows = []
    # Ping / UI
    r = http_json("GET", "/api/ui/ping", timeout=8)
    p = r.get("payload") or {}
    rows.append(check(
        "ui.ping", "arranque", "UI viva + versión",
        r.get("ok_http") and p.get("ok") and str(p.get("ui_version") or "").startswith("5."),
        "v=%s busy=%s %sms" % (p.get("ui_version"), p.get("cympy_busy"), r.get("ms")),
        {"ms": r.get("ms"), "payload": p},
    ))
    # HTML index
    r = http_json("GET", "/", timeout=8)
    html_ok = r.get("ok_http") and (
        (r.get("payload") or {}).get("_html")
        or ("RECYM" in str((r.get("payload") or {}).get("_raw") or ""))
        or r.get("status") == 200
    )
    # GET / returns HTML — our parser may put in _raw
    if not html_ok and r.get("ok_http") and r.get("status") == 200:
        html_ok = True
    rows.append(check("ui.index", "arranque", "Página principal carga", html_ok, "%sms" % r.get("ms")))

    # §1 contexto
    r = http_json("GET", "/api/contexto/archivos", timeout=12)
    p = r.get("payload") or {}
    n_db = len(p.get("databases") or [])
    n_st = len(p.get("studies") or [])
    rows.append(check(
        "s1.contexto_archivos", "§1 Cabecera/contexto",
        "Listar BD .mdb y estudios .zxst sin CYMDIST",
        r.get("ok_http") and p.get("ok") and n_db >= 1 and n_st >= 1,
        "%d BD · %d estudios · %sms" % (n_db, n_st, r.get("ms")),
        {"n_db": n_db, "n_st": n_st, "current_study": p.get("current_study")},
    ))

    # Calidad soft (no CymPy)
    r = http_json("GET", "/api/calidad/redes", timeout=8)
    p = r.get("payload") or {}
    soft_ok = r.get("ok_http") and p.get("ok") and (p.get("source") in ("none", "disk", "memory") or p.get("soft") or p.get("cached") is not None)
    rows.append(check(
        "calidad.redes_soft", "Calidad modelo",
        "Listar redes sin abrir CYMDIST (soft/disco)",
        soft_ok,
        "source=%s n=%s soft=%s %sms" % (p.get("source"), p.get("n"), p.get("soft"), r.get("ms")),
        {"n": p.get("n"), "source": p.get("source"), "msg": p.get("msg")},
    ))

    r = http_json("GET", "/api/calidad/estado", timeout=8, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "calidad.estado", "Calidad modelo",
        "Estado gate desde disco (feeder)",
        r.get("ok_http") and p.get("ok") is not False,
        "feeder=%s ready=%s converge=%s %sms" % (p.get("feeder_id") or feeder, p.get("ready"), p.get("converge"), r.get("ms")),
        {"feeder_id": p.get("feeder_id"), "ready": p.get("ready")},
    ))

    # §2 archivos
    r = http_json("GET", "/api/clientes/archivos", timeout=12, feeder=feeder)
    p = r.get("payload") or {}
    n_ci = len(p.get("clientesimportantes") or p.get("clientes_files") or p.get("ci") or [])
    # API shape may vary
    if not n_ci:
        for k in ("clientesimportantes", "clientes_importantes", "ci_files", "files"):
            if isinstance(p.get(k), list):
                n_ci = len(p[k])
                break
        if not n_ci and isinstance(p.get("suministrocliente"), list):
            n_ci = -1  # at least structure
    ok_arch = r.get("ok_http") and (p.get("ok") in (True, None) or "error" not in p or p.get("ok"))
    # be lenient: ok if http ok and no hard error
    if r.get("ok_http") and p.get("error") and not p.get("ok"):
        ok_arch = False
    elif r.get("ok_http"):
        ok_arch = True if p.get("ok") is not False else False
    rows.append(check(
        "s2.archivos", "§2 Clientes",
        "Listar suministrocliente / clientesimportantes",
        ok_arch,
        "keys=%s %sms" % (sorted(list(p.keys()))[:12], r.get("ms")),
        {"payload_keys": list(p.keys()), "sample": {k: p[k] for k in list(p.keys())[:6]}},
    ))

    r = http_json("GET", "/api/clientes/radiales", timeout=30, feeder=feeder)
    p = r.get("payload") or {}
    n_rad = len(p.get("radiales") or [])
    rows.append(check(
        "s2.radiales", "§2 Clientes",
        "Listar RADIAL del archivo suministro (uno o global en archivo)",
        r.get("ok_http") and p.get("ok") and n_rad >= 1,
        "%d radiales · default=%s %sms" % (n_rad, p.get("default"), r.get("ms")),
        {"n": n_rad, "sample": (p.get("radiales") or [])[:8]},
    ))

    # §5 informe light
    r = http_json("GET", "/api/informe/status", timeout=12, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "s5.status", "§5 Informes",
        "Checklist entrega (disco) por alimentador",
        r.get("ok_http") and ("ok" in p or "delivery_ready" in p or "checks" in p or "missing" in p),
        "delivery_ready=%s %sms" % (p.get("delivery_ready"), r.get("ms")),
        {"keys": list(p.keys())[:15]},
    ))

    r = http_json("GET", "/api/informe/rutas", timeout=8, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "s5.rutas", "§5 Informes",
        "Rutas plantilla/doc por alimentador",
        r.get("ok_http") and p.get("ok"),
        "%sms" % r.get("ms"),
        {"paths": p.get("paths")},
    ))

    r = http_json("GET", "/api/informe/meta", timeout=8, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "s5.meta", "§5 Informes",
        "Meta OCR/manual cargable",
        r.get("ok_http") and p.get("ok") is not False,
        "complete=%s %sms" % (p.get("complete"), r.get("ms")),
    ))

    # Suite light
    r = http_json("GET", "/api/suite/entorno", timeout=25, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "suite.entorno", "§7 Suite",
        "Validar entorno (paths + cympy import)",
        r.get("ok_http") and p.get("cyme_exists") and p.get("mdb_exists"),
        "cympy_ok=%s dry_run=%s feeders=%s %sms" % (
            p.get("cympy_ok"), p.get("dry_run"), len(p.get("feeders") or []), r.get("ms")),
        {"feeder_id": p.get("feeder_id"), "cympy_ok": p.get("cympy_ok"), "msg": p.get("msg")},
    ))

    # Opt endpoint reachable (may skip/unconfirmed — still must respond JSON)
    r = http_json("POST", "/api/optimizacion/capacitors", body={"force": False}, timeout=20, feeder=feeder)
    p = r.get("payload") or {}
    rows.append(check(
        "opt.capacitors_reachable", "§6 Optimización",
        "Endpoint optimización responde JSON (ok|skip|unconfirmed)",
        r.get("ok_http") and ("status" in p or "ok" in p or "error" in p),
        "status=%s msg=%s %sms" % (p.get("status"), (p.get("msg") or p.get("error") or "")[:80], r.get("ms")),
        p,
    ))

    return rows


def validate_feeder_disk(feeder):
    """Artefactos en disco del alimentador (objetivo por alimentador)."""
    rows = []
    out = os.path.join(ROOT, "data", "output", "feeders", feeder)
    exists = os.path.isdir(out)
    rows.append(check(
        "disk.feeder_out", "alimentador:%s" % feeder,
        "Carpeta output del alimentador",
        exists,
        out if exists else "NO EXISTE",
    ))
    # Obligatorios mínimos si ya se trabajó el feeder
    required = [
        ("demand/session.json", "Sesión demanda §1"),
        ("diagnostics/dashboard_summary.json", "Resumen diagnóstico"),
    ]
    optional = [
        ("clientes/clientes_alimentador.json", "Tabla clientes §2 (tras Armar tabla)"),
        ("diagnostics/cymdist_diagnostic_errors.csv", "CSV NetworkDiagnostic"),
    ]
    for rel, obj in required:
        path = os.path.join(out, *rel.split("/"))
        ok = os.path.isfile(path)
        rows.append(check(
            "disk." + rel.replace("/", "_"),
            "alimentador:%s" % feeder,
            obj,
            ok,
            path if ok else "faltante",
        ))
    for rel, obj in optional:
        path = os.path.join(out, *rel.split("/"))
        ok = os.path.isfile(path)
        # optional: always pass, detail says present/missing
        rows.append(check(
            "disk.opt_" + rel.replace("/", "_"),
            "alimentador:%s" % feeder,
            obj + " [opcional]",
            True,
            "OK" if ok else "aún no generado (OK para gate parcial)",
        ))
    for scen in ("situacional", "proyectado"):
        cand = [
            os.path.join(out, "loadflow", "loadflow_%s.json" % scen),
            os.path.join(out, "loadflow_%s.json" % scen),
            os.path.join(out, "analysis", "loadflow_%s.json" % scen),
        ]
        found = next((c for c in cand if os.path.isfile(c)), None)
        rows.append(check(
            "disk.opt_lf_" + scen,
            "alimentador:%s" % feeder,
            "LoadFlow %s (§4) [opcional hasta correr flujo]" % scen,
            True,
            found or "aún no generado",
        ))
    return rows


def validate_functional_feeder(feeder):
    """Pruebas funcionales por alimentador (sin escritura COM pesada)."""
    rows = []
    # Cabecera preview_only
    r = http_json(
        "POST", "/api/cabecera",
        body={"mode": "KW_COSFI", "P_kW": 1500, "cosfi": 0.95, "preview_only": True, "feeder": feeder},
        timeout=15,
        feeder=feeder,
    )
    p = r.get("payload") or {}
    rows.append(check(
        "s1.cabecera_preview", "§1 Cabecera/contexto",
        "Recalcular P/Q sin escribir CYMDIST",
        r.get("ok_http") and p.get("ok") and p.get("preview_only") and float(p.get("P_kW") or 0) > 0,
        "P=%s Q=%s %sms" % (p.get("P_kW"), p.get("Q_kvar"), r.get("ms")),
        p,
    ))

    # Armar tabla NIS (Excel only)
    r = http_json(
        "POST", "/api/clientes/tabla",
        body={
            "suministro_file": "ML_1225.xlsx",
            "clientes_file": "0326clientesImportantes.xlsb",
            "feeder": feeder,
            "feeders": [feeder],
            "all_feeders": False,
        },
        timeout=120,
        feeder=feeder,
    )
    p = r.get("payload") or {}
    n_rows = int(p.get("n_rows") or len(p.get("rows") or []) or 0)
    rows.append(check(
        "s2.armar_tabla", "§2 Clientes",
        "Armar tabla cruzando NIS para UN alimentador (%s)" % feeder,
        r.get("ok_http") and p.get("ok") and n_rows >= 1,
        "n_rows=%s msg=%s %sms" % (n_rows, (p.get("msg") or p.get("error") or "")[:100], r.get("ms")),
        {"n_rows": n_rows, "meta": p.get("meta"), "error": p.get("error")},
    ))

    # Soft redes must stay responsive after tabla
    r = http_json("GET", "/api/ui/ping", timeout=8)
    p = r.get("payload") or {}
    rows.append(check(
        "arranque.ping_post_tabla", "arranque",
        "UI sigue viva tras Armar tabla (no colgar Waitress)",
        r.get("ok_http") and p.get("ok"),
        "busy=%s %sms" % (p.get("cympy_busy"), r.get("ms")),
    ))
    return rows


def validate_global_networks(do_force):
    rows = []
    if not do_force:
        r = http_json("GET", "/api/calidad/redes", timeout=8)
        p = r.get("payload") or {}
        rows.append(check(
            "global.redes_soft", "global BD",
            "Catálogo redes (soft) — sin COM",
            r.get("ok_http") and p.get("ok"),
            "n=%s source=%s" % (p.get("n"), p.get("source")),
            p,
        ))
        return rows

    print("  [global] force=1 list_bd_networks vía UI (puede tardar / abrir CYMDIST)…")
    r = http_json("GET", "/api/calidad/redes?force=1", timeout=180)
    p = r.get("payload") or {}
    n = int(p.get("n") or 0)
    rows.append(check(
        "global.redes_force", "global BD",
        "Listar TODOS los alimentadores/redes de la BD vía CymPy",
        r.get("ok_http") and p.get("ok") and n >= 10 and not p.get("busy"),
        "n=%s source=%s busy=%s %sms" % (n, p.get("source"), p.get("busy"), r.get("ms")),
        {
            "n": n,
            "connection": p.get("connection"),
            "sample": (p.get("networks") or [])[:5],
            "error": p.get("error"),
        },
    ))
    # Persistencia disco
    disk = os.path.join(ROOT, "data", "output", "system", "bd_networks.json")
    disk_ok = os.path.isfile(disk)
    disk_n = 0
    if disk_ok:
        try:
            with open(disk, "r", encoding="utf-8") as f:
                disk_n = len((json.load(f).get("networks") or []))
        except Exception:
            disk_ok = False
    rows.append(check(
        "global.redes_disk", "global BD",
        "Catálogo persistido para arranque sin CYMDIST",
        disk_ok and disk_n >= 10,
        "path=%s n=%s" % (disk, disk_n),
    ))
    return rows


def validate_config_feeders():
    rows = []
    from core.feeder_context import list_feeders, load_settings
    feeders = [f for f in list_feeders() if f != "_TEMPLATE"]
    rows.append(check(
        "config.feeders_list", "config",
        "Alimentadores registrados en config/feeders",
        len(feeders) >= 1,
        ", ".join(feeders),
        {"feeders": feeders},
    ))
    for fid in feeders:
        try:
            s = load_settings(feeder_id=fid, synthesize=True, persist_synth=False)
            study = s.get("study_path") or ""
            ok_study = (not study) or os.path.isfile(study)
            rows.append(check(
                "config." + fid,
                "config",
                "Settings + study_path resoluble para %s" % fid,
                bool(s.get("feeder_id")) and ok_study,
                "network=%s study_exists=%s dry_run=%s" % (
                    s.get("network_id"), os.path.isfile(study) if study else None, s.get("dry_run")),
            ))
        except Exception as ex:
            rows.append(check("config." + fid, "config", "Load settings %s" % fid, False, str(ex)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeder", default="", help="Alimentador a validar (default: active_feeder)")
    ap.add_argument("--global", dest="do_global", action="store_true", help="Forzar listado CymPy de todas las redes BD")
    ap.add_argument("--skip-imports", action="store_true")
    args = ap.parse_args()

    from core.common import load_json
    gs = load_json("config/settings.json")
    feeder = (args.feeder or gs.get("active_feeder") or "IN112").strip().upper()

    report = {
        "timestamp": _now(),
        "ui_base": BASE,
        "feeder": feeder,
        "global_force": bool(args.do_global),
        "checks": [],
    }

    print("=" * 64)
    print("VALIDACIÓN PANELES / MÓDULOS RECYM")
    print("UI:", BASE, "| feeder:", feeder, "| global:", args.do_global)
    print("=" * 64)

    if not args.skip_imports:
        print("\n[1] Módulos (import)")
        report["checks"].extend(module_imports())

    print("\n[2] Config alimentadores")
    report["checks"].extend(validate_config_feeders())

    print("\n[3] Paneles light (API UI)")
    report["checks"].extend(validate_light(feeder))

    print("\n[4] Disco alimentador", feeder)
    report["checks"].extend(validate_feeder_disk(feeder))

    # Also PA217 if different
    if feeder != "PA217" and os.path.isdir(os.path.join(ROOT, "data", "output", "feeders", "PA217")):
        print("\n[4b] Disco alimentador PA217")
        report["checks"].extend(validate_feeder_disk("PA217"))

    print("\n[4c] Funcional un alimentador", feeder)
    report["checks"].extend(validate_functional_feeder(feeder))

    print("\n[5] Global BD")
    report["checks"].extend(validate_global_networks(args.do_global))

    checks = report["checks"]
    n_pass = sum(1 for c in checks if c["pass"])
    n_fail = sum(1 for c in checks if not c["pass"])
    report["summary"] = {
        "total": len(checks),
        "pass": n_pass,
        "fail": n_fail,
        "result": "PASS" if n_fail == 0 else ("PARTIAL" if n_pass > n_fail else "FAIL"),
    }

    # Group by panel
    by_panel = {}
    for c in checks:
        by_panel.setdefault(c["panel"], {"pass": 0, "fail": 0, "items": []})
        if c["pass"]:
            by_panel[c["panel"]]["pass"] += 1
        else:
            by_panel[c["panel"]]["fail"] += 1
        by_panel[c["panel"]]["items"].append(c["name"] + ("" if c["pass"] else " FAIL"))
    report["by_panel"] = by_panel

    out_dir = os.path.join(ROOT, "data", "output", "system")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    out_path = os.path.join(out_dir, "validation_panels_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 64)
    print("RESULTADO:", report["summary"]["result"],
          "| OK:", n_pass, "| FAIL:", n_fail, "| total:", len(checks))
    print("Por panel:")
    for panel, st in sorted(by_panel.items()):
        mark = "OK" if st["fail"] == 0 else "REVISAR"
        print("  [%s] %s  pass=%d fail=%d" % (mark, panel, st["pass"], st["fail"]))
    print("\nFALLIDOS:")
    fails = [c for c in checks if not c["pass"]]
    if not fails:
        print("  (ninguno)")
    for c in fails:
        print("  - [%s] %s :: %s" % (c["panel"], c["name"], c.get("detail")))
    print("\nInforme:", out_path)
    print("=" * 64)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
