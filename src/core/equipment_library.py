# -*- coding: utf-8 -*-
"""Biblioteca de equipos CYMDIST (cympy.eq) — solo IDs reales de la BD."""
from __future__ import print_function
import json
import os
import re

# DeviceType / correcciones -> EquipmentType de la biblioteca
EQ_TYPE_MAP = {
    "OverheadLine": "OverheadLine",
    "Cable": "Cable",
    "Underground": "Cable",
    "Sectionalizer": "Sectionalizer",
    "Switch": "Switch",
    "Seccionador": "Sectionalizer",
    "Transformer": "Transformer",
    "Transformador": "Transformer",
    "Fuse": "Fuse",
    "Recloser": "Recloser",
    "Breaker": "Breaker",
    "Conductor": "Conductor",
    "ShuntCapacitor": "ShuntCapacitor",
    "Regulator": "Regulator",
}

# Preferencias por calibre (mm2) -> ID ya existente en BD Electro Dunas
# OH = línea aérea ATVB1 con conductor AAAC; Cable = XLPE Cu 18/30 kV
SIZE_HINTS = {
    "OverheadLine": {
        35: "ATVB1-22.9KV-035",
        50: "ATVB1-22.9KV-050",
        70: "ATVB1-22.9KV-070",
        95: "ATVB1-22.9KV-120",   # sin OH-95 en BD → vecino 120
        120: "ATVB1-22.9KV-120",
        150: "ATVB1-22.9KV-120",  # sin OH-150 → vecino 120
        185: "ATVB1-22.9KV-240",
        240: "ATVB1-22.9KV-240",
    },
    "Cable": {
        50: "XLPE050",
        70: "XLPE120",   # sin XLPE070 en BD → vecino 120
        95: "XLPE120",
        120: "XLPE120",
        150: "XLPE120",
        185: "XLPE0240",
        240: "XLPE0240",
    },
    "Conductor": {
        35: "AAAC035",
        50: "AAAC050",
        70: "AAAC070",
        95: "AAAC1203",
        120: "AAAC1203",
        150: "AAAC1203",
        185: "AAAC240",
        240: "AAAC240",
    },
    "Sectionalizer": {
        None: "SEC22.9KV",
    },
    "Switch": {
        None: "SW22.9KV",
    },
}

def list_equipment_ids(cympy, equipment_type_name):
    """Lista IDs de la biblioteca para un EquipmentType (excluye vacíos)."""
    import cympy.eq as eq
    et = getattr(cympy.enums.EquipmentType, equipment_type_name)
    eqs = list(eq.ListEquipments(et))
    return [str(e.ID) for e in eqs if str(e.ID or "").strip()]

def inventory_library(cympy, types=None):
    types = types or [
        "OverheadLine", "Cable", "Conductor", "Sectionalizer", "Switch",
        "Transformer", "Fuse", "Recloser", "Breaker", "ShuntCapacitor",
        "Regulator", "OverheadSpacingOfConductor",
    ]
    inv = {}
    for name in types:
        try:
            ids = list_equipment_ids(cympy, name)
            inv[name] = ids
        except Exception as ex:
            inv[name] = []
            print("AVISO ListEquipments(%s): %s" % (name, ex))
    return inv

def equipment_exists(cympy, equipment_id, equipment_type_name):
    if not equipment_id or str(equipment_id).upper() == "DEFAULT":
        return False
    import cympy.eq as eq
    try:
        e = eq.GetEquipment(str(equipment_id), getattr(cympy.enums.EquipmentType, equipment_type_name))
        return bool(e and str(e.ID) == str(equipment_id))
    except Exception as ex:
        # fallback: membership in list
        try:
            return str(equipment_id) in list_equipment_ids(cympy, equipment_type_name)
        except Exception:
            print("AVISO GetEquipment(%s,%s): %s" % (equipment_id, equipment_type_name, ex))
            return False

def non_default_ids(ids):
    return [i for i in ids if str(i).upper() != "DEFAULT"]

def _parse_size_from_id(eq_id):
    """Extrae calibre mm2 desde IDs tipo ATVB1-22.9KV-120 / XLPE050 / AAAC035."""
    s = str(eq_id or "").upper()
    m = re.search(r"(?:KV-|XLPE|AAAC|N2XYH)?(\d{2,4})(?:-2T)?$", s)
    if not m:
        m = re.search(r"(\d{2,4})", s)
    if not m:
        return None
    try:
        n = int(m.group(1))
        if n > 500:  # p.ej. 1203 -> 120
            if n % 10 == 3 and 100 <= n // 10 <= 500:
                return n // 10
        return n
    except Exception:
        return None

def pick_equipment(cympy, device_tipo, preferred_id=None, size_mm2=None, inventory=None):
    """
    Elige un equipo REAL de la biblioteca.
    Orden: hint por calibre (si size_mm2) -> preferred si existe -> más usado no-DEFAULT -> None.
    Así DEFAULT se reemplaza por AAAC/XLPE de la misma sección, no siempre por el default fijo.
    """
    eq_tipo = EQ_TYPE_MAP.get(device_tipo, device_tipo)
    inv = inventory or inventory_library(cympy, [eq_tipo])
    ids = non_default_ids(inv.get(eq_tipo) or [])
    if not ids:
        return None, "sin_equipos_en_biblioteca"

    hints = SIZE_HINTS.get(eq_tipo) or {}
    if size_mm2 is not None:
        try:
            size_i = int(round(float(size_mm2)))
        except Exception:
            size_i = None
        if size_i is not None:
            hint = hints.get(size_i)
            if hint and hint in ids:
                return hint, "size_hint_%smm2" % size_i
            # match by parsed size in existing IDs
            for eid in ids:
                if _parse_size_from_id(eid) == size_i:
                    return eid, "size_match_id_%s" % size_i
            # nearest available size
            avail = []
            for eid in ids:
                s = _parse_size_from_id(eid)
                if s is not None:
                    avail.append((abs(s - size_i), s, eid))
            if avail:
                avail.sort()
                return avail[0][2], "size_nearest_%s->%s" % (size_i, avail[0][1])

    if preferred_id and equipment_exists(cympy, preferred_id, eq_tipo):
        return str(preferred_id), "preferred_verified"

    # Sectionalizer / switch: único real
    if eq_tipo in ("Sectionalizer", "Switch") and len(ids) == 1:
        return ids[0], "only_available"

    # Prefer 120 mm2 / mayor calibre típico MT si hay varios
    for prefer in ("120", "070", "050", "035", "240"):
        for eid in ids:
            if prefer in eid.upper():
                return eid, "prefer_" + prefer

    return ids[0], "first_available"


def size_from_default_equipment(cympy, device_tipo):
    """
    Lee la sección mm2 del equipo DEFAULT de biblioteca (PhaseConductor / Size).
    Respeta la fuente de ingreso: no inventa calibre si DEFAULT ya apunta a un AAAC.
    """
    import cympy.eq as eq
    eq_tipo = EQ_TYPE_MAP.get(device_tipo, device_tipo)
    try:
        et = getattr(cympy.enums.EquipmentType, eq_tipo)
        e = eq.GetEquipment("DEFAULT", et)
    except Exception:
        return None
    # OverheadLine: sección del conductor de fase
    for fld in ("PhaseConductorID", "PhaseConductorId", "ConductorID"):
        try:
            cid = str(e.GetValue(fld) or "").strip()
            if cid and cid.upper() != "DEFAULT":
                try:
                    cond = eq.GetEquipment(cid, cympy.enums.EquipmentType.Conductor)
                    for sf in ("Size", "Size_mm2"):
                        try:
                            v = cond.GetValue(sf)
                            if v is not None and str(v).strip() != "":
                                return float(str(v).replace(",", "."))
                        except Exception:
                            pass
                    # fallback: parse ID AAAC1203
                    parsed = _parse_size_from_id(cid)
                    if parsed:
                        return float(parsed)
                except Exception:
                    parsed = _parse_size_from_id(cid)
                    if parsed:
                        return float(parsed)
        except Exception:
            pass
    # Cable / otros: Size directo o NominalRating→hint
    for sf in ("Size", "Size_mm2", "ConductorSize"):
        try:
            v = e.GetValue(sf)
            if v is not None and str(v).strip() not in ("", "0", "0,0", "0.0"):
                return float(str(v).replace(",", "."))
        except Exception:
            pass
    return None


def size_from_device(adapter_or_cympy, device_tipo, obj_id):
    """Lee sección mm2 del dispositivo en el modelo; si es DEFAULT, usa biblioteca DEFAULT.

    Prioridad:
      1) Campos Size / Conductor / LineID / CableID / EquipmentID del dispositivo
      2) Equipo del mismo tramo (Section.ListDevices → OH/UG)
      3) Equipo DEFAULT de biblioteca (AAAC/XLPE ligado)
    """
    cympy = getattr(adapter_or_cympy, "cympy", adapter_or_cympy)
    d = None
    try:
        if hasattr(adapter_or_cympy, "get_device"):
            d = adapter_or_cympy.get_device(device_tipo, obj_id)
    except Exception:
        d = None

    def _size_from_eq_id(eq_id):
        vs = str(eq_id or "").strip()
        if not vs or vs.upper() == "DEFAULT":
            return None
        return float(_parse_size_from_id(vs)) if _parse_size_from_id(vs) else None

    if d is not None:
        for fld in (
            "Size", "ConductorSize", "PhaseConductorID",
            "LineID", "CableID", "EquipmentID", "EquipmentId",
        ):
            try:
                v = d.GetValue(fld)
                vs = str(v or "").strip()
                if not vs or vs.upper() == "DEFAULT":
                    continue
                if fld in ("Size", "ConductorSize"):
                    return float(vs.replace(",", "."))
                parsed = _size_from_eq_id(vs)
                if parsed:
                    return parsed
            except Exception:
                pass

        # Calibre del tramo: otros OH/UG en la misma sección
        sec_id = ""
        try:
            sec_id = str(getattr(d, "SectionID", None) or d.GetValue("SectionID") or "").strip()
        except Exception:
            sec_id = ""
        if sec_id:
            try:
                sec = cympy.study.GetSection(sec_id)
                for peer in list(sec.ListDevices()):
                    try:
                        eq = str(getattr(peer, "EquipmentID", None) or "").strip()
                    except Exception:
                        eq = ""
                    parsed = _size_from_eq_id(eq)
                    if parsed:
                        return parsed
            except Exception:
                pass

    return size_from_default_equipment(cympy, device_tipo)


def fix_defaults_on_network(adapter, settings, inventory=None, catalog_hints=None):
    """Reemplaza equipos DEFAULT del alimentador vía API CymPy.

    Usa la biblioteca (tablas de equipos) y, si hay calibre del tramo o de fichas
    (Catalogo_Maestro / AAAC / XLPE), elige el ID de misma sección mm2.
    No modifica OperatingVoltage de fuentes.
    """
    cympy = adapter.cympy
    inv = inventory or inventory_library(cympy)
    defaults = (settings or {}).get("default_equipment") or {}
    hints = catalog_hints or {}
    net = str((settings or {}).get("network_id") or "").strip() or None
    report = []

    targets = (
        ("OverheadLine", "OverheadLine"),
        ("Underground", "Cable"),
        ("Sectionalizer", "Sectionalizer"),
        ("Switch", "Switch"),
    )
    for device_name, eq_tipo in targets:
        try:
            dtype = adapter.device_type(device_name)
        except Exception:
            continue
        try:
            if net:
                devices = list(cympy.study.ListDevices(dtype, net))
            else:
                devices = list(cympy.study.ListDevices(dtype))
        except Exception as ex:
            report.append({
                "Tipo": device_name, "ID": "", "Estado": "ERR_LIST",
                "Detalle": str(ex),
            })
            continue

        for d in devices:
            sid = str(
                getattr(d, "DeviceNumber", None)
                or getattr(d, "ID", None)
                or ""
            ).strip()
            if not sid:
                continue
            # Campo de equipo según tipo
            eq_now = ""
            for fld in ("EquipmentID", "LineID", "CableID", "EquipmentId"):
                try:
                    eq_now = str(d.GetValue(fld) or "").strip()
                    if eq_now:
                        break
                except Exception:
                    continue
            if not eq_now:
                try:
                    eq_now = str(getattr(d, "EquipmentID", None) or "").strip()
                except Exception:
                    eq_now = ""
            if eq_now.upper() != "DEFAULT":
                continue

            size = None
            try:
                size = size_from_device(adapter, device_name, sid)
            except Exception:
                size = None
            if size is None:
                size = hints.get((device_name, sid)) or hints.get((eq_tipo, sid))

            preferred = defaults.get(device_name) or defaults.get(eq_tipo) or ""
            new_eq, how = pick_equipment(
                cympy, device_name,
                preferred_id=preferred,
                size_mm2=size,
                inventory=inv,
            )
            if not new_eq:
                report.append({
                    "Tipo": device_name, "ID": sid, "Estado": "SIN_EQUIPO",
                    "Detalle": "biblioteca sin candidato (fichas/tablas)",
                    "Size": size,
                })
                continue
            try:
                before, after = adapter.set_equipment(device_name, sid, new_eq)
                report.append({
                    "Tipo": device_name, "ID": sid, "Estado": "OK",
                    "Antes": before, "Despues": after,
                    "How": how, "Size": size,
                })
            except Exception as ex:
                report.append({
                    "Tipo": device_name, "ID": sid, "Estado": "ERROR",
                    "Detalle": str(ex), "Equipo": new_eq,
                })
    return report


def save_inventory(path, inv):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)
    return path
