from __future__ import print_function
from core.common import require_cympy, truthy, load_json
from core.excel_io import read_rows, read_kv
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path

def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    ctrl = read_kv(book, "Control_Proyecto")
    dist = read_kv(book, "Distribucion_Carga")
    clients = [r for r in read_rows(book, "Clientes_Grandes") if truthy(r.get("Activo"))]

    if ctrl.get("Demanda_Max_Cabecera_kW") in (None, ""):
        raise RuntimeError("Falta Demanda_Max_Cabecera_kW en Control_Proyecto")

    Phead = float(ctrl["Demanda_Max_Cabecera_kW"])
    Pfixed = 0.0
    for r in clients:
        if r.get("kW_Fijo") in (None, ""):
            raise RuntimeError("Cliente grande activo sin kW_Fijo: " + str(r.get("LoadID")))
        Pfixed += float(r["kW_Fijo"])

    Pgen = float(ctrl.get("Generacion_Neta_kW") or 0)
    Potros = float(ctrl.get("Otros_Fijos_kW") or 0)
    Pres = Phead - Pfixed - Potros + Pgen
    if Pres < 0:
        raise RuntimeError("La suma de cargas fijas supera la demanda máxima de cabecera.")

    print("[%s] P cabecera objetivo: %s" % (s["feeder_id"], Phead))
    print("P grandes clientes:", Pfixed)
    print("P otros fijos:", Potros)
    print("P generacion neta:", Pgen)
    print("P residual a distribuir:", Pres)
    print("Metodo residual:", dist.get("Metodo_Residual"))
    print("Metodo flujo:", dist.get("Metodo_Flujo"))

    if s.get("dry_run"):
        print("DRY_RUN: no se ejecuta distribución real.")
        return

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.ensure_study()
    try:
        la = c.sim.LoadAllocation()
        try:
            la.SetDemand(float(Pres))
            print("SetDemand residual:", Pres)
        except TypeError:
            print("AVISO: SetDemand no aceptó firma simple; se usa demanda del estudio.")
        a.run_load_allocation()
    except Exception:
        a.run_load_allocation()
    print("LoadAllocation ejecutado.")

if __name__ == "__main__":
    main()
