# -*- coding: utf-8 -*-
"""
Clientes por alimentador: suministrocliente + clientesimportantes + match SED CYMDIST.

Flujo:
  1) Leer ML_*.xlsx (Suministro, Cliente, SED, RADIAL)
  2) Filtrar por alimentador (RADIAL), p.ej. PA217
  3) Enriquecer EA/Pot desde hoja 'resumen' del .xlsb elegido en UI
  4) Resolver LoadID en CYMDIST por código SED
"""
from __future__ import print_function
import os
import re
import json
from collections import defaultdict

def _root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def resolve_dir(settings, key, default_rel):
    raw = (settings or {}).get(key) or default_rel
    if os.path.isabs(raw):
        return raw
    return os.path.join(_root(), raw)

def norm_nis(value):
    """Normaliza NIS/Suministro a string entero sin decimales."""
    if value is None or value == "":
        return ""
    s = str(value).strip().replace(" ", "").replace(",", "")
    try:
        return str(int(float(s)))
    except Exception:
        return re.sub(r"\D", "", s) or s

def norm_sed(value):
    s = str(value or "").strip().upper()
    s = s.replace(" ", "")
    return s

def list_suministro_files(settings=None):
    d = resolve_dir(settings, "suministrocliente_dir", "data/input/common/suministrocliente")
    if not os.path.isdir(d):
        return []
    return sorted(
        f for f in os.listdir(d)
        if f.lower().endswith((".xlsx", ".xlsm", ".xls")) and not f.startswith("~")
    )

def list_clientes_importantes_files(settings=None):
    d = resolve_dir(settings, "clientesimportantes_dir", "data/input/common/clientesimportantes")
    if not os.path.isdir(d):
        return []
    return sorted(
        f for f in os.listdir(d)
        if f.lower().endswith((".xlsb", ".xlsx", ".xlsm")) and not f.startswith("~")
    )

def _pick_col(headers, candidates):
    lower = {str(h).strip().lower(): h for h in headers if h is not None}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    # partial
    for h in headers:
        hl = str(h).strip().lower()
        for c in candidates:
            if c.lower() in hl:
                return h
    return None

def read_suministro_table(path):
    """Lee tabla suministrocliente → list[dict]."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows_raw = []
    for row in ws.iter_rows(values_only=True):
        rows_raw.append(list(row))
    wb.close()
    if not rows_raw:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows_raw[0]]
    col_sum = _pick_col(headers, ["Suministro", "NIS", "Nis", "Suministro Act"])
    col_cli = _pick_col(headers, ["Cliente", "Inicio", "Nombre"])
    col_sed = _pick_col(headers, ["SED", "Sed", "Codigo SED", "Código SED"])
    col_rad = _pick_col(headers, ["RADIAL", "Radial", "Alimentador", "Feeder"])
    col_gen = _pick_col(headers, ["Generador", "Suministrador"])
    col_con = _pick_col(headers, ["Conseción", "Concesion", "Concesión"])
    out = []
    for vals in rows_raw[1:]:
        if not any(vals):
            continue
        d = dict(zip(headers, vals))
        suministro = norm_nis(d.get(col_sum) if col_sum else None)
        if not suministro:
            continue
        out.append({
            "Suministro": suministro,
            "Cliente": str(d.get(col_cli) or "").strip() if col_cli else "",
            "SED": norm_sed(d.get(col_sed) if col_sed else ""),
            "RADIAL": str(d.get(col_rad) or "").strip().upper() if col_rad else "",
            "Generador": str(d.get(col_gen) or "").strip() if col_gen else "",
            "Concesion": str(d.get(col_con) or "").strip() if col_con else "",
        })
    return out

def filter_by_feeder(rows, feeder_id, all_feeders=False, feeders=None):
    """
    Filtra por RADIAL.
    - all_feeders=True → todos con RADIAL no vacío
    - feeders=[...] → varios alimentadores
    - feeder_id=str → uno solo (compatibilidad)
    """
    if all_feeders:
        return [r for r in rows if r.get("RADIAL")]
    ids = []
    if feeders:
        if isinstance(feeders, (list, tuple, set)):
            ids = [str(x).strip().upper() for x in feeders if str(x).strip()]
        else:
            ids = [str(feeders).strip().upper()] if str(feeders).strip() else []
    if not ids:
        fid = str(feeder_id or "").strip().upper()
        if fid:
            ids = [fid]
    if not ids:
        return []
    if len(ids) == 1:
        fid = ids[0]
        return [r for r in rows if str(r.get("RADIAL") or "").strip().upper() == fid]
    wanted = set(ids)
    return [r for r in rows if str(r.get("RADIAL") or "").strip().upper() in wanted]

def list_radiales(rows):
    from collections import Counter
    return Counter(r.get("RADIAL") or "" for r in rows)

def list_radiales_from_suministro(settings, suministro_file=None):
    """
    Lista alimentadores (RADIAL) presentes en el archivo suministrocliente.
    Retorna [{id, n}, ...] ordenado por id.
    """
    sum_dir = resolve_dir(settings, "suministrocliente_dir", "data/input/common/suministrocliente")
    sum_files = list_suministro_files(settings)
    if not sum_files:
        return [], None
    sum_name = suministro_file or sum_files[0]
    if sum_name not in sum_files:
        raise RuntimeError(
            "Archivo suministro no está en la carpeta (%s). Disponibles: %s"
            % (sum_name, ", ".join(sum_files))
        )
    sum_path = os.path.join(sum_dir, sum_name)
    base = read_suministro_table(sum_path)
    counts = list_radiales(base)
    items = [
        {"id": rid, "n": int(n)}
        for rid, n in sorted(counts.items(), key=lambda x: x[0])
        if rid
    ]
    return items, sum_name

def read_clientes_importantes_resumen(path, sheet_name="resumen"):
    """
    Lee hoja resumen de .xlsb/.xlsx → dict NIS -> {EA, Pot, Cliente, ...}
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsb":
        return _read_resumen_xlsb(path, sheet_name)
    return _read_resumen_xlsx(path, sheet_name)

def _read_resumen_xlsb(path, sheet_name):
    from pyxlsb import open_workbook
    by_nis = {}
    with open_workbook(path) as wb:
        names = list(wb.sheets)
        if sheet_name not in names:
            # fallback: primera hoja con Nis/EA
            sheet_name = names[1] if len(names) > 1 else names[0]
        with wb.get_sheet(sheet_name) as sheet:
            header = None
            header_idx = None
            for i, row in enumerate(sheet.rows()):
                vals = [c.v for c in row]
                # Detectar fila de encabezado
                texts = [str(v).strip().lower() if v is not None else "" for v in vals]
                if header is None and ("nis" in texts or "ea" in texts and "pot" in texts):
                    header = [str(v).strip() if v is not None else "" for v in vals]
                    header_idx = {h.lower(): idx for idx, h in enumerate(header) if h}
                    continue
                if header is None:
                    continue
                def get(name_opts):
                    for n in name_opts:
                        j = header_idx.get(n.lower())
                        if j is not None and j < len(vals):
                            return vals[j]
                    return None
                nis = norm_nis(get(["Nis", "NIS", "Suministro", "Nuevo #sum"]))
                if not nis:
                    continue
                ea = get(["EA", "Ea", "Energia", "Energía"])
                pot = get(["Pot", "POT", "Potencia", "P"])
                by_nis[nis] = {
                    "EA": _to_float(ea),
                    "Pot": _to_float(pot),
                    "Cliente_CI": str(get(["Inicio", "Cliente"]) or "").strip(),
                    "ERI": _to_float(get(["ERI"])),
                    "ERC": _to_float(get(["ERC"])),
                    "Codigo_CL": str(get(["Código CL", "Codigo CL"]) or "").strip(),
                }
    return by_nis

def _read_resumen_xlsx(path, sheet_name):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]
    header = None
    header_idx = {}
    by_nis = {}
    for row in ws.iter_rows(values_only=True):
        vals = list(row)
        texts = [str(v).strip().lower() if v is not None else "" for v in vals]
        if header is None and ("nis" in texts or ("ea" in texts and "pot" in texts)):
            header = [str(v).strip() if v is not None else "" for v in vals]
            header_idx = {h.lower(): i for i, h in enumerate(header) if h}
            continue
        if not header:
            continue
        def get(names):
            for n in names:
                j = header_idx.get(n.lower())
                if j is not None and j < len(vals):
                    return vals[j]
            return None
        nis = norm_nis(get(["Nis", "NIS", "Suministro"]))
        if not nis:
            continue
        by_nis[nis] = {
            "EA": _to_float(get(["EA"])),
            "Pot": _to_float(get(["Pot", "POT"])),
            "Cliente_CI": str(get(["Inicio", "Cliente"]) or "").strip(),
            "ERI": _to_float(get(["ERI"])),
            "ERC": _to_float(get(["ERC"])),
            "Codigo_CL": str(get(["Código CL", "Codigo CL"]) or "").strip(),
        }
    wb.close()
    return by_nis

def _to_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(",", ".").replace(" ", ""))
        except Exception:
            return None

def enrich_with_ea_pot(rows, by_nis):
    """Agrega columnas EA y Pot a la tabla de suministro."""
    out = []
    for r in rows:
        row = dict(r)
        info = by_nis.get(row["Suministro"]) or {}
        row["EA"] = info.get("EA")
        row["Pot"] = info.get("Pot")
        row["Cliente_CI"] = info.get("Cliente_CI") or ""
        row["Match_CI"] = bool(info)
        row["ERI"] = info.get("ERI")
        row["Codigo_CL"] = info.get("Codigo_CL") or ""
        out.append(row)
    return out

def build_feeder_clientes_table(settings, feeder_id, clientes_file=None, suministro_file=None, all_feeders=False, feeders=None):
    """
    Orquesta lectura + filtro + cruce NIS.
    clientes_file es OBLIGATORIO: el cruce EA/Pot se hace solo sobre ese archivo.
    feeders: lista opcional de RADIAL a incluir (multi-selección UI).
    Retorna (rows, meta).
    """
    sum_dir = resolve_dir(settings, "suministrocliente_dir", "data/input/common/suministrocliente")
    ci_dir = resolve_dir(settings, "clientesimportantes_dir", "data/input/common/clientesimportantes")

    sum_files = list_suministro_files(settings)
    if not sum_files:
        raise RuntimeError("No hay archivos en suministrocliente: " + sum_dir)
    sum_name = suministro_file or sum_files[0]
    if suministro_file and suministro_file not in sum_files:
        raise RuntimeError(
            "Archivo suministro no está en la carpeta (%s). Disponibles: %s"
            % (suministro_file, ", ".join(sum_files))
        )
    sum_path = os.path.join(sum_dir, sum_name)
    if not os.path.isfile(sum_path):
        raise RuntimeError("No existe archivo suministro: " + sum_path)

    ci_files = list_clientes_importantes_files(settings)
    if not ci_files:
        raise RuntimeError("No hay archivos en clientesimportantes: " + ci_dir)
    ci_name = (clientes_file or "").strip()
    if not ci_name:
        raise RuntimeError(
            "Debe seleccionar un archivo de clientesimportantes en la interfaz. Disponibles: %s"
            % (", ".join(ci_files))
        )
    if ci_name not in ci_files:
        raise RuntimeError(
            "Archivo '%s' no está en clientesimportantes. Disponibles: %s"
            % (ci_name, ", ".join(ci_files))
        )
    ci_path = os.path.join(ci_dir, ci_name)
    if not os.path.isfile(ci_path):
        raise RuntimeError("No existe archivo clientes importantes: " + ci_path)

    # Normalizar lista de alimentadores
    feeder_list = []
    if feeders:
        if isinstance(feeders, (list, tuple, set)):
            feeder_list = [str(x).strip().upper() for x in feeders if str(x).strip()]
        else:
            feeder_list = [str(feeders).strip().upper()] if str(feeders).strip() else []
    if not feeder_list and feeder_id and not all_feeders:
        # admite "PA217,PA218" o un solo id
        raw = str(feeder_id).strip()
        if "," in raw or ";" in raw:
            feeder_list = [x.strip().upper() for x in re.split(r"[,;]+", raw) if x.strip()]
        else:
            feeder_list = [raw.upper()] if raw else []

    base = read_suministro_table(sum_path)
    filtered = filter_by_feeder(
        base, feeder_id, all_feeders=all_feeders, feeders=feeder_list or None
    )
    # Cruce SOLO contra el archivo seleccionado
    by_nis = read_clientes_importantes_resumen(ci_path)
    enriched = enrich_with_ea_pot(filtered, by_nis)

    if all_feeders:
        feeder_meta = "ALL"
    elif len(feeder_list) > 1:
        feeder_meta = ",".join(feeder_list)
    elif feeder_list:
        feeder_meta = feeder_list[0]
    else:
        feeder_meta = feeder_id

    meta = {
        "suministro_file": sum_name,
        "clientes_file": ci_name,
        "clientes_path": ci_path,
        "feeder_id": feeder_meta,
        "feeders": feeder_list if not all_feeders else sorted(
            {r.get("RADIAL") for r in filtered if r.get("RADIAL")}
        ),
        "all_feeders": bool(all_feeders),
        "n_suministro_total": len(base),
        "n_filtrados": len(filtered),
        "n_con_ea_pot": sum(1 for r in enriched if r.get("Match_CI")),
        "n_sin_match": sum(1 for r in enriched if not r.get("Match_CI")),
        "n_nis_en_archivo_ci": len(by_nis),
        "radiales": dict(list_radiales(base)),
        "archivos_ci_disponibles": ci_files,
    }
    return enriched, meta

def score_sed_load(load_id, sed):
    """Mayor score = mejor match SED → LoadID."""
    lid = str(load_id or "").upper()
    sed = norm_sed(sed)
    if not sed or sed not in lid:
        return -1
    # exact trailing _SED
    if lid.endswith("_" + sed) or lid.endswith(sed):
        return 100
    # _SED-2 / _SED-11 variants
    m = re.search(r"_" + re.escape(sed) + r"(-\d+)?$", lid)
    if m:
        if m.group(1):
            return 70
        return 95
    if "_" + sed + "-" in lid or "_" + sed + "_" in lid:
        return 50
    return 10

def resolve_sed_to_loads(loads, sed, primary_only=True):
    """
    loads: list dict with LoadID
    Retorna lista de LoadID ordenados por score.
    primary_only: solo el mejor match.
    """
    scored = []
    for L in loads:
        lid = L.get("LoadID") if isinstance(L, dict) else str(L)
        sc = score_sed_load(lid, sed)
        if sc >= 0:
            scored.append((sc, str(lid)))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored:
        return []
    if primary_only:
        return [scored[0][1]]
    return [x[1] for x in scored]

def attach_cymdist_loads(rows, loads_inventory, primary_only=True):
    """Agrega LoadID_CYMDIST y Match_SED a cada fila."""
    out = []
    for r in rows:
        row = dict(r)
        lids = resolve_sed_to_loads(loads_inventory, row.get("SED"), primary_only=primary_only)
        row["LoadID_CYMDIST"] = lids[0] if lids else ""
        row["LoadIDs_CYMDIST"] = "|".join(lids)
        row["Match_SED"] = bool(lids)
        if "Activo" not in row:
            row["Activo"] = True
        out.append(row)
    return out

def row_key(row):
    """Clave estable por suministro (NIS) + SED."""
    return "%s|%s" % (str(row.get("Suministro") or "").strip(), str(row.get("SED") or "").strip())

def ensure_activo(rows, default=True):
    """Garantiza campo Activo en cada fila (marcado por defecto)."""
    out = []
    for r in rows:
        row = dict(r)
        if "Activo" not in row or row.get("Activo") in (None, ""):
            row["Activo"] = bool(default)
        else:
            from core.common import truthy
            row["Activo"] = truthy(row.get("Activo"))
        out.append(row)
    return out

def merge_activo(rows, activo_map=None, previous_rows=None):
    """
    Aplica selección Activo desde mapa {key: bool} y/o filas previas.
    key = Suministro|SED (ver row_key). También acepta solo Suministro.
    """
    from core.common import truthy
    prev = {}
    if previous_rows:
        for r in previous_rows:
            prev[row_key(r)] = truthy(r.get("Activo", True))
            sumi = str(r.get("Suministro") or "").strip()
            if sumi:
                prev.setdefault(sumi, truthy(r.get("Activo", True)))
    amap = {}
    if activo_map:
        for k, v in activo_map.items():
            amap[str(k).strip()] = truthy(v)
    out = []
    for r in rows:
        row = dict(r)
        key = row_key(row)
        sumi = str(row.get("Suministro") or "").strip()
        if key in amap:
            row["Activo"] = amap[key]
        elif sumi in amap:
            row["Activo"] = amap[sumi]
        elif key in prev:
            row["Activo"] = prev[key]
        elif sumi in prev:
            row["Activo"] = prev[sumi]
        elif "Activo" not in row or row.get("Activo") in (None, ""):
            row["Activo"] = True
        else:
            row["Activo"] = truthy(row.get("Activo"))
        out.append(row)
    return out

def load_saved_clientes_rows(path):
    """Lee filas de clientes_alimentador.json si existe."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("rows") or []
    except Exception:
        return []

def save_table_csv(path, rows, headers=None):
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if headers is None:
        headers = [
            "RADIAL", "Suministro", "Cliente", "SED", "EA", "Pot",
            "Match_CI", "LoadID_CYMDIST", "Match_SED", "Activo",
            "Generador", "Concesion", "Cliente_CI", "Codigo_CL",
        ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path

def save_table_json(path, rows, meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta or {}, "rows": rows}, f, ensure_ascii=False, indent=2)
    return path
