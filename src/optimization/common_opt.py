from __future__ import print_function
from core.common import require_cympy, truthy, load_json
from core.excel_io import read_kv
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path

def run_opt(command_name, control_flag=None, settings=None, force=False):
    """Ejecuta comando de optimización CYMDIST. Devuelve dict para CLI/UI."""
    s = settings or load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    ctrl = read_kv(book, "Control_Proyecto") if book else {}

    result = {
        "ok": False,
        "feeder_id": s.get("feeder_id"),
        "command": command_name,
        "control_flag": control_flag,
        "status": "error",
    }

    if control_flag and not force and not truthy(ctrl.get(control_flag)):
        msg = "Omitido por control Excel (%s=false): %s" % (control_flag, command_name)
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({"ok": True, "status": "skipped", "msg": msg})
        return result

    cfg = api.get("commands", {}).get(command_name, {})
    if s.get("dry_run"):
        msg = "DRY_RUN: %s | confirmed=%s" % (command_name, cfg.get("confirmed"))
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({"ok": True, "status": "dry_run", "msg": msg, "confirmed": cfg.get("confirmed")})
        return result

    if not cfg.get("confirmed"):
        msg = "OMITIDO (sin API CymPy): %s - %s" % (command_name, cfg.get("note") or "")
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({"ok": False, "status": "unconfirmed", "msg": msg})
        return result

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.ensure_study()
    a.command(command_name)
    print("[%s] OK: %s" % (s["feeder_id"], command_name))
    lf_ok = None
    lf_err = None
    try:
        a.run_load_flow()
        lf_ok = True
        print("[%s] LoadFlow post-optimización ejecutado." % s["feeder_id"])
    except Exception as ex:
        lf_ok = False
        lf_err = str(ex)
        print("AVISO LoadFlow post-opt:", ex)
    result.update({
        "ok": True,
        "status": "ok",
        "msg": "OK: %s" % command_name,
        "loadflow_ok": lf_ok,
        "loadflow_error": lf_err,
    })
    return result
