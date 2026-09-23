# -*- coding: utf-8 -*-
"""Continua: 5.1 → 5.2 → 6.2 (3.3 ya OK)."""
from __future__ import print_function
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:5055"
FEEDER = "PA217"


def _req(method, path, body=None, timeout=120):
    url = BASE + path
    data = None
    headers = {"X-Feeder": FEEDER, "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw) if raw else {}


def run_job(action, payload, timeout_sec=420, label=None):
    label = label or action
    print("\n>>> JOB", label, flush=True)
    created = _req("POST", "/api/jobs", {"action": action, "payload": payload, "feeder": FEEDER})
    if not created.get("ok") or not created.get("job_id"):
        raise RuntimeError("No job: %s" % created)
    jid = created["job_id"]
    t0 = time.time()
    last_msg = ""
    while True:
        wrap = _req("GET", "/api/jobs/%s" % jid, timeout=30)
        job = wrap.get("job") if isinstance(wrap.get("job"), dict) else wrap
        st = job.get("status")
        msg = str(job.get("message") or "")
        if msg and msg != last_msg:
            print("  [%ss] %s" % (int(time.time() - t0), msg), flush=True)
            last_msg = msg
        if st in ("ok", "error"):
            print("  DONE status=%s elapsed=%.1fs" % (st, time.time() - t0), flush=True)
            if st != "ok":
                raise RuntimeError("%s fallo: %s · %s" % (label, msg, job.get("result")))
            return job.get("result") or {}
        if time.time() - t0 > timeout_sec:
            raise RuntimeError("%s timeout %ss · last=%s" % (label, timeout_sec, msg))
        time.sleep(2)


def main():
    r51 = run_job(
        "flujo",
        {"scenario": "situacional", "update_informe": False},
        timeout_sec=360,
        label="5.1 situacional",
    )
    topo51 = ((r51 or {}).get("result") or {}).get("topo") or {}
    notes51 = ((r51 or {}).get("result") or {}).get("new_loads_scenario") or []
    print("  situacional KWTOT=", topo51.get("KWTOT"), "KVARTOT=", topo51.get("KVARTOT"), "KWLOSS=", topo51.get("KWLOSS"))
    print("  loads=", notes51)

    r52 = run_job(
        "flujo",
        {"scenario": "proyectado", "update_informe": False},
        timeout_sec=360,
        label="5.2 proyectado",
    )
    topo52 = ((r52 or {}).get("result") or {}).get("topo") or {}
    notes52 = ((r52 or {}).get("result") or {}).get("new_loads_scenario") or []
    print("  proyectado KWTOT=", topo52.get("KWTOT"), "KVARTOT=", topo52.get("KVARTOT"), "KWLOSS=", topo52.get("KWLOSS"))
    print("  loads=", notes52)

    print("\n>>> 6.2 Rellenar informes", flush=True)
    arm = _req("POST", "/api/informe/armar", {}, timeout=360)
    print("  armar ok=", arm.get("ok"), "delivery=", arm.get("delivery_ready"))
    if arm.get("error") or arm.get("missing"):
        print("  missing/err=", arm.get("error") or arm.get("missing"))

    prev = _req("GET", "/api/informe/preview", timeout=90)
    used = prev.get("scenarios_used") or {}
    sm = used.get("situacional_metrics") or {}
    pm = used.get("proyectado_metrics") or {}
    print("\n=== VERIFICACION ===")
    print("cabecera esperada ~9537.88 / 2587.65")
    print("situacional kw/kvar/loss=", sm.get("kw"), sm.get("kvar"), sm.get("kw_loss"))
    print("proyectado  kw/kvar/loss=", pm.get("kw"), pm.get("kvar"), pm.get("kw_loss"))
    p_cab = 9537.88
    kw_s = float(sm.get("kw") or 0)
    kw_p = float(pm.get("kw") or 0)
    ok_cab = abs(kw_s - p_cab) / p_cab < 0.08 if kw_s else False
    ok_delta = kw_p > kw_s + 500 if kw_s else False
    print("OK_CABECERA_SIT=", ok_cab, "ratio=", round(kw_s / p_cab, 3) if kw_s else None)
    print("OK_DELTA_PROY=", ok_delta, "delta_kw=", round(kw_p - kw_s, 1))
    print("ARMAR_OK=", bool(arm.get("ok")))
    return 0 if (ok_cab and ok_delta and arm.get("ok")) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print("FAIL:", ex)
        sys.exit(3)
