# -*- coding: utf-8 -*-
"""
Conecta una SpotLoad concentrada trifasica en el tramo del nodo indicado.
Solo P (kW) + cos φ o Q (kvar). Sin EA/kWh.
SectionID y LoadID se derivan del nodo.
"""
from __future__ import print_function
import json
import os
from core.common import require_cympy, load_json, write_csv, mkdir
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path
from core.spot_load_new import (
    compute_pq,
    load_id_from_section,
    unique_load_id,
    pick_section_for_node,
    filter_nodes,
    sanitize_load_name,
)
from pipeline.inventory_nodes import (
    collect_nodes_sections,
    save_inventory,
    load_inventory,
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


def _strip_qid(v):
    s = str(v or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')):
        s = s[1:-1].strip()
    return s


def get_topology(settings, refresh=False, adapter=None):
    """Inventario nodos/tramos (cache JSON o CYMDIST)."""
    data, path = load_inventory(settings)
    if data and not refresh:
        # Sanear caches antiguos con comillas literales en FromNode/ToNode
        for sec in data.get("sections") or []:
            sec["FromNode"] = _strip_qid(sec.get("FromNode"))
            sec["ToNode"] = _strip_qid(sec.get("ToNode"))
            sec["SectionID"] = _strip_qid(sec.get("SectionID"))
        for n in data.get("nodes") or []:
            n["NodeID"] = _strip_qid(n.get("NodeID"))
        by_node = {}
        for sec in data.get("sections") or []:
            for key in ("FromNode", "ToNode"):
                nid = _strip_qid(sec.get(key))
                if nid:
                    by_node.setdefault(nid, []).append(sec)
        for n in data.get("nodes") or []:
            linked = by_node.get(n["NodeID"]) or []
            n["n_sections"] = len(linked)
            n["sections"] = [s["SectionID"] for s in linked]
        data["by_node"] = by_node
        return data, path

    if adapter is None:
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(settings)
        adapter = CymPyAdapter(c, api, settings)
        adapter.open_study()
    data = collect_nodes_sections(adapter.cympy, settings.get("network_id"))
    path = save_inventory(settings, data)
    return data, path


def search_nodes(settings, query="", limit=80, refresh=False):
    """Busca nodos usando inventario saneado (n_sections correcto)."""
    if refresh:
        topo, _ = get_topology(settings, refresh=True)
        return filter_nodes(topo.get("nodes") or [], query, limit=limit)
    data, path = load_inventory(settings)
    if not data:
        return []
    # Reusar saneado de get_topology (comillas en From/To de caches viejos)
    topo, _ = get_topology(settings, refresh=False)
    return filter_nodes(topo.get("nodes") or [], query, limit=limit)



def resolve_connection(topo, node_id, existing_load_ids=None, load_name=None):
    """Deriva SectionID + LoadID desde el nodo.

    load_name: nombre a dibujar en CYMDIST (= DeviceNumber). Si se indica,
    se usa ese ID (sanitizado). Si ya existe, se actualiza (no crea _2).
    """
    nid = str(node_id or "").strip()
    if not nid:
        raise ValueError("Indique NodeID.")
    node_ids = {str(n.get("NodeID")) for n in (topo.get("nodes") or [])}
    if node_ids and nid not in node_ids:
        raise ValueError("Nodo no encontrado en inventario: %s" % nid)

    linked = (topo.get("by_node") or {}).get(nid) or []
    if not linked:
        linked = [
            s for s in (topo.get("sections") or [])
            if str(s.get("FromNode")) == nid or str(s.get("ToNode")) == nid
        ]
    sec = pick_section_for_node(nid, linked)
    if not sec:
        raise ValueError("El nodo %s no tiene tramos asociados." % nid)
    section_id = str(sec["SectionID"])
    custom = sanitize_load_name(load_name)
    if custom:
        load_id = custom
    else:
        base = load_id_from_section(section_id, nid)
        existing = set(str(x) for x in (existing_load_ids or []))
        if base in existing:
            load_id = base
        else:
            load_id = unique_load_id(base, existing_load_ids or [])
    return {
        "NodeID": nid,
        "SectionID": section_id,
        "LoadID": load_id,
        "LoadName": custom or load_id,
        "FromNode": sec.get("FromNode"),
        "ToNode": sec.get("ToNode"),
        "n_sections": len(linked),
        "section_candidates": [str(s.get("SectionID")) for s in linked],
    }


def connect_spot_load(settings, node_id, mode, p_kw, q_kvar=None, cosfi=None,
                      refresh_topo=False, lock=True, adapter=None, load_name=None,
                      recreate=True):
    """Resuelve nodo -> tramo/ID y crea SpotLoad trifasica con P/Q.

    load_name: nombre dibujado en el plano (= DeviceNumber en CYMDIST).
    recreate: borra y vuelve a crear para forzar simbolo en el esquema.
    """
    p, q, fp = compute_pq(mode, p_kw, q_kvar=q_kvar, cosfi=cosfi)

    own_adapter = adapter is None
    if adapter is None and not settings.get("dry_run"):
        # Pausar CYMDIST GUI si esta abierto (sesion §§2–5) para escritura CymPy
        try:
            from core.cymdist_com import pause_cymdist_for_cympy, is_keep_open
            if is_keep_open(settings):
                pause_cymdist_for_cympy(settings)
        except Exception as ex:
            print("AVISO pause_cymdist:", ex)
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(settings)
        adapter = CymPyAdapter(c, api, settings)
        adapter.open_study()

    topo, topo_path = get_topology(settings, refresh=refresh_topo, adapter=adapter)

    existing_ids = []
    if adapter is not None:
        try:
            existing_ids = [
                str(r.get("LoadID"))
                for r in collect_loads(adapter.cympy, settings.get("network_id"))
            ]
        except Exception:
            existing_ids = []
    else:
        inv = output_path(settings, "inventory", "loads.json")
        if os.path.isfile(inv):
            try:
                with open(inv, "r", encoding="utf-8") as f:
                    existing_ids = [
                        str(r.get("LoadID"))
                        for r in (json.load(f).get("loads") or [])
                    ]
            except Exception:
                pass

    resolved = resolve_connection(
        topo, node_id, existing_ids, load_name=load_name
    )
    result = {
        "ok": True,
        "feeder_id": settings.get("feeder_id"),
        "network_id": settings.get("network_id"),
        "mode": (mode or "KW_COSFI").upper(),
        "P_kW": p,
        "Q_kvar": q,
        "cosfi": fp,
        "phases": "ABC",
        "tipo": "SpotLoad",
        "topo_path": topo_path,
        "dry_run": bool(settings.get("dry_run")),
        "Nombre": resolved.get("LoadName") or resolved.get("LoadID"),
    }
    result.update(resolved)

    if settings.get("dry_run"):
        result["Estado"] = "DRY_RUN"
        result["created"] = True
        return result

    write = adapter.add_spot_load(
        resolved["LoadID"],
        resolved["SectionID"],
        p,
        q,
        lock=lock,
        phases="ABC",
        node_id=resolved.get("NodeID"),
        from_node=resolved.get("FromNode"),
        to_node=resolved.get("ToNode"),
        recreate=bool(recreate),
        stub=False,
    )
    result.update(write)
    if write.get("StubSectionID"):
        result["SectionID"] = write["StubSectionID"]
    result["Estado"] = "OK" if write.get("created") or write.get("pq_after") else "OK_UPDATE"
    if settings.get("save_after_write", True) and own_adapter:
        adapter.save_study()
        result["saved"] = True
        # Liberar .zxst antes de abrir CYMDIST por COM
        try:
            adapter.close_study(save=False)
        except Exception:
            pass

    # Abrir CYMDIST (API COM) en el mismo estudio e insertar/asegurar SpotLoad
    # con el nombre asignado en el nodo/tramo — deja Cyme visible.
    try:
        from core.cymdist_com import (
            add_spot_load_com, pause_cymdist_for_cympy, resume_cymdist_gui,
        )
        com = add_spot_load_com(
            settings,
            load_id=result.get("LoadID") or resolved.get("LoadID"),
            section_id=result.get("SectionID") or resolved.get("SectionID"),
            location=result.get("Location") or "From",
            node_id=resolved.get("NodeID"),
            from_node=resolved.get("FromNode"),
            to_node=resolved.get("ToNode"),
            show_window=True,
            leave_open=True,
            kill_existing=True,  # evita bloqueo del .zxst por otra sesion
        )
        result["com"] = com
        if com.get("ok"):
            result["cymdist_open"] = True
            if com.get("Location"):
                result["Location"] = com["Location"]
            result["Estado"] = "OK"
            # COM puede recrear el dispositivo y dejar P/Q en 0: reescribir
            # trifasico → monofasico (A/B/C = P/3, Q/3) via CymPy.
            try:
                pause_cymdist_for_cympy(settings)
                api = load_json("config/cympy_api_map.json")
                c2 = require_cympy(settings)
                a2 = CymPyAdapter(c2, api, settings)
                a2.open_study()
                before2, after2 = a2.set_load_pq(
                    result.get("LoadID") or resolved.get("LoadID"),
                    p, q, lock=lock,
                )
                a2.save_study()
                try:
                    a2.close_study(save=False)
                except Exception:
                    pass
                result["pq_reapplied"] = True
                result["pq_after"] = after2
                result["pq_per_phase_kW"] = float(p) / 3.0
                result["pq_per_phase_kvar"] = float(q) / 3.0
                print(
                    "P/Q reaplicado por fase:",
                    round(float(p) / 3.0, 5), "kW /",
                    round(float(q) / 3.0, 5), "kvar × 3",
                )
                resume_cymdist_gui(settings, reason="spot_load_pq:%s" % (
                    result.get("LoadID") or ""
                ))
            except Exception as ex_pq:
                result["pq_reapply_error"] = str(ex_pq)
                print("AVISO reaplicar P/Q tras COM:", ex_pq)
                try:
                    resume_cymdist_gui(settings, reason="spot_load_pq_error")
                except Exception:
                    pass
            # Mantener CYMDIST abierto para §§4–5 (flujos e informes)
            try:
                from pipeline.run_demand_allocation import load_session, save_session
                sess = load_session(settings)
                sess["cymdist_keep_open"] = True
                sess["last_spot_load"] = result.get("LoadID")
                save_session(settings, sess)
            except Exception as ex:
                print("AVISO session cymdist_keep_open:", ex)
        else:
            result["com_error"] = com.get("error")
            result["aviso_com"] = (
                "CymPy OK pero no se pudo abrir/insertar por COM: %s" % com.get("error")
            )
    except Exception as ex:
        result["com_error"] = str(ex)
        result["aviso_com"] = "CymPy OK pero fallo apertura CYMDIST COM: %s" % ex

    return result


def append_report(settings, row):
    out = output_path(settings, "loads", "new_spot_loads_report.csv")
    mkdir(os.path.dirname(out))
    headers = [
        "NodeID", "SectionID", "LoadID", "Nombre", "Location", "P_kW", "Q_kvar", "cosfi",
        "phases", "Estado", "created", "dry_run",
    ]
    rows = []
    if os.path.isfile(out):
        try:
            import csv
            with open(out, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except Exception:
            rows = []
    rows.append({h: row.get(h, "") for h in headers})
    write_csv(out, rows, headers)
    return out


def list_connected_spot_loads(settings):
    """
    Cargas nuevas del §3 (reporte CSV), una entrada por LoadID (la ultima gana).
    Solo filas OK (no DRY_RUN / error). Usadas como Locked fuera de LoadAllocation.
    """
    path = output_path(settings, "loads", "new_spot_loads_report.csv")
    if not os.path.isfile(path):
        return []
    by_id = {}
    try:
        import csv
        with open(path, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                lid = str(r.get("LoadID") or "").strip()
                if not lid:
                    continue
                estado = str(r.get("Estado") or "").upper()
                if "DRY" in estado or estado.startswith("ERR") or estado in ("FAIL", "ERROR"):
                    continue
                try:
                    p = float(str(r.get("P_kW") or "0").replace(",", "."))
                    q = float(str(r.get("Q_kvar") or "0").replace(",", "."))
                except Exception:
                    continue
                by_id[lid] = {
                    "LoadID": lid,
                    "NodeID": r.get("NodeID"),
                    "SectionID": r.get("SectionID"),
                    "P_kW": p,
                    "Q_kvar": q,
                    "cosfi": r.get("cosfi"),
                    "Estado": r.get("Estado"),
                }
    except Exception:
        return []
    return list(by_id.values())


def new_loads_as_fixed(settings):
    """Formato apply_fixed_loads: cargas §3 Locked, fuera de prorrateo."""
    rows = []
    for r in list_connected_spot_loads(settings):
        rows.append({
            "Activo": True,
            "LoadID": r["LoadID"],
            "kW_Fijo": r["P_kW"],
            "kvar_Fijo": r["Q_kvar"],
            "FP": r.get("cosfi") or "",
            "Fuente": "nueva_spotload",
        })
    return rows


def main():
    s = load_settings()
    node = _arg("node") or _arg("nodo")
    if not node:
        print("Uso: add_spot_load.py --node <NodeID> --p <kW> (--cosfi 0.95 | --q <kvar>)")
        raise SystemExit(2)
    mode = _arg("mode") or ("KW_KVAR" if _arg("q") is not None else "KW_COSFI")
    res = connect_spot_load(
        s,
        node,
        mode,
        _arg("p") or _arg("kw"),
        q_kvar=_arg("q") or _arg("kvar"),
        cosfi=_arg("cosfi") or _arg("fp") or 0.95,
        refresh_topo=True,
    )
    report = append_report(s, res)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    print("Reporte:", report)


if __name__ == "__main__":
    main()
