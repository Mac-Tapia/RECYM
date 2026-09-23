# -*- coding: utf-8 -*-
"""Pruebas robustez §3.3 Distribucion de carga (PA217 u --feeder).

Cubre:
  1) Motor COM Cymdist.LoadAllocation (evita 130013 de CymPy)
  2) Balance vs cabecera
  3) Reentrada idempotente
  4) Fallback SetValue si COM no disponible

Uso:
  .tools\\python37-win32\\python.exe -u scripts\\test_33_distribucion.py
  .tools\\python37-win32\\python.exe -u scripts\\test_33_distribucion.py --feeder PA217
"""
from __future__ import print_function
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _fail(msg):
    print("FAIL:", msg)
    return False


def _ok(msg):
    print("OK:", msg)
    return True


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    from core.feeder_context import load_settings, resolve_cymdist_binding, output_path
    from pipeline.run_demand_allocation import (
        seed_session_from_excel,
        run_load_allocation_module,
        load_session,
        save_session,
    )

    s = load_settings(argv=argv)
    sess = seed_session_from_excel(s)
    if sess.get("P_kW") in (None, ""):
        return 2 if not _fail("Sin cabecera §1 en sesion") else 2

    bind = resolve_cymdist_binding(s)
    s2 = dict(s)
    s2.update({k: bind[k] for k in ("study_path", "database_mdb", "database_connection_name")})
    s2["network_id"] = bind.get("network_id") or s.get("network_id")
    s2["skip_db_project_save"] = True
    s2["auto_backup"] = False
    # Forzar ruta robusta documentada (CymPy 130013 en esta instalacion)
    s2["loadflow_engine"] = "COM"
    s2["prefer_loadallocation_com"] = True

    results = []
    n_pass = 0

    print("=" * 60)
    print("TEST 3.3 · feeder", s2.get("feeder_id"), "· net", s2.get("network_id"))
    print("=" * 60)

    # --- T1: COM allocation ---
    print("\n[T1] COM LoadAllocation + validacion")
    t0 = time.time()
    r1 = run_load_allocation_module(s2, sess)
    wall1 = round(time.time() - t0, 2)
    method = str(r1.get("method") or "")
    val = r1.get("validation") or {}
    ok1 = bool(r1.get("allocation_ok")) and bool(val.get("ok", True))
    if "COM" not in method and "fallback" not in method and not method.startswith("cymdist_"):
        ok1 = False
    msg1 = "method=%s status=%s val=%s balance=%s wall=%.1fs timing=%s" % (
        method,
        r1.get("status"),
        val.get("ok"),
        val.get("balance_msg") or val.get("msg"),
        wall1,
        r1.get("timing"),
    )
    results.append(("T1_com", ok1, msg1))
    n_pass += 1 if ok1 else 0
    print(("PASS" if ok1 else "FAIL"), msg1)

    # --- T2: reentrada (idempotente) ---
    print("\n[T2] Reentrada 3.3 (idempotente)")
    t0 = time.time()
    r2 = run_load_allocation_module(s2, load_session(s))
    wall2 = round(time.time() - t0, 2)
    val2 = r2.get("validation") or {}
    ok2 = bool(r2.get("allocation_ok")) and bool(val2.get("ok", True))
    # Segunda pasada no debe ser mucho peor que 90s (COM reopen)
    if wall2 > 90:
        ok2 = False
    msg2 = "method=%s status=%s val=%s wall=%.1fs" % (
        r2.get("method"),
        r2.get("status"),
        val2.get("ok"),
        wall2,
    )
    results.append(("T2_reentrada", ok2, msg2))
    n_pass += 1 if ok2 else 0
    print(("PASS" if ok2 else "FAIL"), msg2)

    # --- T3: invariantes cabecera ---
    print("\n[T3] Invariantes balance")
    sum_kw = float((val2.get("sum_kw") if val2.get("sum_kw") is not None else val.get("sum_kw")) or 0)
    p_head = float(sess.get("P_kW") or 0)
    delta = abs(sum_kw - p_head) / p_head * 100.0 if p_head else 999.0
    ok3 = p_head > 0 and delta <= 8.0
    msg3 = "sum_kw=%.2f cab=%.2f delta=%.2f%%" % (sum_kw, p_head, delta)
    results.append(("T3_balance", ok3, msg3))
    n_pass += 1 if ok3 else 0
    print(("PASS" if ok3 else "FAIL"), msg3)

    # --- T4: artefacto JSON ---
    print("\n[T4] Artefacto allocation_result.json")
    out = output_path(s2, "demand", "allocation_result.json")
    ok4 = os.path.isfile(out)
    if ok4:
        data = json.load(open(out, encoding="utf-8"))
        ok4 = bool(data.get("allocation_ok")) and bool(data.get("method"))
    msg4 = out if ok4 else "faltante o incompleto"
    results.append(("T4_artefacto", ok4, msg4))
    n_pass += 1 if ok4 else 0
    print(("PASS" if ok4 else "FAIL"), msg4)

    report = {
        "feeder": s2.get("feeder_id"),
        "n_pass": n_pass,
        "n_total": len(results),
        "results": [{"id": i, "ok": o, "msg": m} for i, o, m in results],
        "r1_method": r1.get("method"),
        "r1_engine": r1.get("engine") or (r1.get("com_allocation") or {}).get("engine"),
        "wall_t1": wall1,
        "wall_t2": wall2,
    }
    rep_path = output_path(s2, "demand", "test_33_report.json")
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("RESUMEN %d/%d" % (n_pass, len(results)))
    print("Reporte:", rep_path)
    print("=" * 60)
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
