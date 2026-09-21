from __future__ import print_function
from core.common import require_cympy, load_json, write_csv
from core.excel_io import read_kv
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path, output_path

def _safe_float(v):
    try:
        if v in (None, ""):
            return ""
        return float(str(v).replace(",", "."))
    except Exception:
        return str(v)

def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    ctrl = read_kv(book, "Control_Proyecto")
    out = output_path(s, "diagnostics", "diagnostico_tecnico.csv")

    row = {
        "Utility": s.get("utility_name"),
        "Feeder": s.get("feeder_id"),
        "Escenario": ctrl.get("Escenario_Base"),
        "Converge": "",
        "P_Cabecera_kW": "",
        "Q_Cabecera_kvar": "",
        "Vmin_pu": "",
        "Nodo_Vmin": "",
        "Vmax_pu": "",
        "Perdidas_kW": "",
        "Perdidas_pct": "",
        "Imax_A": "",
        "Seccion_Imax": "",
        "Sobrecargas": "",
        "Violaciones_V": "",
        "Estado": "",
    }

    if s.get("dry_run"):
        row["Estado"] = "DRY_RUN"
        row["P_Cabecera_kW"] = ctrl.get("Demanda_Max_Cabecera_kW")
        write_csv(out, [row], list(row.keys()))
        print(out)
        return

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.ensure_study()
    keys = api.get("result_keywords") or {}
    try:
        valid = c.sim.IsValidResults(str(s.get("network_id")), c.enums.SimulationType.LoadFlow)
        row["Converge"] = "SI" if valid else "NO"
    except Exception as ex:
        row["Converge"] = "DESCONOCIDO"
        print("AVISO IsValidResults:", ex)

    for field, kw in (
        ("P_Cabecera_kW", keys.get("network_kw", "KWTOT")),
        ("Q_Cabecera_kvar", keys.get("network_kvar", "KVARTOT")),
        ("Perdidas_kW", keys.get("network_loss_kw", "KWLOSS")),
        ("Vmin_pu", keys.get("vmin_pu", "VMINPU")),
        ("Vmax_pu", keys.get("vmax_pu", "VMAXPU")),
        ("Imax_A", keys.get("imax_a", "IMAX")),
    ):
        try:
            row[field] = _safe_float(a.query_topo(kw))
        except Exception as ex:
            row[field] = ""
            print("AVISO keyword", kw, ":", ex)

    row["Estado"] = "OK" if row["Converge"] == "SI" else "REVISAR"
    write_csv(out, [row], list(row.keys()))
    print(out)

if __name__ == "__main__":
    main()
