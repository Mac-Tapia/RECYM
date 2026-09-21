from __future__ import print_function
from core.feeder_context import load_settings, control_path, catalog_path
from core.excel_io import read_rows, read_kv
import os

def main():
    s = load_settings()
    book = control_path(s)
    catalog = catalog_path(s)

    print("Utility:", s.get("utility_name"))
    print("Alimentador:", s.get("feeder_id"), "-", s.get("feeder_name"))

    if not os.path.isfile(book):
        print("No existe control workbook:", book)
        raise SystemExit(1)

    ctrl = read_kv(book, "Control_Proyecto")
    required = ["NetworkID", "Tension_MT_LL", "Demanda_Max_Cabecera_kW", "Escenario_Base"]
    missing = [x for x in required if ctrl.get(x) in (None, "")]
    if missing:
        print("FALTAN en Control_Proyecto:", ", ".join(missing))
        raise SystemExit(2)

    # Consistencia NetworkID Excel vs config alimentador
    net_cfg = str(s.get("network_id") or "")
    net_xls = str(ctrl.get("NetworkID") or "")
    if net_cfg and net_xls and net_cfg != net_xls:
        print("AVISO: NetworkID Excel (%s) != config alimentador (%s)" % (net_xls, net_cfg))

    from core.common import truthy
    clients = [r for r in read_rows(book, "Clientes_Grandes") if truthy(r.get("Activo"))]
    for r in clients:
        if not r.get("LoadID") or r.get("kW_Fijo") in (None, ""):
            print("Cliente grande incompleto:", r)
            raise SystemExit(3)
        if r.get("kvar_Fijo") in (None, "") and r.get("FP") in (None, ""):
            print("Cliente grande sin kvar_Fijo ni FP:", r.get("LoadID"))
            raise SystemExit(3)

    fixes = []
    if os.path.isfile(catalog):
        fixes = [r for r in read_rows(catalog, "Correcciones") if truthy(r.get("Activo"))]
    else:
        print("AVISO: no hay catálogo:", catalog)

    print("VALIDACION OK")
    print("NetworkID:", ctrl.get("NetworkID"))
    print("Demanda cabecera kW:", ctrl.get("Demanda_Max_Cabecera_kW"))
    print("Clientes grandes activos:", len(clients))
    print("Correcciones activas:", len(fixes))
    print("dry_run:", s.get("dry_run"))
    print("study_path:", s.get("study_path") or "(pendiente para WRITE)")

if __name__ == "__main__":
    main()
