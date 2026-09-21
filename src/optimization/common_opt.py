from __future__ import print_function
from core.common import require_cympy, truthy, load_json
from core.excel_io import read_kv
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path

def run_opt(command_name, control_flag=None):
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    ctrl = read_kv(book, "Control_Proyecto")

    if control_flag and not truthy(ctrl.get(control_flag)):
        print("[%s] Omitido por control Excel (%s=false): %s" % (s["feeder_id"], control_flag, command_name))
        return

    cfg = api.get("commands", {}).get(command_name, {})
    if s.get("dry_run"):
        print("[%s] DRY_RUN: %s | confirmed=%s" % (s["feeder_id"], command_name, cfg.get("confirmed")))
        return

    if not cfg.get("confirmed"):
        print("[%s] OMITIDO (sin API CymPy): %s - %s" % (s["feeder_id"], command_name, cfg.get("note") or ""))
        return

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.ensure_study()
    a.command(command_name)
    print("[%s] OK: %s" % (s["feeder_id"], command_name))
    try:
        a.run_load_flow()
        print("[%s] LoadFlow post-optimización ejecutado." % s["feeder_id"])
    except Exception as ex:
        print("AVISO LoadFlow post-opt:", ex)
