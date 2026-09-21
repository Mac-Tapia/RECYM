# -*- coding: utf-8 -*-
"""
Construye tabla clientes del alimentador:
  suministro + cliente + SED (+ EA/Pot desde clientesimportantes).
"""
from __future__ import print_function
import os
import json
from core.common import load_json, write_csv, require_cympy
from core.feeder_context import load_settings, output_path
from core.cympy_adapter import CymPyAdapter
from core.clientes_suministro import (
    build_feeder_clientes_table, attach_cymdist_loads,
    save_table_csv, save_table_json, list_clientes_importantes_files,
    list_suministro_files,
)
from pipeline.inventory_loads import collect_loads

def _arg(name, default=None):
    import sys
    key = "--" + name
    for i, a in enumerate(sys.argv[1:]):
        if a == key and i + 2 <= len(sys.argv[1:]):
            return sys.argv[i + 2]
        if a.startswith(key + "="):
            return a.split("=", 1)[1]
    return default

def main():
    s = load_settings()
    feeder = s.get("feeder_id")
    ci_file = _arg("clientes-file") or _arg("ci") or s.get("clientes_importantes_file")
    sum_file = _arg("suministro-file") or _arg("sum") or s.get("suministrocliente_file")
    all_feeders = "--all-feeders" in __import__("sys").argv

    print("Suministro disponibles:", ", ".join(list_suministro_files(s)) or "(ninguno)")
    print("Clientes importantes:", ", ".join(list_clientes_importantes_files(s)) or "(ninguno)")
    print("Alimentador:", "ALL" if all_feeders else feeder)
    if not ci_file:
        print("ERROR: indique --clientes-file <nombre.xlsb> o settings.clientes_importantes_file")
        print("Ejemplo: --clientes-file 0326clientesImportantes.xlsb")
        raise SystemExit(2)
    print("Archivo CI seleccionado:", ci_file)

    rows, meta = build_feeder_clientes_table(
        s, feeder, clientes_file=ci_file, suministro_file=sum_file, all_feeders=all_feeders
    )

    # Inventario cargas CYMDIST para mapear SED
    loads = []
    inv_path = output_path(s, "inventory", "loads.json")
    if os.path.isfile(inv_path):
        with open(inv_path, "r", encoding="utf-8") as f:
            loads = (json.load(f).get("loads") or [])
    if not loads and not s.get("dry_run"):
        try:
            api = load_json("config/cympy_api_map.json")
            c = require_cympy(s)
            a = CymPyAdapter(c, api, s)
            a.open_study()
            loads = collect_loads(c, s.get("network_id"))
            os.makedirs(os.path.dirname(inv_path), exist_ok=True)
            with open(inv_path, "w", encoding="utf-8") as f:
                json.dump({"feeder_id": feeder, "loads": loads}, f, ensure_ascii=False, indent=2)
        except Exception as ex:
            print("AVISO inventario cargas:", ex)

    rows = attach_cymdist_loads(rows, loads, primary_only=True)
    meta["n_match_sed"] = sum(1 for r in rows if r.get("Match_SED"))
    meta["n_sin_sed"] = sum(1 for r in rows if not r.get("Match_SED"))

    csv_path = output_path(s, "clientes", "clientes_alimentador.csv")
    json_path = output_path(s, "clientes", "clientes_alimentador.json")
    save_table_csv(csv_path, rows)
    save_table_json(json_path, rows, meta)

    print("Filas:", meta["n_filtrados"], "| con EA/Pot:", meta["n_con_ea_pot"],
          "| match SED:", meta["n_match_sed"], "| sin SED:", meta["n_sin_sed"])
    print(csv_path)
    print(json_path)
    for r in rows[:5]:
        print(" ", r.get("Suministro"), r.get("Cliente"), r.get("SED"),
              "EA=", r.get("EA"), "Pot=", r.get("Pot"), "Load=", r.get("LoadID_CYMDIST"))

if __name__ == "__main__":
    main()
