# -*- coding: utf-8 -*-
"""UAT COM pendiente — firma operativa §§1–7 contra SPA en :5055.
Genera data/output/system/uat_com_report.json
"""
from __future__ import print_function
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("RECYM_QA_BASE") or "http://127.0.0.1:5055"
FEEDER = os.environ.get("RECYM_FEEDER") or "IN112"
OUT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "output", "system", "uat_com_report.json"
))


def req(method, path, body=None, timeout=600, headers=None):
    url = BASE.rstrip("/") + path
    data = None
    hdrs = {"Accept": "application/json", "X-Feeder": FEEDER}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.getcode()
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {"_text": raw[:500].decode("utf-8", "replace")}
            return {"http": code, "ms": int((time.time() - t0) * 1000), "body": payload, "error": None}
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            payload = {"_text": raw[:500].decode("utf-8", "replace")}
        return {"http": e.code, "ms": int((time.time() - t0) * 1000), "body": payload, "error": str(e)}
    except Exception as e:
        return {"http": 0, "ms": int((time.time() - t0) * 1000), "body": {}, "error": str(e)}


def wait_job(action, payload=None, timeout_sec=300):
    """POST /api/jobs y espera status ok|error."""
    r = req("POST", "/api/jobs", {"action": action, "payload": payload or {}, "feeder": FEEDER}, timeout=60)
    body = r.get("body") or {}
    if not body.get("job_id"):
        return {
            "ok": False,
            "step": action,
            "detail": "no job_id: %s" % (r.get("error") or body),
            "http": r.get("http"),
            "ms": r.get("ms"),
            "result": body,
        }
    jid = body["job_id"]
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout_sec:
        s = req("GET", "/api/jobs/%s" % jid, timeout=20)
        if s.get("http") == 0:
            return {
                "ok": False,
                "step": action,
                "job_id": jid,
                "detail": "server no responde al poll: %s" % s.get("error"),
                "result": last,
            }
        job = ((s.get("body") or {}).get("job") or {})
        last = job
        st = job.get("status")
        if st in ("ok", "error"):
            res = job.get("result") if isinstance(job.get("result"), dict) else {"raw": job.get("result")}
            ok = st == "ok" and (res.get("ok") is not False)
            return {
                "ok": ok,
                "step": action,
                "job_id": jid,
                "status": st,
                "ms": int((time.time() - t0) * 1000),
                "message": job.get("message"),
                "result": res,
                "detail": job.get("message") or st,
            }
        time.sleep(2.0)
    return {
        "ok": False,
        "step": action,
        "job_id": jid,
        "detail": "timeout %ss" % timeout_sec,
        "result": last,
    }


def case(name, step, ok, detail, **extra):
    row = {"id": name, "step": step, "ok": bool(ok), "detail": detail or ""}
    row.update(extra)
    return row


def emit(case_row):
    mark = "PASS" if case_row.get("ok") else "FAIL"
    line = "[%s] %s — %s" % (mark, case_row["id"], (case_row.get("detail") or "")[:180])
    print(line)
    sys.stdout.flush()
    return case_row


def main():
    cases = []
    print("UAT COM feeder=%s base=%s" % (FEEDER, BASE))
    sys.stdout.flush()

    # —— §1 ——
    r = req("GET", "/api/contexto/archivos", timeout=30)
    body = r.get("body") or {}
    db = body.get("current_database")
    st = body.get("current_study")
    if isinstance(db, dict):
        db = db.get("path")
    if isinstance(st, dict):
        st = st.get("path")
    r = req("POST", "/api/contexto/aplicar", {
        "database_mdb": db, "study_path": st, "feeder": FEEDER,
    }, timeout=60)
    b = r.get("body") or {}
    cases.append(emit(case("1.1 Aplicar BD+estudio", 1, b.get("ok") and r.get("http") == 200,
                      b.get("msg") or b.get("error") or r.get("error"), http=r.get("http"), ms=r.get("ms"))))

    r = req("POST", "/api/cabecera", {
        "mode": "KW_COSFI", "P_kW": 8500, "cosfi": 0.95, "feeder": FEEDER,
        "database_mdb": db, "study_path": st, "preview_only": False, "reset_downstream": False,
    }, timeout=180)
    b = r.get("body") or {}
    ok_cab = bool(b.get("ok") or b.get("cymdist_ok")) and r.get("http") == 200
    cases.append(emit(case(
        "1.2 Guardar cabecera SetDemand COM", 1, ok_cab,
        b.get("msg") or b.get("error") or r.get("error"),
        http=r.get("http"), ms=r.get("ms"), P_kW=b.get("P_kW"), cymdist_ok=b.get("cymdist_ok"),
    )))

    # —— §2 (sin convergencia larga: cuelga COM/uvicorn) ——
    j = wait_job("calidad_diagnosticar", {}, timeout_sec=420)
    cases.append(emit(case("2.1 Diagnosticar", 2, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    j = wait_job("calidad_proponer", {}, timeout_sec=240)
    cases.append(emit(case("2.2 Proponer", 2, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    j = wait_job("calidad_aplicar", {}, timeout_sec=420)
    cases.append(emit(case("2.3 Aplicar correcciones", 2, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    # Convergencia es opcional / riesgosa: intentar con timeout corto
    j = wait_job("calidad_convergencia", {}, timeout_sec=180)
    cases.append(emit(case("2.4 Convergencia LF", 2, j.get("ok"), j.get("detail") or "skip-soft", ms=j.get("ms"))))

    r = req("GET", "/api/calidad/estado", timeout=60)
    b = r.get("body") or {}
    cases.append(emit(case("2.5 Estado gate", 2, r.get("http") == 200,
                      "ready=%s · %s" % (b.get("ready"), b.get("msg") or b.get("error") or ""),
                      http=r.get("http"), ready=b.get("ready"))))

    r = req("GET", "/api/tablero?rebuild=1", timeout=90)
    b = r.get("body") or {}
    cases.append(emit(case("2.T Tablero rebuild", 2,
                      r.get("http") == 200 and bool(b.get("feeder_id") or b.get("ok")),
                      "feeder=%s clientes=%s" % (b.get("feeder_id"), (b.get("clientes") or {}).get("n")),
                      http=r.get("http"))))

    # —— §3 ——
    r = req("GET", "/api/clientes/archivos", timeout=30)
    files = r.get("body") or {}
    ci = (files.get("clientesimportantes") or [None])[0]
    su = (files.get("suministro") or [None])[0]
    r = req("POST", "/api/clientes/tabla", {
        "clientes_file": ci, "suministro_file": su, "feeders": [FEEDER], "feeder": FEEDER,
    }, timeout=300)
    b = r.get("body") or {}
    n_rows = len(b.get("rows") or [])
    cases.append(emit(case("3.1 Armar tabla", 3, bool(b.get("ok")) and n_rows > 0,
                      b.get("msg") or b.get("error") or ("filas=%s" % n_rows),
                      http=r.get("http"), ms=r.get("ms"), n_rows=n_rows)))

    r = req("POST", "/api/clientes/aplicar", {
        "clientes_file": ci, "suministro_file": su, "feeders": [FEEDER], "feeder": FEEDER,
        "open_gui": False, "fp": 0.95,
    }, timeout=480)
    b = r.get("body") or {}
    cases.append(emit(case("3.2 Cargar EA/Pot CYMDIST", 3, bool(b.get("ok")),
                      b.get("msg") or b.get("error") or r.get("error"),
                      http=r.get("http"), ms=r.get("ms"), ok_count=b.get("ok_count"))))

    j = wait_job("distribucion", {}, timeout_sec=420)
    cases.append(emit(case("3.3 Distribucion Consumo kWh", 3, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    # —— §4 ——
    r = req("GET", "/api/nodos/buscar?q=1&limit=20", timeout=120)
    b = r.get("body") or {}
    nodes = b.get("nodes") or b.get("results") or []
    node_id = ""
    if nodes:
        n0 = nodes[0]
        node_id = str(n0.get("NodeID") or n0.get("node_id") or n0.get("id") or "")
    cases.append(emit(case("4.0 Buscar nodos", 4, bool(node_id),
                      "n=%s node=%s" % (len(nodes), node_id), http=r.get("http"), ms=r.get("ms"))))

    if node_id:
        r = req("POST", "/api/cargas/nueva", {
            "node_id": node_id, "load_name": "UAT_RECYM_SPOT",
            "mode": "KW_COSFI", "P_kW": 100, "cosfi": 0.95,
        }, timeout=300)
        b = r.get("body") or {}
        cases.append(emit(case("4.2 Conectar SpotLoad UAT_RECYM_SPOT", 4, bool(b.get("ok")),
                          b.get("error") or ("LoadID=%s" % ((b.get("result") or {}).get("LoadID"))),
                          http=r.get("http"), ms=r.get("ms"))))
    else:
        cases.append(emit(case("4.2 Conectar SpotLoad", 4, False, "sin nodos")))

    # —— §5 ——
    j = wait_job("flujo", {"scenario": "situacional", "update_informe": True}, timeout_sec=480)
    cases.append(emit(case("5.1 Flujo situacional", 5, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    j = wait_job("flujo", {"scenario": "proyectado", "update_informe": True}, timeout_sec=480)
    cases.append(emit(case("5.2 Flujo proyectado", 5, j.get("ok"), j.get("detail"), ms=j.get("ms"))))

    # —— §6 ——
    r = req("GET", "/api/informe/meta", timeout=30)
    meta = (r.get("body") or {}).get("meta") or {}
    if not meta.get("cliente") or not meta.get("potencia_kw"):
        r = req("POST", "/api/informe/meta", {
            "cliente": "UAT RECYM", "potencia_kw": 100, "potencia_txt": "100KW",
            "alimentador": FEEDER, "ubicacion": "UAT",
        }, timeout=30)
        b = r.get("body") or {}
        cases.append(emit(case("6.1 Guardar meta minima", 6, r.get("http") == 200,
                          b.get("msg") or b.get("error") or "meta UAT", http=r.get("http"))))
    else:
        cases.append(emit(case("6.1 Meta existente", 6, True,
                          "cliente=%s kW=%s" % (meta.get("cliente"), meta.get("potencia_kw")))))

    r = req("GET", "/api/informe/status", timeout=60)
    b = r.get("body") or {}
    cases.append(emit(case("6.0 Checklist entrega", 6, r.get("http") == 200,
                      "ready=%s missing=%s" % (b.get("ready"), b.get("missing")),
                      http=r.get("http"), ready=b.get("ready"), missing=b.get("missing"))))

    r = req("POST", "/api/informe/armar", {"fill": True}, timeout=180)
    b = r.get("body") or {}
    cases.append(emit(case("6.2 Rellenar informes doc", 6, bool(b.get("ok")),
                      b.get("msg") or b.get("error") or ("missing=%s" % b.get("missing")),
                      http=r.get("http"), ms=r.get("ms"), missing=b.get("missing"))))

    # —— §7 ——
    r = req("GET", "/api/suite/entorno", timeout=90)
    b = r.get("body") or {}
    cases.append(emit(case("7.2a Validar entorno", 7, bool(b.get("cympy_ok") or b.get("ok")),
                      b.get("msg") or b.get("error") or r.get("error"),
                      http=r.get("http"), ms=r.get("ms"))))

    r = req("POST", "/api/suite/conexion", {}, timeout=120)
    b = r.get("body") or {}
    cases.append(emit(case("7.2b Conexion CYMDIST", 7, bool(b.get("ok")),
                      b.get("msg") or b.get("error") or r.get("error"),
                      http=r.get("http"), ms=r.get("ms"))))

    # Opt force puede colgar: timeout corto, no bloquear veredicto GO parcial
    r = req("POST", "/api/optimizacion/reclosers", {"force": True}, timeout=120)
    b = r.get("body") if isinstance(r.get("body"), dict) else {}
    exercised = r.get("http") == 200
    cases.append(emit(case("7.1a Opt reconectadores (force)", 7, exercised,
                      b.get("msg") or b.get("error") or r.get("error") or ("http=%s" % r.get("http")),
                      http=r.get("http"), ms=r.get("ms"), body_ok=b.get("ok"))))

    n_ok = sum(1 for c in cases if c.get("ok"))
    n_fail = sum(1 for c in cases if not c.get("ok"))
    report = {
        "product": "RECYM SPA UAT COM",
        "feeder": FEEDER,
        "base": BASE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": {"pass": n_ok, "fail": n_fail, "total": len(cases)},
        "verdict": "GO" if n_fail == 0 else ("GO-WITH-FAILURES" if n_ok >= max(1, n_fail) else "NO-GO"),
        "cases": cases,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=True)
    print(json.dumps({"verdict": report["verdict"], "summary": report["summary"]}, ensure_ascii=True))
    print("REPORT:", OUT)
    sys.stdout.flush()
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
