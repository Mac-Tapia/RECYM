from __future__ import print_function
"""Inventario de cargas SpotLoad / DistributedLoad del alimentador activo."""
import json
from core.common import require_cympy, load_json, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path

def _safe_get(dev, field):
    try:
        return dev.GetValue(field)
    except Exception:
        return ""

def collect_loads(cympy, network_id):
    rows = []
    for dtype, label in (
        (cympy.enums.DeviceType.SpotLoad, "SpotLoad"),
        (cympy.enums.DeviceType.DistributedLoad, "DistributedLoad"),
    ):
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id))
        except Exception:
            devices = []
        for d in devices:
            load_id = getattr(d, "DeviceNumber", None) or _safe_get(d, "DeviceNumber")
            # Intentar leer P/Q actuales (polimórfico LoadValue)
            kw = ""
            kvar = ""
            base = "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue"
            for p_path, q_path in (
                (base + ".KW", base + ".KVAR"),
                (base + ".KW", base + ".PF"),
                (base + ".KVA", base + ".PF"),
            ):
                try:
                    kw = d.GetValue(p_path)
                    kvar = d.GetValue(q_path)
                    break
                except Exception:
                    pass
            try:
                vtype = d.GetValue(base + ".GetType()")
            except Exception:
                vtype = ""
            rows.append({
                "LoadID": str(load_id),
                "Tipo": label,
                "SectionID": str(getattr(d, "SectionID", "") or ""),
                "kW": str(kw),
                "kvar": str(kvar),
                "LoadValueType": str(vtype),
                "ZoneID": str(_safe_get(d, "ZoneID") or ""),
                "Label": "%s (%s)" % (load_id, label),
            })
    return rows

def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    rows = collect_loads(c, s.get("network_id"))
    out = output_path(s, "inventory", "loads.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"feeder_id": s["feeder_id"], "network_id": s.get("network_id"), "loads": rows}, f, indent=2, ensure_ascii=False)
    print("Cargas:", len(rows))
    print(out)

if __name__ == "__main__":
    run_cympy_main(main)
