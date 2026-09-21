# -*- coding: utf-8 -*-
"""
Crea/corrige condensadores shunt en PA217 segun ficha CYME (BC22.9KV).

- DeviceNumber unico (no reutilizar ID del tramo/linea)
- KVLN = Vll/sqrt(3)  (~13.22 kV), no 22.9 kVLN
- Fija 450 kvar + Conmutada 450 kvar (150 kvar/fase)
- Control VoltageControlled + override tension
- Guarda estudio + AllEquipments
"""
from __future__ import print_function
import json
import math
import os
from core.common import require_cympy, load_json, mkdir
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path
import cympy.eq as eq


# Bancos a materializar (section conocida del screenshot + placeholder 2do si se indica)
BANKS = [
    {
        "DeviceNumber": "BC_PA217_01",
        "SectionID": "SEC_1091_978023",
        "EquipmentID": "BC22.9KV",
        "fixed_kvar_total": 450.0,
        "switched_kvar_total": 450.0,
        "interrupting_a": 600.0,
    },
    # Segundo banco: completar SectionID cuando se confirme en CYME
    # {"DeviceNumber": "BC_PA217_02", "SectionID": "???", ...},
]


def _set(d, field, value, notes):
    try:
        before = None
        try:
            before = d.GetValue(field)
        except Exception:
            pass
        d.SetValue(value, field)
        after = d.GetValue(field)
        notes.append("%s: %s -> %s" % (field, before, after))
        return True
    except Exception as ex:
        notes.append("%s FAIL: %s" % (field, ex))
        return False


def _ensure_equipment(cympy, equip_id, vln, rated_kvar, notes):
    et = cympy.enums.EquipmentType.ShuntCapacitor
    exists = False
    try:
        eq.GetValue("RatedKVAR", equip_id, et)
        exists = True
    except Exception:
        exists = False
    if not exists:
        try:
            eq.Add(equip_id, et)
            notes.append("eq.Add %s" % equip_id)
        except Exception as ex:
            notes.append("eq.Add FAIL %s: %s" % (equip_id, ex))
            return False
    for fld, val in [
        ("RatedKVAR", float(rated_kvar)),
        ("RatedVoltageKVLN", float(vln)),
        ("LossesKW", 0.0),
    ]:
        try:
            before = eq.GetValue(fld, equip_id, et)
            eq.SetValue(float(val), fld, equip_id, et)
            after = eq.GetValue(fld, equip_id, et)
            notes.append("EQ %s %s: %s -> %s" % (equip_id, fld, before, after))
        except Exception as ex:
            notes.append("EQ %s %s FAIL: %s" % (equip_id, fld, ex))
    # Trifasico si el enum lo permite
    for cand in ("ThreePhase", "Three-Phase", "ABC", 1, 2):
        try:
            eq.SetValue(cand, "PhaseType", equip_id, et)
            notes.append("EQ %s PhaseType -> %s" % (equip_id, eq.GetValue("PhaseType", equip_id, et)))
            break
        except Exception:
            continue
    return True


def _configure_bank(d, bank, vln, notes):
    kvar_f = float(bank["fixed_kvar_total"]) / 3.0
    kvar_s = float(bank["switched_kvar_total"]) / 3.0
    _set(d, "DeviceID", bank["EquipmentID"], notes)
    _set(d, "ConnectionStatus", "Connected", notes)
    _set(d, "Location", "From", notes)
    _set(d, "KVLN", float(vln), notes)
    _set(d, "InterruptingRating", float(bank.get("interrupting_a") or 600.0), notes)
    _set(d, "ConnectionConfiguration", "Yg", notes)
    for ph, val in (("A", kvar_f), ("B", kvar_f), ("C", kvar_f)):
        _set(d, "FixedKVAR" + ph, float(val), notes)
        _set(d, "FixedLosses" + ph, 0.0, notes)
    for ph, val in (("A", kvar_s), ("B", kvar_s), ("C", kvar_s)):
        _set(d, "SwitchedKVAR" + ph, float(val), notes)
        _set(d, "SwitchedLosses" + ph, 0.0, notes)
    # Control por tension
    try:
        d.Execute("CapacitorControl.SetType(VoltageControlled)")
        notes.append("CapacitorControl.SetType(VoltageControlled) OK")
    except Exception:
        try:
            d.Execute("CapacitorControl.Create(VoltageControlled)")
            notes.append("CapacitorControl.Create(VoltageControlled) OK")
        except Exception as ex:
            notes.append("CapacitorControl FAIL: %s" % ex)
    # Umbrales ON/OFF (kV LN): enciende bajo, apaga alto
    on_kv = float(vln) * 0.95
    off_kv = float(vln) * 1.05
    for ph in ("A", "B", "C"):
        _set(d, "CapacitorControl.OnValue" + ph, on_kv, notes)
        _set(d, "CapacitorControl.OffValue" + ph, off_kv, notes)
    _set(d, "VoltageOverride", True, notes)
    _set(d, "VoltageOverrideOn", on_kv, notes)
    _set(d, "VoltageOverrideOff", off_kv, notes)
    _set(d, "VoltageOverrideDeadband", 0.5, notes)


def run(settings=None, banks=None):
    s = settings or load_settings()
    banks = banks or BANKS
    vll = float(s.get("voltage_ll_kv") or 22.9)
    vln = vll / math.sqrt(3.0)
    notes = []
    result = {
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "Vll_kV": vll,
        "Vln_kV": vln,
        "created": [],
        "notes": notes,
        "ok": True,
    }

    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()
    net = str(s.get("network_id"))
    dtype = c.enums.DeviceType.ShuntCapacitor

    for bank in banks:
        sid = (bank.get("SectionID") or "").strip()
        did = (bank.get("DeviceNumber") or "").strip().upper()
        eid = (bank.get("EquipmentID") or "BC22.9KV").strip().upper()
        bank = dict(bank)
        bank["DeviceNumber"] = did
        bank["EquipmentID"] = eid
        if not sid or sid.startswith("?"):
            notes.append("SKIP %s: falta SectionID del 2do banco" % did)
            continue
        # Validar seccion
        try:
            c.study.GetSection(sid)
        except Exception as ex:
            notes.append("Section FAIL %s: %s" % (sid, ex))
            result["ok"] = False
            continue

        rated = max(float(bank["fixed_kvar_total"]), float(bank["switched_kvar_total"]))
        _ensure_equipment(c, eid, vln, rated, notes)

        # Add or get
        d = c.study.GetDevice(did, dtype)
        if d is None:
            try:
                d = c.study.AddDevice(
                    did, dtype, sid, eid, c.enums.Location.From, True
                )
                notes.append("AddDevice %s on %s" % (did, sid))
            except Exception as ex:
                try:
                    d = c.study.AddDevice(did, dtype, sid, eid)
                    notes.append("AddDevice(simple) %s: %s" % (did, d))
                except Exception as ex2:
                    notes.append("AddDevice FAIL %s: %s | %s" % (did, ex, ex2))
                    result["ok"] = False
                    continue
        else:
            notes.append("GetDevice existing %s" % did)

        _configure_bank(d, bank, vln, notes)
        snap = {"DeviceNumber": did, "SectionID": sid, "EquipmentID": eid}
        for f in (
            "KVLN", "FixedKVARA", "FixedKVARB", "FixedKVARC",
            "SwitchedKVARA", "SwitchedKVARB", "SwitchedKVARC",
            "ConnectionStatus", "DeviceID", "VoltageOverride",
            "VoltageOverrideOn", "VoltageOverrideOff",
        ):
            try:
                snap[f] = d.GetValue(f)
            except Exception:
                pass
        try:
            snap["CapacitorControlType"] = d.GetValue("CapacitorControl.GetType()")
        except Exception:
            pass
        result["created"].append(snap)

    # Contar
    caps = list(c.study.ListDevices(dtype, net))
    result["n_shunt_after"] = len(caps)
    result["device_numbers"] = [getattr(x, "DeviceNumber", None) for x in caps]

    if s.get("save_after_write", True):
        try:
            from cympy.enums import SaveStudyEquipmentOption
            import cympy.db as db
            path = s.get("study_path") or ""
            c.study.Save(path, True, True, SaveStudyEquipmentOption.AllEquipments)
            try:
                db.Update()
                db.SaveProject()
            except Exception:
                pass
            result["saved"] = True
            notes.append("study.Save(AllEquipments) OK")
        except Exception as ex:
            result["saved"] = False
            result["ok"] = False
            notes.append("save FAIL: %s" % ex)

    try:
        c.study.Close()
    except Exception:
        pass

    out = output_path(s, "diagnostics", "shunt_capacitors_fix.json")
    mkdir(os.path.dirname(out))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    print("wrote", out)
    return result


def main():
    r = run()
    if not r.get("ok") or not r.get("created"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
