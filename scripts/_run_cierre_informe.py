# -*- coding: utf-8 -*-
"""Orquesta 3.3 → 5.1 → 5.2 → 6.2 y verifica cabecera vs informe."""
from __future__ import print_function
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("RECYM_UI_BASE") or "http://127.0.0.1:5055"
FEEDER = os.environ.get("RECYM_FEEDER") or "PA217"


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
                raise RuntimeError("%s fallo: %s" % (label, msg))
            return job.get("result") or {}
        if time.time() - t0 > timeout_sec:
            raise RuntimeError("%s timeout %ss · last=%s" % (label, timeout_sec, msg))
        time.sleep(2)


def main():
    print("BASE", BASE, "FEEDER", FEEDER)

    # 3.3 distribución
    r33 = run_job("distribucion", {}, timeout_sec=480, label="3.3 distribucion")
    print("  method=", (r33 or {}).get("method"), "status=", (r33 or {}).get("status") or (r33 or {}).get("ok"))
    val = (r33 or {}).get("validation") or {}
    print("  validation ok=", val.get("ok"), "sum_kw=", val.get("sum_kw"), "P_cab=", val.get("P_cabecera_kW"), "balance=", val.get("balance_msg") or val.get("balance_ok"))

    # 5.1 / 5.2 sin rellenar informe intermedio
    r51 = run_job(
        "flujo",
        {"scenario": "situacional", "update_informe": False},
        timeout_sec=360,
        label="5.1 situacional",
    )
    topo51 = ((r51 or {}).get("result") or {}).get("topo") or {}
    print("  situacional KWTOT=", topo51.get("KWTOT"), "KVARTOT=", topo51.get("KVARTOT"), "KWLOSS=", topo51.get("KWLOSS"))

    r52 = run_job(
        "flujo",
        {"scenario": "proyectado", "update_informe": False},
        timeout_sec=360,
        label="5.2 proyectado",
    )
    topo52 = ((r52 or {}).get("result") or {}).get("topo") or {}
    notes = ((r52 or {}).get("result") or {}).get("new_loads_scenario") or []
    print("  proyectado KWTOT=", topo52.get("KWTOT"), "KVARTOT=", topo52.get("KVARTOT"), "KWLOSS=", topo52.get("KWLOSS"))
    print("  new_loads=", notes)

    # 6.2 rellenar
    print("\n>>> 6.2 Rellenar informes", flush=True)
    arm = _req("POST", "/api/informe/armar", {}, timeout=300)
    print("  armar ok=", arm.get("ok"), "delivery=", arm.get("delivery_ready"), "err=", arm.get("error") or arm.get("missing"))
    sit_m = (arm.get("situacional_metrics") or arm.get("scenarios_used", {}).get("situacional_metrics")
             if isinstance(arm.get("scenarios_used"), dict) else None)
    # preview metrics
    prev = _req("GET", "/api/informe/preview", timeout=60)
    used = prev.get("scenarios_used") or {}
    sm = used.get("situacional_metrics") or {}
    pm = used.get("proyectado_metrics") or {}
    print("\n=== VERIFICACION ===")
    print("cabecera esperada ~9537.88 / 2587.65")
    print("situacional kw/kvar=", sm.get("kw"), sm.get("kvar"), "kw_loss=", sm.get("kw_loss"))
    print("proyectado  kw/kvar=", pm.get("kw"), pm.get("kvar"), "kw_loss=", pm.get("kw_loss"))
    try:
        kw_s = float(sm.get("kw") or 0)
        kw_p = float(pm.get("kw") or 0)
        p_cab = 9537.88
        ok_cab = abs(kw_s - p_cab) / p_cab < 0.08  # 8%
        ok_delta = kw_p > kw_s + 500  # al menos ~media SpotLoad
        print("OK_CABECERA_SIT=", ok_cab, "ratio_sit/cab=", round(kw_s / p_cab, 3))
        print("OK_DELTA_PROY=", ok_delta, "delta_kw=", round(kw_p - kw_s, 1))
        return 0 if (ok_cab and ok_delta and arm.get("ok")) else 1
    except Exception as ex:
        print("verify error", ex)
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print("FAIL:", ex)
        sys.exit(3)
