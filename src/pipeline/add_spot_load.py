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
    """Busca nodos usando inventario (cache). Si no hay cache, lo genera una vez."""
    data, _path = load_inventory(settings)
    if refresh or not data:
        topo, _ = get_topology(settings, refresh=True)
        return filter_nodes(topo.get("nodes") or [], query, limit=limit)
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
                      recreate=True, open_gui=True, save=True):
    """Resuelve nodo -> tramo/ID y crea SpotLoad trifasica con P/Q.

    load_name: nombre dibujado en el plano (= DeviceNumber en CYMDIST).
    recreate: borra y vuelve a crear para forzar simbolo en el esquema.
    open_gui: abrir CYMDIST al final (False en lote; se abre una sola vez).
    save: guardar estudio (False en lote intermedio; se guarda al final).
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
    if settings.get("save_after_write", True) and own_adapter and save:
        adapter.save_study()
        result["saved"] = True
        # Liberar .zxst antes de abrir la GUI
        try:
            adapter.close_study(save=False)
        except Exception:
            pass

    # Abrir CYMDIST una sola vez para ver el simbolo.
    # Evitar el ciclo kill→COM→kill→CymPy→resume (provoca 0xC0000005 en Cyme.exe).
    use_com = bool(settings.get("spot_load_use_com"))
    if open_gui and use_com:
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
                kill_existing=True,
            )
            result["com"] = com
            if com.get("ok"):
                result["cymdist_open"] = True
                if com.get("Location"):
                    result["Location"] = com["Location"]
                result["Estado"] = "OK"
                # COM puede recrear el dispositivo y dejar P/Q en 0: reescribir
                try:
                    pause_cymdist_for_cympy(settings)
                    api = load_json("config/cympy_api_map.json")
                    c2 = require_cympy(settings)
                    a2 = CymPyAdapter(c2, api, settings)
                    a2.open_study(force_backup=False)
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
            else:
                result["com_error"] = com.get("error")
                result["aviso_com"] = (
                    "CymPy OK pero no se pudo abrir/insertar por COM: %s" % com.get("error")
                )
        except Exception as ex:
            result["com_error"] = str(ex)
            result["aviso_com"] = "CymPy OK pero fallo apertura CYMDIST COM: %s" % ex
    elif open_gui:
        # Camino robusto (default): CymPy ya escribio SpotLoad+P/Q.
        # Un solo ciclo: pause (kill si hacia falta) → open GUI (sin recrear COM).
        try:
            from core.cymdist_com import pause_cymdist_for_cympy, open_cymdist_gui
            reason = "spot_load:%s" % (result.get("LoadID") or "")
            pause_cymdist_for_cympy(settings)  # libera .zxst si Cyme tenia el estudio
            gui = open_cymdist_gui(settings, kill_existing=False, reason=reason)
            result["com"] = gui
            result["cymdist_open"] = bool(gui.get("ok") or gui.get("cymdist_open"))
            if gui.get("ok"):
                result["Estado"] = "OK"
            else:
                result["aviso_com"] = (
                    "SpotLoad en .zxst; GUI no abrio: %s" % gui.get("error")
                )
            result["pq_per_phase_kW"] = float(p) / 3.0
            result["pq_per_phase_kvar"] = float(q) / 3.0
        except Exception as ex:
            result["com_error"] = str(ex)
            result["aviso_com"] = (
                "SpotLoad guardada en .zxst; abra CYMDIST manualmente si no se inicio: %s" % ex
            )
    else:
        result["pq_per_phase_kW"] = float(p) / 3.0
        result["pq_per_phase_kvar"] = float(q) / 3.0

    # Mantener CYMDIST abierto para §§4–5 (flujos e informes)
    if open_gui:
        try:
            from pipeline.run_demand_allocation import load_session, save_session
            sess = load_session(settings)
            sess["cymdist_keep_open"] = True
            sess["cymdist_keep_open_reason"] = "spot_load"
            sess["last_spot_load"] = result.get("LoadID")
            save_session(settings, sess)
        except Exception as ex:
            print("AVISO session cymdist_keep_open:", ex)

    return result


# Columnas de plantilla §4 lote (CSV/Excel)
SPOT_LOAD_BATCH_HEADERS = [
    "Accion", "NodeID", "Nombre", "Modo", "P_kW", "Q_kvar", "cosfi", "Cliente", "Notas",
]
SPOT_LOAD_BATCH_SAMPLE = [
    {
        "Accion": "NUEVA",
        "NodeID": "16955",
        "Nombre": "CARGA_CLIENTE_01",
        "Modo": "KW_COSFI",
        "P_kW": "150",
        "Q_kvar": "",
        "cosfi": "0.95",
        "Cliente": "Ejemplo SA",
        "Notas": "Completar NodeID real del alimentador",
    },
    {
        "Accion": "ACTUALIZAR",
        "NodeID": "17001",
        "Nombre": "CARGA_CLIENTE_02",
        "Modo": "KW_KVAR",
        "P_kW": "80",
        "Q_kvar": "26.3",
        "cosfi": "",
        "Cliente": "Otro cliente",
        "Notas": "Actualiza P/Q si ya existe el DeviceNumber",
    },
]


def _norm_header(h):
    s = str(h or "").strip().lower()
    for a, b in (
        ("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"),
    ):
        s = s.replace(a, b)
    return s.replace(" ", "_").replace("-", "_")


_BATCH_ALIASES = {
    "accion": "Accion",
    "action": "Accion",
    "tipo": "Accion",
    "nodeid": "NodeID",
    "node_id": "NodeID",
    "nodo": "NodeID",
    "nombre": "Nombre",
    "load_name": "Nombre",
    "loadid": "Nombre",
    "load_id": "Nombre",
    "devicenumber": "Nombre",
    "modo": "Modo",
    "mode": "Modo",
    "p_kw": "P_kW",
    "p": "P_kW",
    "kw": "P_kW",
    "potencia": "P_kW",
    "potencia_kw": "P_kW",
    "q_kvar": "Q_kvar",
    "q": "Q_kvar",
    "kvar": "Q_kvar",
    "cosfi": "cosfi",
    "cos_fi": "cosfi",
    "cosphi": "cosfi",
    "fp": "cosfi",
    "factor_potencia": "cosfi",
    "cliente": "Cliente",
    "notas": "Notas",
    "nota": "Notas",
}


def normalize_batch_row(raw, row_index=0):
    """Normaliza una fila de plantilla a dict canónico + validación suave."""
    mapped = {}
    for k, v in (raw or {}).items():
        key = _BATCH_ALIASES.get(_norm_header(k))
        if key:
            mapped[key] = v
    accion = str(mapped.get("Accion") or "NUEVA").strip().upper()
    if accion in ("UPDATE", "ACTUALIZA", "UPDATEAR", "UPD"):
        accion = "ACTUALIZAR"
    elif accion in ("NEW", "CREATE", "CREAR", ""):
        accion = "NUEVA"
    modo = str(mapped.get("Modo") or "KW_COSFI").strip().upper()
    if modo in ("P+COS", "P_COS", "COSFI", "KW+COSFI", "P+COSF"):
        modo = "KW_COSFI"
    elif modo in ("P+Q", "KW+KVAR", "PQ"):
        modo = "KW_KVAR"
    node_id = str(mapped.get("NodeID") or "").strip()
    nombre = str(mapped.get("Nombre") or "").strip()
    row = {
        "row": int(row_index) + 1,
        "Accion": accion,
        "NodeID": node_id,
        "Nombre": nombre,
        "Modo": modo if modo in ("KW_COSFI", "KW_KVAR") else "KW_COSFI",
        "P_kW": mapped.get("P_kW"),
        "Q_kvar": mapped.get("Q_kvar"),
        "cosfi": mapped.get("cosfi") if mapped.get("cosfi") not in (None, "") else "0.95",
        "Cliente": str(mapped.get("Cliente") or "").strip(),
        "Notas": str(mapped.get("Notas") or "").strip(),
    }
    errors = []
    if not node_id:
        errors.append("Falta NodeID")
    if not nombre:
        errors.append("Falta Nombre (DeviceNumber)")
    try:
        if row["P_kW"] in (None, ""):
            errors.append("Falta P_kW")
        else:
            float(str(row["P_kW"]).replace(",", "."))
    except Exception:
        errors.append("P_kW inválido")
    if row["Modo"] == "KW_KVAR":
        if row["Q_kvar"] in (None, ""):
            errors.append("Falta Q_kvar (modo KW_KVAR)")
    else:
        try:
            fp = float(str(row["cosfi"]).replace(",", "."))
            if fp <= 0 or fp > 1:
                errors.append("cosfi fuera de rango (0.01–1)")
        except Exception:
            errors.append("cosfi inválido")
    row["ok"] = not errors
    row["errors"] = errors
    return row


def parse_batch_file(path_or_bytes, filename=""):
    """Lee CSV o Excel de plantilla SpotLoad → lista de filas normalizadas."""
    import csv
    import io as _io

    name = (filename or "").lower()
    raw_rows = []

    if hasattr(path_or_bytes, "read"):
        data = path_or_bytes.read()
        path_or_bytes = data

    if isinstance(path_or_bytes, bytes):
        bio = _io.BytesIO(path_or_bytes)
        if name.endswith((".xlsx", ".xlsm")) or (
            len(path_or_bytes) >= 2 and path_or_bytes[:2] == b"PK"
        ):
            from openpyxl import load_workbook
            wb = load_workbook(bio, read_only=True, data_only=True)
            ws = wb["Cargas"] if "Cargas" in wb.sheetnames else wb.active
            rows_iter = ws.iter_rows(values_only=True)
            headers = [str(c or "").strip() for c in next(rows_iter)]
            for vals in rows_iter:
                if vals is None or all(v is None or str(v).strip() == "" for v in vals):
                    continue
                raw_rows.append({headers[i]: vals[i] for i in range(len(headers)) if i < len(vals)})
            wb.close()
        else:
            text = path_or_bytes.decode("utf-8-sig")
            reader = csv.DictReader(_io.StringIO(text))
            raw_rows = list(reader)
    else:
        path = str(path_or_bytes)
        low = path.lower()
        if low.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=True)
            ws = wb["Cargas"] if "Cargas" in wb.sheetnames else wb.active
            rows_iter = ws.iter_rows(values_only=True)
            headers = [str(c or "").strip() for c in next(rows_iter)]
            for vals in rows_iter:
                if vals is None or all(v is None or str(v).strip() == "" for v in vals):
                    continue
                raw_rows.append({headers[i]: vals[i] for i in range(len(headers)) if i < len(vals)})
            wb.close()
        else:
            with open(path, "r", encoding="utf-8-sig") as f:
                raw_rows = list(csv.DictReader(f))

    rows = []
    for i, raw in enumerate(raw_rows):
        row = normalize_batch_row(raw, i)
        # Omitir filas de ejemplo vacías / placeholder puro si el usuario no las tocó
        if not row["NodeID"] and not row["Nombre"]:
            continue
        rows.append(row)
    return rows


def build_batch_template_csv():
    """Bytes CSV (utf-8-sig) de plantilla con filas de ejemplo."""
    import csv
    import io as _io
    buf = _io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SPOT_LOAD_BATCH_HEADERS, lineterminator="\n")
    w.writeheader()
    for r in SPOT_LOAD_BATCH_SAMPLE:
        w.writerow(r)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def build_batch_template_xlsx():
    """Bytes XLSX de plantilla con hoja Instrucciones + Cargas."""
    import io as _io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws_i = wb.active
    ws_i.title = "Instrucciones"
    lines = [
        "Plantilla RECYM §4 — SpotLoad en bloque",
        "",
        "1) Complete la hoja «Cargas» (una fila por cliente).",
        "2) Accion = NUEVA (crear) o ACTUALIZAR (reaplicar P/Q si ya existe el Nombre).",
        "3) NodeID = nodo existente del alimentador activo (no se crean nodos).",
        "4) Nombre = DeviceNumber dibujado en CYMDIST (sin espacios raros).",
        "5) Modo = KW_COSFI (P + cosφ) o KW_KVAR (P + Q).",
        "6) Guarde y suba el archivo en la UI → Conectar en bloque.",
        "",
        "P trifásica → en CYMDIST A/B/C = P/3 y Q/3. Locked (fuera de distribución).",
    ]
    for i, line in enumerate(lines, 1):
        ws_i.cell(row=i, column=1, value=line)
        if i == 1:
            ws_i.cell(row=i, column=1).font = Font(bold=True, size=14)
    ws_i.column_dimensions["A"].width = 90

    ws = wb.create_sheet("Cargas")
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0F766E")
    thin = Border(
        left=Side(style="thin", color="CCCCCC"),
        right=Side(style="thin", color="CCCCCC"),
        top=Side(style="thin", color="CCCCCC"),
        bottom=Side(style="thin", color="CCCCCC"),
    )
    for col, h in enumerate(SPOT_LOAD_BATCH_HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin
    for i, r in enumerate(SPOT_LOAD_BATCH_SAMPLE, 2):
        for col, h in enumerate(SPOT_LOAD_BATCH_HEADERS, 1):
            cell = ws.cell(row=i, column=col, value=r.get(h, ""))
            cell.border = thin
    widths = [12, 12, 22, 12, 10, 10, 8, 18, 36]
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    out = _io.BytesIO()
    wb.save(out)
    return out.getvalue()


def list_pending_spot_loads(settings):
    """
    Cargas §4 pendientes o fallidas (no OK) del reporte, más última versión por Nombre.
    Útil para reintentar las que no se actualizaron a tiempo.
    """
    import csv
    path = output_path(settings, "loads", "new_spot_loads_report.csv")
    by_key = {}
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                lid = str(r.get("LoadID") or r.get("Nombre") or "").strip()
                if not lid:
                    continue
                estado = str(r.get("Estado") or "").upper()
                okish = estado in ("OK", "OK_UPDATE", "OK_INV", "OK_SESSION") or (
                    estado and "OK" in estado and "ERR" not in estado and "DRY" not in estado
                )
                by_key[lid] = {
                    "LoadID": lid,
                    "Nombre": r.get("Nombre") or lid,
                    "NodeID": r.get("NodeID") or "",
                    "SectionID": r.get("SectionID") or "",
                    "P_kW": r.get("P_kW"),
                    "Q_kvar": r.get("Q_kvar"),
                    "cosfi": r.get("cosfi"),
                    "Estado": r.get("Estado") or "",
                    "pending": not okish,
                }
    except Exception:
        return []
    return [v for v in by_key.values() if v.get("pending")]


def _upsert_inventory_load(settings, result):
    """Actualiza inventory/loads.json con una SpotLoad §4."""
    if not result.get("LoadID"):
        return
    try:
        inv = output_path(settings, "inventory", "loads.json")
        loads = []
        if os.path.isfile(inv):
            with open(inv, "r", encoding="utf-8") as f:
                loads = json.load(f).get("loads") or []
        loads = [r for r in loads if str(r.get("LoadID")) != str(result.get("LoadID"))]
        loads.append({
            "LoadID": result.get("LoadID"),
            "Tipo": "SpotLoad",
            "SectionID": result.get("SectionID"),
            "kW": str(result.get("P_kW")),
            "kvar": str(result.get("Q_kvar")),
            "LoadValueType": "LoadValueKW_KVAR",
            "ZoneID": "",
            "Label": "%s (SpotLoad)" % result.get("LoadID"),
        })
        mkdir(os.path.dirname(inv))
        with open(inv, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "feeder_id": settings.get("feeder_id"),
                    "network_id": settings.get("network_id"),
                    "loads": loads,
                },
                f, indent=2, ensure_ascii=False,
            )
    except Exception as ex:
        print("AVISO inventory SpotLoad:", ex)


def connect_spot_loads_bulk(settings, rows, open_gui=True):
    """
    Conecta/actualiza varias SpotLoad en una sola apertura de estudio.
    rows: lista ya normalizada (normalize_batch_row / parse_batch_file).
    """
    valid = [r for r in (rows or []) if r.get("ok")]
    skipped = [r for r in (rows or []) if not r.get("ok")]
    results = []
    if not valid:
        return {
            "ok": False,
            "error": "No hay filas válidas para conectar.",
            "n_ok": 0,
            "n_error": 0,
            "n_skipped": len(skipped),
            "skipped": skipped,
            "results": [],
        }

    adapter = None
    if not settings.get("dry_run"):
        try:
            from core.cymdist_com import pause_cymdist_for_cympy, is_keep_open
            if is_keep_open(settings):
                pause_cymdist_for_cympy(settings)
        except Exception as ex:
            print("AVISO pause_cymdist bulk:", ex)
        api = load_json("config/cympy_api_map.json")
        c = require_cympy(settings)
        adapter = CymPyAdapter(c, api, settings)
        adapter.open_study()

    n_ok = 0
    n_err = 0
    last_ok = None
    for row in valid:
        try:
            res = connect_spot_load(
                settings,
                row["NodeID"],
                row.get("Modo") or "KW_COSFI",
                row.get("P_kW"),
                q_kvar=row.get("Q_kvar"),
                cosfi=row.get("cosfi"),
                refresh_topo=False,
                lock=True,
                adapter=adapter,
                load_name=row.get("Nombre"),
                recreate=True,
                open_gui=False,
                save=False,
            )
            res["Accion"] = row.get("Accion")
            res["Cliente"] = row.get("Cliente")
            res["row"] = row.get("row")
            append_report(settings, res)
            _upsert_inventory_load(settings, res)
            results.append(res)
            n_ok += 1
            last_ok = res
        except Exception as ex:
            n_err += 1
            fail = {
                "ok": False,
                "row": row.get("row"),
                "NodeID": row.get("NodeID"),
                "Nombre": row.get("Nombre"),
                "Accion": row.get("Accion"),
                "Estado": "ERROR",
                "error": str(ex),
            }
            try:
                append_report(settings, fail)
            except Exception:
                pass
            results.append(fail)

    if adapter is not None:
        try:
            if settings.get("save_after_write", True):
                adapter.save_study()
        except Exception as ex:
            print("AVISO save bulk SpotLoad:", ex)
        try:
            adapter.close_study(save=False)
        except Exception:
            pass

    gui_info = None
    if open_gui and last_ok and not settings.get("dry_run"):
        try:
            from core.cymdist_com import pause_cymdist_for_cympy, open_cymdist_gui
            pause_cymdist_for_cympy(settings)
            gui_info = open_cymdist_gui(
                settings,
                kill_existing=False,
                reason="spot_load_bulk:%s" % (last_ok.get("LoadID") or ""),
            )
        except Exception as ex:
            gui_info = {"ok": False, "error": str(ex)}
        try:
            from pipeline.run_demand_allocation import load_session, save_session
            sess = load_session(settings)
            sess["cymdist_keep_open"] = True
            sess["cymdist_keep_open_reason"] = "spot_load_bulk"
            sess["last_spot_load"] = last_ok.get("LoadID")
            save_session(settings, sess)
        except Exception as ex:
            print("AVISO session bulk:", ex)

    location_map = None
    if n_ok > 0 and not settings.get("dry_run"):
        location_map = attach_location_map(settings, last_ok)

    return {
        "ok": n_err == 0 and n_ok > 0,
        "n_ok": n_ok,
        "n_error": n_err,
        "n_skipped": len(skipped),
        "skipped": skipped,
        "results": results,
        "gui": gui_info,
        "location_map": location_map,
        "location_map_url": (
            "/api/informe/imagen/topologia.png" if (location_map or {}).get("ok") else None
        ),
        "msg": "Conectadas %s · errores %s · omitidas %s" % (n_ok, n_err, len(skipped)),
    }


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


def attach_location_map(settings, result=None):
    """
    Tras conectar SpotLoad (§4.2): genera topologia.png (mapa satelite del nodo).
    Debe llamarse despues de append_report para que el CSV tenga la fila OK.
    """
    if settings.get("dry_run"):
        return {"ok": False, "skipped": True, "reason": "dry_run"}
    estado = str((result or {}).get("Estado") or "").upper()
    if result is not None and estado not in ("OK", "OK_UPDATE", ""):
        return {"ok": False, "skipped": True, "reason": "estado=%s" % estado}
    try:
        from pipeline.generate_location_map import generate_location_map
        # Preferir nodo de conexion de este result (mas fiable que solo CSV)
        map_res = generate_location_map(settings, force=True)
        if result is not None and isinstance(result, dict):
            result["location_map"] = map_res
        return map_res
    except Exception as ex:
        err = {"ok": False, "error": str(ex)}
        if result is not None and isinstance(result, dict):
            result["location_map"] = err
        print("AVISO mapa ubicacion SpotLoad:", ex)
        return err


def list_connected_spot_loads(settings):
    """
    Cargas nuevas del §4 ya conectadas y guardadas en el estudio.

    Fuentes (en orden):
      1) loads/new_spot_loads_report.csv (escrito al conectar 4.2 o 4.3)
      2) Fallback: session.last_spot_load + inventory/loads.json

    Independiente de inventario de nodos. §5 proyectado/situacional usa esta lista.
    Solo filas OK. Una entrada por LoadID (la última gana).
    """
    path = output_path(settings, "loads", "new_spot_loads_report.csv")
    by_id = {}
    if os.path.isfile(path):
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
                    fuente = str(r.get("Fuente") or r.get("Location") or "")
                    if fuente == "inventory_fallback" and not lid.startswith("NODE_"):
                        continue
                    try:
                        p = float(str(r.get("P_kW") or "0").replace(",", "."))
                        q = float(str(r.get("Q_kvar") or "0").replace(",", "."))
                    except Exception:
                        continue
                    by_id[lid] = {
                        "LoadID": lid,
                        "Nombre": r.get("Nombre") or lid,
                        "NodeID": r.get("NodeID"),
                        "SectionID": r.get("SectionID"),
                        "P_kW": p,
                        "Q_kvar": q,
                        "cosfi": r.get("cosfi"),
                        "Estado": r.get("Estado") or "OK",
                        "Fuente": "report_csv",
                    }
        except Exception:
            by_id = {}

    # Reporte §4 (unitaria 4.2 o lote 4.3). Si parece inventario masivo, filtrar.
    if by_id:
        only_new = {
            k: v for k, v in by_id.items()
            if str(k).startswith("NODE_") or str(k).upper().startswith("NEW_")
        }
        if only_new:
            return list(only_new.values())
        if len(by_id) <= 100:
            return list(by_id.values())
        try:
            from pipeline.run_demand_allocation import load_session
            last_id = str((load_session(settings) or {}).get("last_spot_load") or "").strip()
        except Exception:
            last_id = ""
        if last_id and last_id in by_id:
            return [by_id[last_id]]
        by_id = {}

    # --- Fallback: last_spot_load de sesión + inventario ---
    last_id = ""
    try:
        from pipeline.run_demand_allocation import load_session
        last_id = str((load_session(settings) or {}).get("last_spot_load") or "").strip()
    except Exception:
        last_id = ""
    if not last_id:
        return []

    inv = output_path(settings, "inventory", "loads.json")
    inv_loads = []
    if os.path.isfile(inv):
        try:
            with open(inv, "r", encoding="utf-8") as f:
                inv_loads = json.load(f).get("loads") or []
        except Exception:
            inv_loads = []

    item = None
    for row in inv_loads:
        if str(row.get("LoadID") or "").strip() != last_id:
            continue
        try:
            p = float(str(row.get("kW") or row.get("P_kW") or "0").replace(",", "."))
            q = float(str(row.get("kvar") or row.get("Q_kvar") or "0").replace(",", "."))
        except Exception:
            p, q = 0.0, 0.0
        item = {
            "LoadID": last_id,
            "Nombre": row.get("Label") or last_id,
            "NodeID": row.get("NodeID") or "",
            "SectionID": row.get("SectionID") or "",
            "P_kW": p,
            "Q_kvar": q,
            "cosfi": row.get("cosfi") or "",
            "Estado": "OK_INV",
            "Fuente": "session_inventory",
        }
        break
    if item is None:
        item = {
            "LoadID": last_id,
            "Nombre": last_id,
            "NodeID": "",
            "SectionID": "",
            "P_kW": 0.0,
            "Q_kvar": 0.0,
            "cosfi": "",
            "Estado": "OK_SESSION",
            "Fuente": "session_only",
        }
    return [item]

def new_loads_as_fixed(settings):
    """Formato apply_fixed_loads: cargas §4 Locked, fuera de prorrateo."""
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
