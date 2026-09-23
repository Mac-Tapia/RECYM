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

def _lid_from_row(r):
    return str(r.get("LoadID_CYMDIST") or r.get("LoadID") or "").strip()


def previous_applied_load_ids(settings):
    """LoadIDs que ya se escribieron en CYMDIST (reporte 3.2 o tabla guardada)."""
    ids = set()
    rep = output_path(settings, "clientes", "apply_cymdist_report.csv")
    if os.path.isfile(rep):
        try:
            import csv
            with open(rep, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    lid = str(row.get("LoadID") or "").strip()
                    st = str(row.get("Estado") or "").upper()
                    if lid and st in ("OK", "WARN_KWH", "EXCLUIDO"):
                        ids.add(lid)
        except Exception:
            pass
    json_path = output_path(settings, "clientes", "clientes_alimentador.json")
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for r in data.get("rows") or []:
                if r.get("Origen") == "inventario_spotload":
                    continue
                lid = _lid_from_row(r)
                if lid and r.get("Match_SED"):
                    ids.add(lid)
        except Exception:
            pass
    return ids


def keep_load_ids_from_rows(rows, solo_activos=True):
    """LoadIDs que deben permanecer como clientes importantes tras 3.1/3.2."""
    keep = set()
    for r in rows or []:
        if solo_activos and not truthy(r.get("Activo", True)):
            continue
        if r.get("Origen") == "inventario_spotload":
            continue
        lid = _lid_from_row(r)
        if lid and (r.get("Match_SED") or r.get("SED")):
            keep.add(lid)
    return keep


def release_clientes_loads(adapter, load_ids, reconnect=True):
    """Libera SED de clientes previos: Unlocked + KWH/kW=0 (anti-saturación).

    No borra SpotLoad; solo limpia casilleros que 3.2 había escrito como Locked.
    """
    n_ok = n_err = 0
    details = []
    for lid in sorted(set(str(x) for x in (load_ids or []) if x)):
        try:
            if reconnect:
                try:
                    adapter.set_load_connected(lid, True)
                except Exception:
                    pass
            adapter.set_load_kwh_and_pot(lid, 0.0, 0.0, fp=0.95, lock=False)
            try:
                adapter.set_load_lock(lid, False)
            except Exception:
                pass
            n_ok += 1
            details.append({"LoadID": lid, "Estado": "LIBERADO"})
        except Exception as ex:
            n_err += 1
            details.append({"LoadID": lid, "Estado": "ERROR", "Detalle": str(ex)})
    return {"ok": n_err == 0, "n_liberados": n_ok, "n_error": n_err, "rows": details}


def refresh_clientes_in_cymdist(adapter, rows, fp=0.95, previous_ids=None):
    """Al re-pulsar 3.2: libera CI viejos fuera de la tabla y escribe los actuales.

    Evita saturación: SED que ya no están en clientesimportantes quedan
    Unlocked/0; las incluidas se sobrescriben con EA/Pot nuevos.
    """
    keep = keep_load_ids_from_rows(rows, solo_activos=True)
    prev = set(previous_ids or [])
    stale = prev - keep
    # También liberar excluidas actuales (Activo=False) vía apply_rows;
    # aquí solo las que salieron del cruce.
    released = {"n_liberados": 0, "n_error": 0, "rows": []}
    if stale:
        released = release_clientes_loads(adapter, stale, reconnect=True)
        print(
            "[3.2] liberados previos fuera de tabla:",
            released.get("n_liberados"),
            "stale=",
            len(stale),
        )
    report = apply_rows(adapter, rows, fp=fp, lock=True)
    return report, released, keep


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
            # Incluir off: primero poner 0 (aun Connected), luego desconectar.
            # Escribir KWH/kW sobre CustomerLoad ya Disconnected provoca Access
            # Violation 0xc0000005 en Cyme 9.2.
            try:
                res = {"kwh_before": None, "kwh_after": None}
                try:
                    res = adapter.set_load_kwh_and_pot(lid, 0.0, 0.0, fp=fp, lock=True)
                except Exception as ex_z:
                    print("AVISO zero pre-desconexion", lid, ex_z)
                conn = {"after": None}
                try:
                    conn = adapter.set_load_connected(lid, False)
                except Exception as ex_d:
                    print("AVISO desconexion", lid, ex_d)
                    conn = {"after": "ERROR:%s" % ex_d}
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
                        "Desmarcada (Incluir): P/Q/kWh=0 luego "
                        "ConnectionStatus=Disconnected"
                    ),
                })
                print(
                    "EXCLUIDO", lid, "SED", r.get("SED"),
                    "→ 0 kW + Disconnected (Activo=False)",
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
            # Dibujo + capacidad: no bloquean aunque S > ConnectedKVA (260044)
            try:
                adapter._ensure_spot_symbol(lid)
            except Exception:
                pass
            try:
                adapter.raise_load_connected_kva(lid)
            except Exception:
                pass
            kwh_ok = res.get("kwh_ok")
            estado = "OK"
            detalle = "EA→Consumo(KWH); Pot→kW Locked; símbolo dibujado"
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
    from core.clientes_suministro import (
        save_table_json, save_table_csv, ensure_activo, merge_activo,
        ensure_restar_cabecera, merge_restar_cabecera, load_saved_clientes_rows,
    )
    json_path = output_path(s, "clientes", "clientes_alimentador.json")
    prev = load_saved_clientes_rows(json_path)
    rows = merge_activo(rows, previous_rows=prev)
    rows = ensure_activo(rows, default=True)
    rows = merge_restar_cabecera(rows, previous_rows=prev)
    rows = ensure_restar_cabecera(rows, default=False)
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
    prev_ids = previous_applied_load_ids(s)
    report, released, _keep = refresh_clientes_in_cymdist(
        a, rows, fp=fp, previous_ids=prev_ids
    )
    try:
        from pipeline.run_demand_allocation import adjust_cabecera_for_excluidas
        cab_adj = adjust_cabecera_for_excluidas(
            s, rows, cympy=c, write_cymdist=True
        )
        print("[3.2 CLI] cabecera vs excluidas:", cab_adj.get("msg") or cab_adj)
    except Exception as ex_cab:
        print("AVISO ajuste cabecera excluidas:", ex_cab)
    if s.get("save_after_write", True) or s.get("save_after_fix", True):
        a.save_study()
        print("Estudio guardado.")
    if (released or {}).get("n_liberados"):
        print("Liberados previos:", released.get("n_liberados"))
    # Al recargar otros EA/Pot, 3.3 debe rehacer locks (no reusar sello viejo)
    try:
        from pipeline.run_demand_allocation import load_session, save_session
        sess = load_session(s)
        sess["alloc_locks_ready"] = False
        sess.pop("alloc_locks_fixed_key", None)
        save_session(s, sess)
    except Exception:
        pass

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
