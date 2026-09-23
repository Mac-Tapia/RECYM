# -*- coding: utf-8 -*-
"""Ejecuta cierre §1→§7 vía API RECYM (PA217)."""
from __future__ import print_function
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5055"
FEEDER = "PA217"
HDR = {
    "Content-Type": "application/json",
    "X-Feeder": FEEDER,
}
REPORT = []


def log(step, msg, ok=True, detail=None):
    row = {"step": step, "ok": ok, "msg": msg}
    if detail is not None:
        row["detail"] = detail
    REPORT.append(row)
    flag = "OK" if ok else "FAIL"
    print("[%s] %s · %s" % (flag, step, msg))
    if detail and not ok:
        print("   ", str(detail)[:400])
    sys.stdout.flush()


def http(method, path, body=None, timeout=180):
    data = None
    headers = dict(HDR)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return json.loads(raw), None
            except Exception:
                return {"raw": raw[:500]}, None
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8", "replace")
            j = json.loads(err)
        except Exception:
            j = {"error": str(e), "body": err[:300] if "err" in dir() else ""}
        return j, str(e)
    except Exception as e:
        return {"error": str(e)}, str(e)


def run_job(action, payload=None, timeout_sec=600, poll=2.0):
    body = {"action": action, "payload": payload or {}, "feeder": FEEDER}
    created, err = http("POST", "/api/jobs", body, timeout=60)
    if err or not created.get("ok"):
        return {"ok": False, "error": err or created}, None
    jid = created.get("job_id")
    t0 = time.time()
    last_msg = ""
    while time.time() - t0 < timeout_sec:
        j, e = http("GET", "/api/jobs/%s" % jid, timeout=30)
        job = (j or {}).get("job") or j or {}
        st = str(job.get("status") or "")
        msg = str(job.get("message") or "")
        if msg and msg != last_msg:
            print("   …", msg[:120])
            sys.stdout.flush()
            last_msg = msg
        if st == "ok":
            return job.get("result") or job, None
        if st == "error":
            res = job.get("result") or {}
            return res, res.get("error") or job.get("message") or "job error"
        time.sleep(poll)
    return {"ok": False}, "timeout %ss job=%s" % (timeout_sec, jid)


def main():
    print("=" * 60)
    print("CIERRE 1..7 · feeder=%s" % FEEDER)
    print("=" * 60)

    # —— §1 Contexto + cabecera ——
    files, err = http("GET", "/api/contexto/archivos", timeout=30)
    if err:
        log("1.0 archivos", "no responde", False, err)
    else:
        log("1.0 archivos", "n_feeders=%s" % files.get("n_feeders"))

    apl, err = http(
        "POST",
        "/api/contexto/aplicar",
        {"feeder": FEEDER, "feeder_id": FEEDER},
        timeout=60,
    )
    log("1.1 aplicar", apl.get("msg") or apl.get("feeder_id") or "contexto",
        ok=not err and apl.get("ok", True) is not False, detail=err or apl.get("error"))

    cab, err = http("GET", "/api/cabecera?feeder=%s" % FEEDER, timeout=30)
    ok1 = not err and cab.get("P_kW") not in (None, "")
    log(
        "1.2 cabecera",
        "P=%.2f kW Q=%.2f · %s" % (
            float(cab.get("P_kW") or 0),
            float(cab.get("Q_kvar") or 0),
            cab.get("network_id") or "",
        ),
        ok=ok1,
        detail=err,
    )
    if not ok1:
        print("STOP: falta cabecera §1")
        return 1

    # —— §2 Calidad + tablero ——
    est, _ = http("GET", "/api/calidad/estado", timeout=30)
    log("2.0 estado", "ready=%s converge=%s" % (est.get("ready"), est.get("converge")))

    res, err = run_job("calidad_diagnosticar", {}, timeout_sec=300)
    log("2.1 diagnosticar", (res or {}).get("msg") or "diag",
        ok=not err and (res or {}).get("ok", True) is not False, detail=err)

    res, err = run_job("build_tablero", {}, timeout_sec=120)
    log("2.2 tablero", "regenerado" if not err else str(err), ok=not err, detail=err)

    # —— §3 Clientes + distribución ——
    arch, _ = http("GET", "/api/clientes/archivos", timeout=30)
    sumi = (arch.get("suministro") or [None])[0]
    cli = (arch.get("clientesimportantes") or [None])[0]
    log("3.0 archivos", "suministro=%s · CI=%s" % (sumi, cli), ok=bool(sumi and cli))

    tab, err = http(
        "POST",
        "/api/clientes/tabla",
        {
            "feeder": FEEDER,
            "feeders": [FEEDER],
            "suministro": sumi,
            "clientesimportantes": cli,
            "rebuild": False,
        },
        timeout=180,
    )
    n = len(tab.get("rows") or []) if isinstance(tab, dict) else 0
    log("3.1 tabla", "filas=%s" % n, ok=not err and n > 0, detail=err or tab.get("error"))

    apl3, err = http(
        "POST",
        "/api/clientes/aplicar",
        {"feeder": FEEDER, "feeders": [FEEDER]},
        timeout=300,
    )
    log(
        "3.2 aplicar EA/Pot",
        apl3.get("msg") or "aplicar",
        ok=not err and apl3.get("ok", True) is not False,
        detail=err or apl3.get("error"),
    )

    res, err = run_job("distribucion", {}, timeout_sec=600)
    val = ((res or {}).get("result") or res or {}).get("validation") or {}
    timing = ((res or {}).get("result") or res or {}).get("timing") or {}
    log(
        "3.3 distribución",
        "%s · total=%ss · %s" % (
            ((res or {}).get("result") or res or {}).get("method") or (res or {}).get("status"),
            timing.get("total_sec"),
            val.get("msg") or (res or {}).get("msg") or "",
        ),
        ok=not err and (res or {}).get("ok", True) is not False,
        detail=err or (res or {}).get("error"),
    )

    # —— §4 SpotLoad (inventario; no crear carga nueva) ——
    inv, err = http("POST", "/api/nodos/inventario", {}, timeout=180)
    log(
        "4.1 inventario nodos/cargas",
        "n=%s" % (inv.get("n") or len(inv.get("rows") or []) or inv.get("count") or "?"),
        ok=not err and inv.get("ok", True) is not False,
        detail=err or inv.get("error"),
    )
    log("4.2 spotload nueva", "omitido (ya existe last_spot_load en sesión)", ok=True)

    # —— §5 Flujos ——
    for scen, label in (("situacional", "5.1 situacional"), ("proyectado", "5.2 proyectado")):
        res, err = run_job(
            "flujo",
            {"scenario": scen, "update_informe": True},
            timeout_sec=420,
        )
        st = ((res or {}).get("result") or res or {}).get("status") or (res or {}).get("msg")
        log(label, str(st)[:160], ok=not err and (res or {}).get("ok", True) is not False,
            detail=err or (res or {}).get("error"))

    # —— §6 Informes ——
    arm, err = http("POST", "/api/informe/armar", {"fill": True}, timeout=180)
    log("6.1 armar informe", arm.get("msg") or arm.get("path") or "armar",
        ok=not err and arm.get("ok", True) is not False, detail=err or arm.get("error"))

    st6, _ = http("GET", "/api/informe/status", timeout=30)
    log(
        "6.2 status entrega",
        "delivery_ready=%s missing=%s" % (
            st6.get("delivery_ready"),
            ",".join(st6.get("missing") or [])[:120],
        ),
        ok=True,
    )

    # —— §7 Suite (cierre liviano; pipeline completo es opcional) ——
    ent, err = http("GET", "/api/suite/entorno", timeout=60)
    log("7.1 entorno", "ok" if not err else str(err), ok=not err, detail=err)

    con, err = http("POST", "/api/suite/conexion", {}, timeout=120)
    log("7.2 conexion", con.get("msg") or "conexion",
        ok=not err and con.get("ok", True) is not False, detail=err or con.get("error"))

    val7, err = http("POST", "/api/suite/validar_entradas", {}, timeout=120)
    log("7.3 validar entradas", val7.get("msg") or "validar",
        ok=not err and val7.get("ok", True) is not False, detail=err or val7.get("error"))

    # Pipeline completo puede ser muy largo; intentar con timeout acotado
    pipe, err = http("POST", "/api/suite/pipeline", {}, timeout=300)
    log(
        "7.4 pipeline",
        pipe.get("msg") or ("timeout/omitido" if err else "pipeline"),
        ok=not err and pipe.get("ok", True) is not False,
        detail=err or pipe.get("error"),
    )

    n_ok = sum(1 for r in REPORT if r["ok"])
    n_fail = sum(1 for r in REPORT if not r["ok"])
    print("=" * 60)
    print("RESUMEN · OK=%d FAIL=%d" % (n_ok, n_fail))
    out = r"data\output\feeders\PA217\demand\cierre_1_7_report.json"
    try:
        import os
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"feeder": FEEDER, "steps": REPORT, "n_ok": n_ok, "n_fail": n_fail},
                      f, indent=2, ensure_ascii=False)
        print("Reporte:", out)
    except Exception as ex:
        print("AVISO save report:", ex)
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
