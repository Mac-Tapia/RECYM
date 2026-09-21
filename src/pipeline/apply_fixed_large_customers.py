from __future__ import print_function
import math
from core.common import require_cympy, truthy, load_json
from core.excel_io import read_rows
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path

def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    rows = [r for r in read_rows(book, "Clientes_Grandes") if truthy(r.get("Activo"))]
    if not rows:
        print("[%s] Sin clientes grandes activos." % s["feeder_id"])
        return

    a = None
    if not s.get("dry_run"):
        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        a.ensure_study()

    for r in rows:
        if r.get("kW_Fijo") in (None, ""):
            raise RuntimeError("Cliente grande incompleto (kW_Fijo): " + str(r.get("LoadID")))
        kw = float(r["kW_Fijo"])
        if r.get("kvar_Fijo") not in (None, ""):
            kvar = float(r["kvar_Fijo"])
        elif r.get("FP") not in (None, ""):
            fp = float(r["FP"])
            if fp <= 0 or fp > 1:
                raise RuntimeError("FP inválido para " + str(r["LoadID"]))
            kvar = kw * math.tan(math.acos(fp))
        else:
            raise RuntimeError("Falta kvar o FP para " + str(r["LoadID"]))

        if s.get("dry_run"):
            print("DRY FIXED LOAD", r["LoadID"], kw, round(kvar, 3))
        else:
            print("WRITE FIXED LOAD", r["LoadID"], a.set_load_pq(r["LoadID"], kw, kvar, lock=True))

if __name__ == "__main__":
    main()
