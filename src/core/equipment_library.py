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
SIZE_HINTS = {
    "OverheadLine": {
        35: "ATVB1-22.9KV-035",
        50: "ATVB1-22.9KV-050",
        70: "ATVB1-22.9KV-070",
        120: "ATVB1-22.9KV-120",
    },
    "Cable": {
        50: "XLPE050",
        120: "XLPE120",
    },
    "Conductor": {
        35: "AAAC035",
        50: "AAAC050",
        70: "AAAC070",
        120: "AAAC1203",
    },
    "Sectionalizer": {
        None: "SEC22.9KV",
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
    Orden: preferred si existe -> hint por calibre -> más usado no-DEFAULT -> None.
    """
    eq_tipo = EQ_TYPE_MAP.get(device_tipo, device_tipo)
    inv = inventory or inventory_library(cympy, [eq_tipo])
    ids = non_default_ids(inv.get(eq_tipo) or [])
    if not ids:
        return None, "sin_equipos_en_biblioteca"

    if preferred_id and equipment_exists(cympy, preferred_id, eq_tipo):
        return str(preferred_id), "preferred_verified"

    hints = SIZE_HINTS.get(eq_tipo) or {}
    if size_mm2 is not None:
        try:
            size_i = int(round(float(size_mm2)))
        except Exception:
            size_i = None
        if size_i is not None:
            hint = hints.get(size_i)
            if hint and hint in ids:
                return hint, "size_hint"
            # match by parsed size in existing IDs
            for eid in ids:
                if _parse_size_from_id(eid) == size_i:
                    return eid, "size_match_id"

    # Sectionalizer / switch: único real
    if eq_tipo in ("Sectionalizer", "Switch") and len(ids) == 1:
        return ids[0], "only_available"

    # Prefer 120 mm2 / mayor calibre típico MT si hay varios
    for prefer in ("120", "070", "050", "035"):
        for eid in ids:
            if prefer in eid.upper():
                return eid, "prefer_" + prefer

    return ids[0], "first_available"

def save_inventory(path, inv):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)
    return path
