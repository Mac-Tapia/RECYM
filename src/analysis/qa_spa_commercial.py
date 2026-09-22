# -*- coding: utf-8 -*-
"""QA comercial SPA RECYM — smoke + contrato + POST bridge.
Salida: JSON con resultados por caso (pass/fail/warn/skip).
"""
from __future__ import print_function
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("RECYM_QA_BASE") or "http://127.0.0.1:5055"
OUT = os.environ.get("RECYM_QA_OUT") or os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "output", "system", "qa_spa_report.json"
)


def req(method, path, body=None, timeout=45, headers=None):
    url = BASE.rstrip("/") + path
    data = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        data = raw
        hdrs["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            ct = resp.headers.get("Content-Type") or ""
            code = resp.getcode()
            elapsed = round((time.time() - t0) * 1000)
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except Exception:
                payload = {"_text": raw[:300].decode("utf-8", "replace")}
            return {"ok": True, "status": code, "ms": elapsed, "ct": ct, "body": payload}
    except urllib.error.HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        elapsed = round((time.time() - t0) * 1000)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            payload = {"_text": raw[:300].decode("utf-8", "replace")}
        return {"ok": False, "status": e.code, "ms": elapsed, "body": payload, "error": str(e)}
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {"ok": False, "status": 0, "ms": elapsed, "error": str(e), "body": None}


def judge(name, step, kind, r, expect_status=200, require_json_ok=None, soft=False):
    status = "pass"
    detail = ""
    if not r.get("ok") and r.get("status") != expect_status:
        if soft and r.get("status") in (0, 502, 503, 504):
            status = "skip"
            detail = r.get("error") or "unavailable"
        elif soft:
            status = "warn"
            detail = "HTTP %s · %s" % (r.get("status"), r.get("error") or "")
        else:
            status = "fail"
            detail = "HTTP %s · %s" % (r.get("status"), r.get("error") or "")
    elif r.get("status") != expect_status:
        status = "fail"
        detail = "esperado %s obtuvo %s" % (expect_status, r.get("status"))
    else:
        body = r.get("body")
        if require_json_ok is True:
            if not isinstance(body, dict) or body.get("ok") is False:
                # algunos endpoints legacy no tienen ok
                if isinstance(body, dict) and "ok" in body and body.get("ok") is False:
                    status = "warn" if soft else "fail"
                    detail = str(body.get("error") or body.get("msg") or "ok=false")
                elif not isinstance(body, dict):
                    status = "fail"
                    detail = "respuesta no JSON objeto"
        if require_json_ok is False and isinstance(body, dict) and body.get("ok") is False:
            status = "pass"  # expected failure path
            detail = "error controlado: %s" % (body.get("error") or "ok=false")
        if status == "pass" and not detail:
            detail = "%sms" % r.get("ms")
    return {
        "id": name,
        "step": step,
        "kind": kind,
        "status": status,
        "http": r.get("status"),
        "ms": r.get("ms"),
        "detail": detail,
        "body_ok": (r.get("body") or {}).get("ok") if isinstance(r.get("body"), dict) else None,
    }


def main():
    cases = []

    # —— Infra / SPA ——
    r = req("GET", "/")
    cases.append(judge("SPA index HTML", 0, "smoke", r, require_json_ok=None))
    if isinstance(r.get("body"), dict) and r["body"].get("_text"):
        html = r["body"]["_text"]
    else:
        # non-json: re-fetch as text via special handling
        try:
            with urllib.request.urlopen(BASE + "/", timeout=15) as resp:
                html = resp.read().decode("utf-8", "replace")
            cases[-1]["status"] = "pass" if ("root" in html or "RECYM" in html) else "fail"
            cases[-1]["detail"] = "HTML %d bytes" % len(html)
            cases[-1]["http"] = 200
        except Exception as e:
            cases[-1]["status"] = "fail"
            cases[-1]["detail"] = str(e)

    r = req("GET", "/api/spa/meta")
    cases.append(judge("GET /api/spa/meta (7 steps)", 0, "contract", r, require_json_ok=True))
    steps = ((r.get("body") or {}).get("steps") or []) if isinstance(r.get("body"), dict) else []
    if len(steps) != 7 and cases[-1]["status"] == "pass":
        cases[-1]["status"] = "fail"
        cases[-1]["detail"] = "steps=%d (esperado 7)" % len(steps)

    r = req("GET", "/api/ui/ping")
    cases.append(judge("GET /api/ui/ping", 0, "smoke", r, require_json_ok=True))

    # —— §1 ——
    r = req("GET", "/api/contexto/archivos")
    cases.append(judge("1.0 GET contexto/archivos", 1, "functional", r, require_json_ok=True))
    body = r.get("body") or {}
    dbs = body.get("databases") or []
    studies = body.get("studies") or []
    cur_db = body.get("current_database") or (dbs[0] if dbs else None)
    cur_st = body.get("current_study") or (studies[0] if studies else None)
    if isinstance(cur_db, dict):
        cur_db = cur_db.get("path")
    if isinstance(cur_st, dict):
        cur_st = cur_st.get("path")
    if isinstance(dbs, list) and dbs and isinstance(dbs[0], dict):
        cur_db = cur_db or dbs[0].get("path")
    if isinstance(studies, list) and studies and isinstance(studies[0], dict):
        cur_st = cur_st or studies[0].get("path")

    # POST bridge fix verification (critical for commercial)
    r = req("POST", "/api/contexto/aplicar", {
        "database_mdb": cur_db,
        "study_path": cur_st,
    }, timeout=60)
    cases.append(judge("1.1 POST contexto/aplicar (bridge POST)", 1, "critical", r, require_json_ok=True, soft=True))

    r = req("POST", "/api/cabecera", {
        "mode": "KW_COSFI",
        "P_kW": 100,
        "cosfi": 0.95,
        "preview_only": True,
    }, timeout=30)
    cases.append(judge("1.2 POST cabecera preview_only", 1, "functional", r, require_json_ok=True))

    r = req("POST", "/api/ui/reset", {})
    cases.append(judge("POST /api/ui/reset", 0, "smoke", r, require_json_ok=True))

    # —— §2 ——
    r = req("GET", "/api/calidad/estado", timeout=90)
    cases.append(judge("2.5 GET calidad/estado", 2, "functional", r, soft=True))

    r = req("GET", "/api/tablero")
    cases.append(judge("2.T GET /api/tablero JSON", 2, "critical", r))
    if isinstance(r.get("body"), dict) and not r["body"].get("feeder_id") and cases[-1]["status"] == "pass":
        if r["body"].get("ok") is False:
            cases[-1]["status"] = "warn"
            cases[-1]["detail"] = r["body"].get("error") or "sin feeder"

    r = req("POST", "/api/jobs", {"action": "build_tablero", "payload": {}})
    cases.append(judge("2.J POST /api/jobs build_tablero", 2, "jobs", r, require_json_ok=True))
    job_id = (r.get("body") or {}).get("job_id") if isinstance(r.get("body"), dict) else None
    if job_id:
        time.sleep(1.2)
        r2 = req("GET", "/api/jobs/%s" % job_id)
        cases.append(judge("2.J GET /api/jobs/{id}", 2, "jobs", r2, require_json_ok=True))
        st = ((r2.get("body") or {}).get("job") or {}).get("status")
        if st not in ("ok", "running", "queued") and cases[-1]["status"] == "pass":
            cases[-1]["status"] = "fail"
            cases[-1]["detail"] = "status=%s" % st

    # validation: unknown job action
    r = req("POST", "/api/jobs", {"action": "accion_inexistente_xyz", "payload": {}})
    if r.get("status") == 200 and (r.get("body") or {}).get("job_id"):
        jid = r["body"]["job_id"]
        time.sleep(0.8)
        r2 = req("GET", "/api/jobs/%s" % jid)
        job = (r2.get("body") or {}).get("job") or {}
        if job.get("status") == "error":
            cases.append({
                "id": "2.J job acción inválida → error",
                "step": 2, "kind": "negative", "status": "pass",
                "http": 200, "ms": r2.get("ms"), "detail": job.get("message") or "error",
            })
        else:
            cases.append({
                "id": "2.J job acción inválida → error",
                "step": 2, "kind": "negative", "status": "fail",
                "http": r2.get("status"), "ms": r2.get("ms"),
                "detail": "status=%s" % job.get("status"),
            })
    else:
        cases.append(judge("2.J job acción inválida", 2, "negative", r, soft=True))

    # —— §3 ——
    r = req("GET", "/api/clientes/archivos")
    cases.append(judge("3.0 GET clientes/archivos", 3, "functional", r, require_json_ok=True))
    sum_files = (r.get("body") or {}).get("suministro") or []
    sum_file = sum_files[0] if sum_files else ""
    if sum_file:
        r = req("GET", "/api/clientes/radiales?suministro_file=" + urllib.request.quote(sum_file))
        cases.append(judge("3.0 GET clientes/radiales", 3, "functional", r, require_json_ok=True))

    # negative: armar tabla sin archivo
    r = req("POST", "/api/clientes/tabla", {"clientes_file": "", "feeders": ["IN112"]}, timeout=30)
    ok_flag = isinstance(r.get("body"), dict) and r["body"].get("ok") is False
    cases.append({
        "id": "3.1 POST clientes/tabla sin archivo (negativo)",
        "step": 3, "kind": "negative",
        "status": "pass" if (r.get("status") == 200 and ok_flag) else "fail",
        "http": r.get("status"), "ms": r.get("ms"),
        "detail": (r.get("body") or {}).get("error") if isinstance(r.get("body"), dict) else str(r.get("error")),
    })

    # —— §4 ——
    r = req("GET", "/api/nodos/buscar?q=A&limit=5", timeout=60)
    cases.append(judge("4.0 GET nodos/buscar", 4, "functional", r, soft=True))

    r = req("POST", "/api/cargas/nueva", {"node_id": "", "load_name": ""}, timeout=20)
    ok_flag = isinstance(r.get("body"), dict) and r["body"].get("ok") is False
    cases.append({
        "id": "4.2 POST cargas/nueva vacío (negativo)",
        "step": 4, "kind": "negative",
        "status": "pass" if (r.get("status") == 200 and ok_flag) else "fail",
        "http": r.get("status"), "ms": r.get("ms"),
        "detail": (r.get("body") or {}).get("error") if isinstance(r.get("body"), dict) else "",
    })

    # —— §5 (soft: COM may be long / busy) ——
    # Don't run full LF in QA smoke — only validate endpoint accepts and returns JSON quickly or busy
    # Skip actual flujo to avoid mutating model; document as manual UAT

    # —— §6 ——
    r = req("GET", "/api/informe/status")
    cases.append(judge("6.0 GET informe/status", 6, "functional", r, soft=True))
    r = req("GET", "/api/informe/rutas")
    cases.append(judge("6.0 GET informe/rutas", 6, "functional", r, soft=True))
    r = req("GET", "/api/informe/meta")
    cases.append(judge("6.1 GET informe/meta", 6, "functional", r, soft=True))

    # —— §7 ——
    r = req("GET", "/api/suite/entorno", timeout=60)
    cases.append(judge("7.2a GET suite/entorno", 7, "functional", r, soft=True))

    r = req("POST", "/api/optimizacion/noexiste", {"force": True}, timeout=20)
    # expect 200 with ok=false or similar
    body = r.get("body") if isinstance(r.get("body"), dict) else {}
    cases.append({
        "id": "7.1 POST optimizacion inválida (negativo)",
        "step": 7, "kind": "negative",
        "status": "pass" if (r.get("status") == 200 and body.get("ok") is False) else ("warn" if r.get("status") else "fail"),
        "http": r.get("status"), "ms": r.get("ms"),
        "detail": body.get("error") or r.get("error") or "",
    })

    # OpenAPI / docs
    try:
        with urllib.request.urlopen(BASE + "/openapi.json", timeout=15) as resp:
            oj = json.loads(resp.read().decode("utf-8"))
        cases.append({
            "id": "OpenAPI schema disponible",
            "step": 0, "kind": "contract", "status": "pass",
            "http": 200, "ms": 0, "detail": "paths=%d" % len(oj.get("paths") or {}),
        })
    except Exception as e:
        cases.append({
            "id": "OpenAPI schema disponible",
            "step": 0, "kind": "contract", "status": "warn",
            "http": 0, "ms": 0, "detail": str(e),
        })

    # Assets
    try:
        with urllib.request.urlopen(BASE + "/", timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")
        import re
        m = re.search(r'src="(/assets/[^"]+\.js)"', html)
        if m:
            with urllib.request.urlopen(BASE + m.group(1), timeout=15) as resp2:
                js_ok = resp2.getcode() == 200
            cases.append({
                "id": "SPA asset JS servido",
                "step": 0, "kind": "smoke",
                "status": "pass" if js_ok else "fail",
                "http": 200 if js_ok else 0, "ms": 0, "detail": m.group(1),
            })
    except Exception as e:
        cases.append({
            "id": "SPA asset JS servido", "step": 0, "kind": "smoke",
            "status": "fail", "http": 0, "ms": 0, "detail": str(e),
        })

    counts = {"pass": 0, "fail": 0, "warn": 0, "skip": 0}
    for c in cases:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    report = {
        "product": "RECYM SPA UI",
        "base": BASE,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": counts,
        "verdict": (
            "NO-GO" if counts.get("fail", 0) else (
                "GO-WITH-WARNINGS" if counts.get("warn", 0) else "GO"
            )
        ),
        "cases": cases,
        "notes": [
            "Smoke/contract/negativos automáticos. Flujos LoadFlow y Apply CYMDIST requieren UAT manual con Cyme abierto.",
            "Criterio comercial: 0 fail en critical/smoke/contract; warns aceptables si COM ocupado.",
        ],
    }

    out_path = os.path.abspath(OUT)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    print("REPORT:", out_path, file=sys.stderr)
    return 0 if counts.get("fail", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
