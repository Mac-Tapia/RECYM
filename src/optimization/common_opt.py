# -*- coding: utf-8 -*-
"""Optimización CYMDIST: ubicación óptima de capacitores / reguladores / reclosers.

Usa módulos Simulation (p.ej. CapacitorPlacement.Run) con equipos YA creados
en la biblioteca CYMDIST (default_equipment / opt_*_equipment).
"""
from __future__ import print_function
from core.common import require_cympy, truthy, load_json
from core.excel_io import read_kv
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, control_path


def _equipment_for(command_name, settings):
    s = settings or {}
    de = s.get("default_equipment") or {}
    if not isinstance(de, dict):
        de = {}
    if "capacitor" in (command_name or "").lower():
        return (
            s.get("opt_capacitor_equipment")
            or de.get("ShuntCapacitor")
            or de.get("Capacitor")
            or "BC22.9KV"
        )
    if "regulator" in (command_name or "").lower():
        return (
            s.get("opt_regulator_equipment")
            or de.get("Regulator")
            or "REG22.9KV"
        )
    if "recloser" in (command_name or "").lower():
        return (
            s.get("opt_recloser_equipment")
            or de.get("Recloser")
            or "REC22.9KV"
        )
    return None


def _try_set(obj, names, value, notes):
    """Best-effort SetValue / setattr sobre el módulo de ubicación óptima."""
    for name in names:
        try:
            if hasattr(obj, "SetValue"):
                obj.SetValue(value, name)
                notes.append("SetValue %s=%s" % (name, value))
                return True
        except Exception:
            pass
        try:
            setattr(obj, name, value)
            notes.append("setattr %s=%s" % (name, value))
            return True
        except Exception:
            pass
    return False


def _configure_placement(inst, command_name, settings, notes):
    """Configura el módulo con equipo de biblioteca ya existente."""
    eid = _equipment_for(command_name, settings)
    if not eid:
        return
    # Nombres habituales en módulos CYME Cap/Reg Placement
    _try_set(
        inst,
        (
            "EquipmentID", "DeviceID", "CapacitorID", "CapacitorEquipmentID",
            "ShuntCapacitorID", "RegulatorID", "RegulatorEquipmentID",
            "Equipment", "EqID",
        ),
        str(eid),
        notes,
    )
    # Cantidad / etapas (si el módulo lo expone)
    n_banks = settings.get("opt_capacitor_count") if "capacitor" in command_name else None
    if n_banks in (None, ""):
        n_banks = settings.get("opt_placement_count")
    if n_banks not in (None, ""):
        try:
            n_banks = int(n_banks)
        except Exception:
            n_banks = None
    if n_banks:
        _try_set(
            inst,
            ("NumberOfCapacitors", "NumberOfBanks", "MaxNumber", "Number", "Count"),
            n_banks,
            notes,
        )
    notes.append("equipment_id=%s" % eid)


def _resolve_placement_class(cympy, command_name, cfg):
    """Resuelve la clase Simulation; prueba alias si Regulator no está mapeado."""
    callable_path = (cfg or {}).get("callable") or ""
    # Camino configurado
    if callable_path:
        try:
            parts = callable_path.split(".")
            obj = cympy
            for p in parts:
                if p == "sim":
                    obj = cympy.sim
                else:
                    obj = getattr(obj, p)
            return obj, callable_path
        except Exception:
            pass
    # Alias por tipo
    names = []
    low = (command_name or "").lower()
    if "capacitor" in low:
        names = ["CapacitorPlacement", "OptimalCapacitorPlacement", "CapacitorLocation"]
    elif "regulator" in low:
        names = [
            "RegulatorPlacement", "OptimalRegulatorPlacement",
            "VoltageRegulatorPlacement", "RegulatorLocation",
        ]
    elif "recloser" in low:
        names = ["RecloserPlacement", "OptimalRecloserPlacement"]
    for name in names:
        try:
            cls = getattr(cympy.sim, name)
            return cls, "sim.%s" % name
        except Exception:
            continue
    return None, None


def run_opt(command_name, control_flag=None, settings=None, force=False):
    """Ejecuta comando de optimización CYMDIST. Devuelve dict para CLI/UI."""
    s = settings or load_settings()
    api = load_json("config/cympy_api_map.json")
    book = control_path(s)
    ctrl = read_kv(book, "Control_Proyecto") if book else {}

    result = {
        "ok": False,
        "feeder_id": s.get("feeder_id"),
        "command": command_name,
        "control_flag": control_flag,
        "status": "error",
        "equipment_id": _equipment_for(command_name, s),
        "config_notes": [],
    }

    if control_flag and not force and not truthy(ctrl.get(control_flag)):
        msg = "Omitido por control Excel (%s=false): %s" % (control_flag, command_name)
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({"ok": True, "status": "skipped", "msg": msg})
        return result

    cfg = api.get("commands", {}).get(command_name, {})
    if s.get("dry_run"):
        msg = "DRY_RUN: %s | confirmed=%s | equipo=%s" % (
            command_name, cfg.get("confirmed"), result.get("equipment_id"),
        )
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({
            "ok": True, "status": "dry_run", "msg": msg,
            "confirmed": cfg.get("confirmed"),
        })
        return result

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.ensure_study()

    notes = []
    cls, resolved = _resolve_placement_class(c, command_name, cfg)
    if cls is None:
        msg = (
            "OMITIDO: módulo de ubicación óptima no disponible en CymPy para %s. "
            "Equipo previsto=%s. %s"
            % (
                command_name,
                result.get("equipment_id"),
                cfg.get("note") or "",
            )
        )
        print("[%s] %s" % (s["feeder_id"], msg))
        result.update({"ok": False, "status": "unconfirmed", "msg": msg})
        return result

    method = (cfg or {}).get("method") or "Run"
    try:
        inst = cls() if callable(cls) else cls
    except TypeError:
        inst = cls
    except Exception as ex:
        result.update({
            "ok": False, "status": "error",
            "msg": "No se pudo instanciar %s: %s" % (resolved, ex),
        })
        return result

    _configure_placement(inst, command_name, s, notes)
    result["config_notes"] = notes
    result["resolved_module"] = resolved

    try:
        fn = getattr(inst, method)
        fn()
    except Exception as ex:
        # Fallback: adapter.command si el mapa confirmado
        if cfg.get("confirmed") and cfg.get("callable"):
            try:
                a.command(command_name)
            except Exception as ex2:
                result.update({
                    "ok": False, "status": "error",
                    "msg": "Fallo %s.%s: %s | fallback: %s" % (resolved, method, ex, ex2),
                    "config_notes": notes,
                })
                return result
        else:
            result.update({
                "ok": False, "status": "error",
                "msg": "Fallo %s.%s: %s" % (resolved, method, ex),
                "config_notes": notes,
            })
            return result

    print("[%s] OK: %s (%s) equipo=%s" % (
        s["feeder_id"], command_name, resolved, result.get("equipment_id"),
    ))
    if s.get("save_after_write", True) or s.get("save_after_fix", True):
        try:
            a.save_study()
        except Exception as ex_sv:
            notes.append("save_study: %s" % ex_sv)

    lf_ok = None
    lf_err = None
    try:
        a.run_load_flow()
        lf_ok = True
        print("[%s] LoadFlow post-optimización ejecutado." % s["feeder_id"])
    except Exception as ex:
        lf_ok = False
        lf_err = str(ex)
        print("AVISO LoadFlow post-opt:", ex)

    result.update({
        "ok": True,
        "status": "ok",
        "msg": "OK: %s · módulo %s · equipo %s" % (
            command_name, resolved, result.get("equipment_id"),
        ),
        "loadflow_ok": lf_ok,
        "loadflow_error": lf_err,
        "config_notes": notes,
    })
    return result
