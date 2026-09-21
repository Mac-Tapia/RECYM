# -*- coding: utf-8 -*-
"""
Aplica EA (kWh) y Pot (kW) de la tabla clientes a SpotLoads CYMDIST por SED.
"""
from __future__ import print_function
import json
import os
from core.common import require_cympy, load_json, write_csv, truthy, run_cympy_main
from core.feeder_context import load_settings, output_path
from core.cympy_adapter import CymPyAdapter
from core.clientes_suministro import build_feeder_clientes_table, attach_cymdist_loads
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

def apply_rows(adapter, rows, fp=0.95, lock=True):
    """
    Escribe EA → casillero Consumo (KWH) y Pot → kW en CYMDIST para filas Activo.
    Verifica relectura de KWH (= energia kWh) con tolerancia.
    Filas desmarcadas (Activo=False / Incluir off): desconecta fisicamente
    la SpotLoad (ConnectionStatus=Disconnected) y pone kWh/kW/kvar=0 Locked,
    para que no entren en LoadAllocation ni LoadFlow.
    """
    report = []
    for r in rows:
        lid = r.get("LoadID_CYMDIST")
        ea = r.get("EA")
        pot = r.get("Pot")
        activo = truthy(r.get("Activo", True))
        if not lid:
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": "", "Estado": "SIN_SED", "EA": ea, "Pot": pot,
                "Activo": activo,
            })
            continue
        if not activo:
            # Sale del alimentador / no actualizar → desconectar en modelo fisico
            try:
                conn = adapter.set_load_connected(lid, False)
                res = adapter.set_load_kwh_and_pot(lid, 0.0, 0.0, fp=fp, lock=True)
                report.append({
                    "Suministro": r.get("Suministro"),
                    "Cliente": r.get("Cliente"),
                    "SED": r.get("SED"),
                    "LoadID": lid,
                    "EA": 0.0,
                    "Pot": 0.0,
                    "KWH_antes": res.get("kwh_before"),
                    "KWH_despues": res.get("kwh_after"),
                    "Estado": "EXCLUIDO",
                    "Activo": False,
                    "ConnectionStatus": conn.get("after"),
                    "Detalle": (
                        "Desmarcada (Incluir): desconectada en modelo fisico "
                        "(ConnectionStatus=Disconnected); P/Q/kWh=0"
                    ),
                })
                print(
                    "EXCLUIDO", lid, "SED", r.get("SED"),
                    "→ Disconnected + 0 kW (Activo=False)",
                )
            except Exception as ex:
                report.append({
                    "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                    "LoadID": lid, "Estado": "ERROR", "Detalle": str(ex),
                    "EA": ea, "Pot": pot, "Activo": False,
                })
                print("ERROR", lid, ex)
            continue
        if ea is None and pot is None:
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": lid, "Estado": "SIN_EA_POT", "EA": ea, "Pot": pot,
                "Activo": True,
            })
            continue
        try:
            conn = adapter.set_load_connected(lid, True)
            res = adapter.set_load_kwh_and_pot(lid, ea, pot, fp=fp, lock=lock)
            kwh_ok = res.get("kwh_ok")
            estado = "OK"
            detalle = "EA→Consumo(KWH); Pot→kW Locked"
            if ea is not None and ea != "" and kwh_ok is False:
                estado = "WARN_KWH"
                detalle = (
                    "Pot OK pero Consumo(KWH) no coincide al releer: "
                    "escrito=%s leido=%s" % (ea, res.get("kwh_after"))
                )
            report.append({
                "Suministro": r.get("Suministro"),
                "Cliente": r.get("Cliente"),
                "SED": r.get("SED"),
                "LoadID": lid,
                "EA": ea,
                "Pot": pot,
                "KWH_antes": res.get("kwh_before"),
                "KWH_despues": res.get("kwh_after"),
                "KWH_ok": kwh_ok,
                "Estado": estado,
                "Activo": True,
                "ConnectionStatus": conn.get("after"),
                "Detalle": detalle,
            })
            print(
                "WRITE", lid, "SED", r.get("SED"),
                "Consumo(KWH)", ea, "→", res.get("kwh_after"),
                "Pot", pot, "Connected", "kwh_ok=", kwh_ok,
            )
        except Exception as ex:
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": lid, "Estado": "ERROR", "Detalle": str(ex),
                "EA": ea, "Pot": pot, "Activo": True,
            })
            print("ERROR", lid, ex)
    return report

def main():
    s = load_settings()
    ci_file = _arg("clientes-file") or _arg("ci") or s.get("clientes_importantes_file")
    sum_file = _arg("suministro-file") or s.get("suministrocliente_file")
    fp = float(_arg("fp", s.get("clientes_fp") or 0.95))

    if not ci_file:
        print("ERROR: indique --clientes-file <nombre.xlsb> o settings.clientes_importantes_file")
        print("Disponibles:", ", ".join(
            __import__("core.clientes_suministro", fromlist=["list_clientes_importantes_files"])
            .list_clientes_importantes_files(s)
        ))
        raise SystemExit(2)

    # Siempre reconstruir con el archivo elegido (no reutilizar tabla de otro mes)
    rows, meta = build_feeder_clientes_table(
        s, s.get("feeder_id"), clientes_file=ci_file, suministro_file=sum_file
    )
    inv_path = output_path(s, "inventory", "loads.json")
    loads = []
    if os.path.isfile(inv_path):
        with open(inv_path, "r", encoding="utf-8") as f:
            loads = json.load(f).get("loads") or []
    if not loads:
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(s)
        a0 = CymPyAdapter(c, api, s)
        a0.open_study()
        loads = collect_loads(c, s.get("network_id"))
    rows = attach_cymdist_loads(rows, loads, primary_only=True)
    from core.clientes_suministro import save_table_json, save_table_csv, ensure_activo, merge_activo, load_saved_clientes_rows
    json_path = output_path(s, "clientes", "clientes_alimentador.json")
    rows = merge_activo(rows, previous_rows=load_saved_clientes_rows(json_path))
    rows = ensure_activo(rows, default=True)
    save_table_json(json_path, rows, meta)
    save_table_csv(output_path(s, "clientes", "clientes_alimentador.csv"), rows)
    print("Cruce con archivo:", ci_file, "| filas", len(rows), "| EA/Pot", meta.get("n_con_ea_pot"),
          "| activos", sum(1 for r in rows if r.get("Activo")),
          "| excluidos", sum(1 for r in rows if not r.get("Activo")))

    if s.get("dry_run"):
        print("DRY_RUN: no se escribe CYMDIST. Filas listas:", len(rows))
        for r in rows:
            print(" DRY", r.get("SED"), r.get("LoadID_CYMDIST"), "EA", r.get("EA"), "Pot", r.get("Pot"))
        return

    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    report = apply_rows(a, rows, fp=fp, lock=True)
    if s.get("save_after_fix", True):
        a.save_study()
        print("Estudio guardado.")

    out = output_path(s, "clientes", "apply_cymdist_report.csv")
    write_csv(
        out, report,
        ["Suministro", "Cliente", "SED", "LoadID", "EA", "Pot", "KWH_antes", "KWH_despues", "KWH_ok", "Estado", "Activo", "Detalle"],
    )
    ok = sum(1 for r in report if r.get("Estado") == "OK")
    excl = sum(1 for r in report if r.get("Estado") == "EXCLUIDO")
    print("Aplicados OK:", ok, "/", len(report), "| Excluidos (Disconnected):", excl)
    print(out)

if __name__ == "__main__":
    run_cympy_main(main)
