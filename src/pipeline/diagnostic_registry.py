# -*- coding: utf-8 -*-
"""
Registro oficial de códigos NetworkDiagnostic / LoadFlow / Simulation.

Fuente: CYME cymdist.cymsg [DiagnosticTool] (220000–220053) + códigos LF/Sim
frecuentes. Política RECYM: en la etapa de diagnóstico se propone corrección
para TODO código Error/Warning/Hint; los auto_apply se ejecutan en bulk_fix
según el mensaje del manual («Favor de corregir/verificar»).
"""
from __future__ import print_function
import json
import math
import os
import re

from core.common import load_json, truthy

_CATALOG = None
RE_DEVICE = re.compile(
    r"(?:dispositivo|rel[eé]|transformador|condensador|cable|l[ií]nea\s+a[eé]rea|"
    r"seccionador|carga\s+concentrada|nodo(?:\s+de\s+bucle)?|tramo|secci[oó]n|"
    r"generador|interruptor|regulador)\s+(\S+)",
    re.IGNORECASE,
)


def catalog_path():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(root, "config", "diagnostic_corrections_catalog.json")


def load_catalog():
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    path = catalog_path()
    data = load_json(path) if os.path.isfile(path) else {}
    _CATALOG = data.get("codes") or {}
    return _CATALOG


def lookup(code):
    code = str(code or "").strip()
    return load_catalog().get(code) or {
        "code": code,
        "section": "Unknown",
        "message": "",
        "action": "revisar",
        "auto_apply": False,
        "tipo_default": "Device",
        "fix_note": "Código no catalogado — revisar según mensaje CYME",
        "source": "fallback",
    }


def extract_object_id(text, tipo_hint=""):
    text = text or ""
    m = RE_DEVICE.search(text)
    if m:
        return m.group(1).rstrip(".,;")
    # último token con dígitos (IDs CYME típicos)
    toks = re.findall(r"[A-Za-z0-9_\-]{2,}", text)
    for t in reversed(toks):
        if any(ch.isdigit() for ch in t):
            return t
    return ""


def propose_row(diag_row, settings, ctx=None):
    """
    Convierte una fila de cymdist_diagnostic_errors.csv en propuesta de corrección
    según el catálogo oficial. ctx puede traer: cympy, inv, defaults, catalog_hints, vbase.
    """
    ctx = ctx or {}
    code = (diag_row.get("Codigo") or "").strip()
    sev = (diag_row.get("Severidad") or "").strip()
    msg = (diag_row.get("Mensaje") or "")
    tipo = (diag_row.get("Tipo") or "").strip()
    obj_id = (diag_row.get("ID_CYMDIST") or "").strip()

    info = lookup(code)
    action = info.get("action") or "revisar"
    auto = bool(info.get("auto_apply"))
    if not tipo:
        tipo = info.get("tipo_default") or "Device"
    if not obj_id and tipo not in ("StudyParam",):
        obj_id = extract_object_id(msg, tipo)

    # Flags settings pueden desactivar auto
    if action == "set_equipment" and not settings.get("auto_fix_default_equipment", True):
        auto = False
    if action == "set_base_voltage" and not settings.get("auto_fix_node_voltage", True):
        auto = False
    if action == "open_tie_switch" and not settings.get("auto_fix_loop_nodes", True):
        auto = False
    if action == "raise_connected_kva" and not settings.get("auto_fix_load_capacity", True):
        auto = False

    obs = "%s | %s" % (info.get("fix_note") or "", (msg or "")[:140])
    vbase = ctx.get("vbase") or settings.get("voltage_ll_kv") or 22.9
    row = {
        "Activo": bool(auto and action != "revisar"),
        "Tipo": tipo,
        "ID_CYMDIST": obj_id,
        "ID_Seccion": obj_id if tipo not in ("Node", "StudyParam") else "",
        "Equipo_Actual": "",
        "Equipo_Nuevo": "",
        "BaseVoltage_kV": "",
        "Fase": "",
        "Observacion": obs.strip(" |"),
        "Origen_Dato": info.get("source") or "cymdist.cymsg",
        "Codigo": code or "(sin_codigo)",
        "Accion_Sugerida": action,
        "Severidad": sev,
        "Mensaje_CYME": info.get("message") or "",
    }

    # Especialización por acción (relleno de campos de la tabla Correcciones)
    if action == "set_base_voltage":
        row["Tipo"] = "Node"
        row["BaseVoltage_kV"] = vbase
        row["Activo"] = bool(auto and obj_id)
        if not obj_id:
            row["Activo"] = False
            row["Accion_Sugerida"] = "revisar"
            row["Observacion"] = "220052/220009 sin nodo parseable. " + obs

    elif action == "set_equipment":
        row = _fill_equipment(row, settings, ctx, auto)

    elif action == "raise_connected_kva":
        row["Tipo"] = "Load"
        row["Fase"] = "ABC"
        row["Activo"] = bool(auto and obj_id)

    elif action == "open_tie_switch":
        row["Tipo"] = "Node"
        row["Activo"] = bool(auto and obj_id)

    elif action in ("fix_lf_warnings", "ensure_valid_base_voltages",
                    "enable_diagnostic_checks", "fix_diagnostic_limits",
                    "tighten_lf_tolerance"):
        row["Tipo"] = "StudyParam"
        row["ID_CYMDIST"] = code or action
        row["ID_Seccion"] = ""
        row["Activo"] = bool(auto)

    elif action == "revisar":
        row["Activo"] = False

    else:
        # Handlers genéricos de dispositivo: requieren ID
        row["Activo"] = bool(auto and (obj_id or row["Tipo"] == "StudyParam"))
        if auto and not obj_id and row["Tipo"] not in ("StudyParam",):
            row["Activo"] = False
            row["Accion_Sugerida"] = "revisar"
            row["Observacion"] = "Sin ID para auto-fix. " + obs

    return row


def _fill_equipment(row, settings, ctx, auto):
    """220047 — EquipmentModeling: equipo real de biblioteca, nunca inventar IDs."""
    from core.equipment_library import pick_equipment, EQ_TYPE_MAP, equipment_exists

    tipo = row.get("Tipo") or "OverheadLine"
    obj_id = row.get("ID_CYMDIST") or ""
    defaults = ctx.get("defaults") or settings.get("default_equipment") or {}
    preferred = defaults.get(tipo) or defaults.get("Cable" if tipo == "Underground" else "") or ""
    hints = ctx.get("catalog_hints") or {}
    size = hints.get((tipo, preferred))
    cympy = ctx.get("cympy")
    inv = ctx.get("inv") or {}

    row["Equipo_Actual"] = "DEFAULT"
    row["Fase"] = "ABC"
    if not obj_id or not tipo:
        row["Activo"] = False
        row["Accion_Sugerida"] = "revisar"
        row["Observacion"] = "220047 sin Tipo/ID. " + (row.get("Observacion") or "")
        return row

    if cympy is not None:
        eq_id, how = pick_equipment(cympy, tipo, preferred_id=preferred, size_mm2=size, inventory=inv)
    else:
        eq_id, how = (preferred if preferred else None), "settings_fallback"

    if not eq_id:
        row["Activo"] = False
        row["Accion_Sugerida"] = "revisar"
        row["Observacion"] = (
            "PENDIENTE: sin equipo en biblioteca CYMDIST (EquipmentModeling). "
            + (row.get("Observacion") or "")
        )
        return row

    eq_tipo = EQ_TYPE_MAP.get(tipo, tipo)
    if cympy is not None and not equipment_exists(cympy, eq_id, eq_tipo):
        row["Activo"] = False
        row["Accion_Sugerida"] = "revisar"
        row["Equipo_Nuevo"] = eq_id
        row["Observacion"] = "Equipo candidato inexistente en biblioteca. " + (row.get("Observacion") or "")
        return row

    row["Equipo_Nuevo"] = eq_id
    row["Activo"] = bool(auto)
    row["Observacion"] = "Equipo biblioteca (%s). %s" % (how, row.get("Observacion") or "")
    row["Origen_Dato"] = "EquipmentModeling + eq.ListEquipments"
    return row


# ---------------------------------------------------------------------------
# Aplicadores (bulk_fix)
# ---------------------------------------------------------------------------

def apply_action(adapter, settings, row):
    """
    Ejecuta Accion_Sugerida sobre el estudio abierto.
    Devuelve (action, before, after).
    """
    action = (row.get("Accion_Sugerida") or "").strip() or "revisar"
    tipo = (row.get("Tipo") or "").strip()
    obj_id = (row.get("ID_CYMDIST") or "").strip()
    code = (row.get("Codigo") or "").strip()
    vll = float(settings.get("voltage_ll_kv") or 22.9)

    if action == "revisar":
        return action, "", "SKIP revisar"

    if action == "set_base_voltage":
        before, after = adapter.set_node_base_voltage(obj_id, float(row.get("BaseVoltage_kV") or vll))
        return action, before, after

    if action == "set_equipment":
        eq = row.get("Equipo_Nuevo")
        if not eq:
            raise RuntimeError("set_equipment sin Equipo_Nuevo")
        before, after = adapter.set_equipment(tipo, obj_id, eq)
        return action, before, after

    if action == "raise_connected_kva":
        before, after, field, how = adapter.raise_load_connected_kva(obj_id)
        return action, before, "%s=%s (%s)" % (field, after, how)

    if action == "open_tie_switch":
        info = adapter.open_tie_at_loop_node(obj_id, settings.get("network_id"))
        before = "%s.%s=%s" % (info.get("device"), info.get("field"), info.get("before"))
        after = "%s=%s" % (info.get("field"), info.get("after"))
        return action, before, after

    if action == "fix_lf_warnings":
        from pipeline.fix_lf_warnings import run as fix_lf
        # Caller debe haber cerrado study si hace falta; aquí asumimos estudio usable
        # Mejor: invocar y reportar
        raise _NeedsStudyRestart("fix_lf_warnings")

    if action == "ensure_valid_base_voltages":
        from pipeline.fix_base_voltages import ensure_base_voltages
        res = ensure_base_voltages(adapter.cympy, settings, adapter)
        return action, "", str(res)

    if action == "enable_diagnostic_checks":
        _enable_diagnostic_checks(adapter)
        return action, "", "checks_enabled"

    if action == "fix_diagnostic_limits":
        _fix_diagnostic_limits(adapter, settings, code)
        return action, "", "limits_ok"

    if action == "tighten_lf_tolerance":
        _tighten_lf_tolerance(adapter)
        return action, "", "tolerance_ok"

    if action == "align_transformer_voltages":
        return _set_transformer_voltages(adapter, obj_id, vll)

    if action == "align_device_rated_voltage":
        return _try_set_fields(adapter, obj_id, tipo, {
            "RatedVoltage": vll,
            "RatedVoltageKV": vll,
            "RatedVoltageKVLN": vll / math.sqrt(3.0),
        })

    if action == "align_device_operating_voltage":
        vln = vll / math.sqrt(3.0)
        return _try_set_fields(adapter, obj_id, tipo, {
            "OperatingVoltageA": vln,
            "OperatingVoltageB": vln,
            "OperatingVoltageC": vln,
            "OperatingVoltage": vll,
        })

    if action == "align_control_voltage":
        return _try_set_fields(adapter, obj_id, tipo, {
            "ControlledVoltage": vll,
            "DesiredVoltage": vll,
        })

    if action == "set_min_impedance":
        # Valor mínimo seguro típico (p.u. o ohm según campo); intentar campos comunes
        zmin = float(settings.get("min_impedance_pu") or 0.0001)
        fields = {
            "PositiveSequenceResistance": zmin,
            "PositiveSequenceReactance": zmin,
            "ZeroSequenceResistance": zmin,
            "ZeroSequenceReactance": zmin,
            "NegativeSequenceResistance": zmin,
            "NegativeSequenceReactance": zmin,
            "R1": zmin, "X1": zmin, "R0": zmin, "X0": zmin, "R2": zmin, "X2": zmin,
            "TransientReactance": zmin,
            "SubtransientReactance": zmin,
        }
        # Solo tocar campos que estén en 0
        return _set_zero_fields_to(adapter, obj_id, tipo, fields, zmin)

    if action == "fix_q_limits":
        return _fix_q_minmax(adapter, obj_id, tipo)

    if action == "fix_bandwidth":
        return _try_set_fields(adapter, obj_id, tipo, {
            "Bandwidth": 0.1,
            "ReverseBandwidth": 0.1,
            "BandWidth": 0.1,
        }, only_if_below=0.1)

    if action == "fix_voltage_thresholds":
        return _try_set_fields(adapter, obj_id, tipo, {
            "MaxOvervoltage": 1.0,
            "MaxUndervoltage": 1.0,
            "OvervoltageThreshold": 1.0,
            "UndervoltageThreshold": 1.0,
        }, only_if_below=1.0)

    if action == "fix_shunt_thresholds":
        return _fix_shunt_close_open(adapter, obj_id)

    if action == "fix_trip_currents":
        return _try_set_fields(adapter, obj_id, tipo, {
            "PhaseTripCurrent": 1.0,
            "NeutralTripCurrent": 1.0,
            "TripCurrent": 1.0,
            "PickupCurrent": 1.0,
        }, only_if_zero=True)

    if action == "raise_device_pf":
        pf_min = float(settings.get("min_device_pf") or 0.85)
        return _try_set_fields(adapter, obj_id, tipo, {
            "PowerFactor": pf_min,
            "PF": pf_min,
            "MinPowerFactor": pf_min,
        })

    if action == "raise_length_limit":
        # Preferible subir límite del diagnóstico que acortar línea (datos GIS)
        return _raise_nd_length_limit(adapter, settings), "", "length_limit_raised"

    if action == "fix_ltc_desired_voltage":
        return _try_set_fields(adapter, obj_id, tipo, {
            "DesiredVoltage": vll,
            "ControlledVoltage": vll,
        })

    if action == "sync_device_from_equipment_db":
        # Mejor esfuerzo: re-asignar mismo EquipmentID para refrescar límites
        return _refresh_equipment_id(adapter, obj_id, tipo)

    if action == "flag_disconnected_section":
        # Marcar en observación; intentar ConnectionStatus=Connected en sección
        return _try_connect_section(adapter, obj_id, settings)

    if action == "fix_load_limit":
        return _try_set_fields(adapter, obj_id, tipo, {
            "LoadLimit": 100.0,
            "MaxLoad": 100.0,
            "ConnectedKVA": 100.0,
        }, only_if_zero=True)

    if action == "fix_pf_percent":
        # Si FP parece p.u. (<1.5), convertir a %
        return _fix_pf_to_percent(adapter, obj_id, tipo)

    raise RuntimeError("Acción no implementada: %s (código %s)" % (action, code))


class _NeedsStudyRestart(Exception):
    """Señal para bulk_fix: cerrar estudio, correr fix_lf_warnings, reabrir."""
    pass


def _device(adapter, tipo, obj_id):
    """Resuelve dispositivo probando tipos conocidos."""
    candidates = []
    if tipo and tipo not in ("Device", "StudyParam", "?"):
        candidates.append(tipo)
    candidates.extend([
        "Load", "Transformer", "OverheadLine", "Cable", "Sectionalizer",
        "Switch", "ShuntCapacitor", "Source",
    ])
    last = None
    for name in candidates:
        try:
            # Mapear a nombres del api map
            key = name
            if name == "Switch":
                key = "Sectionalizer"
            if key not in adapter.api.get("objects", {}):
                # GetDevice directo por enum
                dt = getattr(adapter.cympy.enums.DeviceType, name, None)
                if dt is None:
                    continue
                d = adapter.cympy.study.GetDevice(str(obj_id), dt)
                if d is not None:
                    return d, name
                continue
            return adapter.get_device(key, obj_id), key
        except Exception as ex:
            last = ex
            continue
    raise RuntimeError("Dispositivo no encontrado %s (%s): %s" % (obj_id, tipo, last))


def _try_set_fields(adapter, obj_id, tipo, field_values, only_if_below=None, only_if_zero=False):
    d, used = _device(adapter, tipo, obj_id)
    notes_b, notes_a = [], []
    n_ok = 0
    for fld, val in field_values.items():
        try:
            before = d.GetValue(fld)
            try:
                bnum = float(str(before).replace(",", "."))
            except Exception:
                bnum = None
            if only_if_zero and bnum is not None and abs(bnum) > 1e-12:
                continue
            if only_if_below is not None and bnum is not None and bnum >= only_if_below:
                continue
            d.SetValue(val, fld)
            after = d.GetValue(fld)
            notes_b.append("%s=%s" % (fld, before))
            notes_a.append("%s=%s" % (fld, after))
            n_ok += 1
        except Exception:
            continue
    if n_ok == 0:
        raise RuntimeError("Ningún campo aplicable en %s/%s" % (used, obj_id))
    return "set_fields", "; ".join(notes_b), "; ".join(notes_a)


def _set_zero_fields_to(adapter, obj_id, tipo, fields, zmin):
    return _try_set_fields(adapter, obj_id, tipo, fields, only_if_zero=True)


def _fix_q_minmax(adapter, obj_id, tipo):
    d, used = _device(adapter, tipo, obj_id)
    pairs = (
        ("Qmin", "Qmax"),
        ("MinReactivePower", "MaxReactivePower"),
        ("QMin", "QMax"),
    )
    for qmin_f, qmax_f in pairs:
        try:
            qmin = float(str(d.GetValue(qmin_f)).replace(",", "."))
            qmax = float(str(d.GetValue(qmax_f)).replace(",", "."))
            if qmax < qmin or abs(qmax - qmin) < 1e-9:
                new_max = qmin + 1.0 if qmax <= qmin else qmax
                before = "%s=%s %s=%s" % (qmin_f, qmin, qmax_f, qmax)
                d.SetValue(float(new_max), qmax_f)
                after = "%s=%s %s=%s" % (qmin_f, qmin, qmax_f, d.GetValue(qmax_f))
                return "fix_q_limits", before, after
        except Exception:
            continue
    raise RuntimeError("No se leyeron Qmin/Qmax en %s/%s" % (used, obj_id))


def _fix_shunt_close_open(adapter, obj_id):
    d, used = _device(adapter, "ShuntCapacitor", obj_id)
    for close_f, open_f in (
        ("CloseThreshold", "OpenThreshold"),
        ("ClosingThreshold", "OpeningThreshold"),
        ("OnThreshold", "OffThreshold"),
    ):
        try:
            c = float(str(d.GetValue(close_f)).replace(",", "."))
            o = float(str(d.GetValue(open_f)).replace(",", "."))
            if abs(c - o) < 1e-9:
                before = "%s=%s %s=%s" % (close_f, c, open_f, o)
                d.SetValue(c + 0.02, open_f)
                after = "%s=%s %s=%s" % (close_f, c, open_f, d.GetValue(open_f))
                return "fix_shunt_thresholds", before, after
        except Exception:
            continue
    raise RuntimeError("Umbrales shunt no encontrados en %s" % obj_id)


def _enable_diagnostic_checks(adapter):
    nd = adapter.cympy.study.NetworkDiagnostic()
    # Habilitar verificaciones típicas usadas por RECYM
    paths = [
        "PreDeterminedNetworkBaseVoltagesVerification.Enable",
        "DefaultEquipmentVerification.Enable",
        "LoopNodeVerification.Enable",
        "DisconnectedSectionVerification.Enable",
    ]
    for p in paths:
        try:
            nd.SetValue(True, p)
        except Exception:
            pass
    return "enable_diagnostic_checks"


def _fix_diagnostic_limits(adapter, settings, code):
    nd = adapter.cympy.study.NetworkDiagnostic()
    vll = float(settings.get("voltage_ll_kv") or 22.9)
    # Límites mínimos sensatos según mensajes 220025–220027
    attempts = [
        ("PowerFactorLimit", 0.8),
        ("MinPowerFactor", 0.8),
        ("MaxLength", 50.0),
        ("MaximumLength", 50.0),
        ("OverheadLineMaxLength", 50.0),
        ("CableMaxLength", 50.0),
        ("DesiredVoltageMin", vll * 0.9),
        ("DesiredVoltageMax", vll * 1.1),
        ("MinDesiredVoltage", vll * 0.9),
        ("MaxDesiredVoltage", vll * 1.1),
    ]
    n = 0
    for path, val in attempts:
        for prefix in ("", "LengthVerification.", "DesiredVoltageVerification.",
                       "PowerFactorVerification."):
            try:
                nd.SetValue(val, prefix + path)
                n += 1
            except Exception:
                pass
    if n == 0:
        raise RuntimeError("No se pudieron fijar límites del NetworkDiagnostic (%s)" % code)
    return "fix_diagnostic_limits"


def _raise_nd_length_limit(adapter, settings):
    _fix_diagnostic_limits(adapter, settings, "220004")
    return "raise_length_limit"


def _tighten_lf_tolerance(adapter):
    c = adapter.cympy
    sim = c.sim.LoadFlow()
    base = "LoadFlowParameters"
    for path, val in (
        (base + ".ConvergenceTolerance", 0.001),
        (base + ".VoltageTolerance", 0.001),
        (base + ".Tolerance", 0.001),
    ):
        try:
            sim.SetValue(val, path)
            return "tighten_lf_tolerance"
        except Exception:
            continue
    # Alternativa vía study params
    raise RuntimeError("No se pudo ajustar tolerancia LoadFlow")


def _set_transformer_voltages(adapter, obj_id, vll):
    # Primario = Vll red; secundario típico BT 0.48 si no se conoce
    sec = 0.48
    try:
        sec = float((adapter.settings or {}).get("secondary_voltage_kv") or 0.48)
    except Exception:
        sec = 0.48
    fields = {
        "PrimaryVoltage": vll,
        "SecondaryVoltage": sec,
        "RatedPrimaryVoltage": vll,
        "RatedSecondaryVoltage": sec,
        "UserDefinedBaseVoltagePrimary": vll,
        "UserDefinedBaseVoltageSecondary": sec,
    }
    return _try_set_fields(adapter, obj_id, "Transformer", fields)


def _refresh_equipment_id(adapter, obj_id, tipo):
    d, used = _device(adapter, tipo, obj_id)
    for fld in ("DeviceID", "LineID", "CableID", "EquipmentID", "TransformerID"):
        try:
            cur = d.GetValue(fld)
            if cur in (None, "", "DEFAULT", "Predeterminado"):
                continue
            d.SetValue(str(cur), fld)
            return "sync_device_from_equipment_db", str(cur), str(d.GetValue(fld))
        except Exception:
            continue
    raise RuntimeError("No se pudo refrescar EquipmentID en %s" % obj_id)


def _try_connect_section(adapter, section_id, settings):
    c = adapter.cympy
    net = str(settings.get("network_id") or "")
    # Intentar Localizar sección y dispositivos; marcar Connected
    try:
        # Algunos estudios exponen ConnectionStatus en el tramo vía dispositivos
        for dtype_name in ("Sectionalizer", "Switch", "Breaker", "Fuse"):
            try:
                dtype = getattr(c.enums.DeviceType, dtype_name)
                for d in list(c.study.ListDevices(dtype, net) if net else []):
                    try:
                        sec = str(getattr(d, "SectionID", None) or d.GetValue("SectionID") or "")
                    except Exception:
                        sec = ""
                    if sec != str(section_id):
                        continue
                    for fld, val in (("ClosedPhase", "ABC"), ("Status", "Closed"),
                                    ("ConnectionStatus", "Connected")):
                        try:
                            before = d.GetValue(fld)
                            d.SetValue(val, fld)
                            return "flag_disconnected_section", str(before), str(d.GetValue(fld))
                        except Exception:
                            continue
            except Exception:
                continue
    except Exception as ex:
        raise RuntimeError("Sección desconectada %s: %s" % (section_id, ex))
    # Sin dispositivo: dejar constancia (caller marca OK con nota)
    return "flag_disconnected_section", section_id, "sin_dispositivo_auto; revisar topologia"


def _fix_pf_to_percent(adapter, obj_id, tipo):
    d, used = _device(adapter, tipo, obj_id)
    for fld in ("PowerFactor", "PF", "LoadPowerFactor"):
        try:
            raw = d.GetValue(fld)
            val = float(str(raw).replace(",", "."))
            if 0 < val <= 1.5:
                before = str(raw)
                d.SetValue(val * 100.0, fld)
                return "fix_pf_percent", before, str(d.GetValue(fld))
        except Exception:
            continue
    raise RuntimeError("PF no convertible en %s" % obj_id)
