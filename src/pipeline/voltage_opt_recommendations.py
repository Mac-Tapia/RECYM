# -*- coding: utf-8 -*-
"""Recomendaciones §7 tras diagnóstico 2.1 cuando hay muchas caídas / problemas de tensión.

Orden de solución:
  1) 7.1c · Ubicación óptima de bancos de condensadores (CapacitorPlacement)
  2) 7.1b · Ubicación óptima de reguladores (RegulatorPlacement / módulo CYME)

Usa equipos ya creados en la biblioteca CYMDIST (p.ej. BC22.9KV).
"""
from __future__ import print_function
import re

# Códigos CYMDIST tipicamente ligados a tensión / condensadores / sensibilidad
VOLTAGE_CODES = (
    "220052",  # voltaje de base en nodo
    "260035",  # VoltageSensitivity
    "480010",  # tensión nominal condensador
)

_RE_VOLTAGE = re.compile(
    r"(ca[ií]da\s+de\s+tensi[oó]n|tensi[oó]n\s+baja|voltaje\s+bajo|"
    r"undervolt|overvolt|vmin|vmax|fuera\s+de\s+(?:l[ií]mite|rango).{0,40}tensi|"
    r"voltaje\s+de\s+base|rated\s+voltage|operating\s+voltage|"
    r"voltage\s+(?:drop|violation|limit|sensitivity))",
    re.IGNORECASE,
)


def _iter_messages(summary):
    """Une top_errors + filas si existen."""
    rows = []
    for r in (summary or {}).get("top_errors") or []:
        rows.append(r)
    for r in (summary or {}).get("rows") or []:
        rows.append(r)
    return rows


def count_voltage_issues(summary):
    """Cuenta problemas de tensión en el summary de NetworkDiagnostic."""
    summary = summary or {}
    by_code = summary.get("by_code") or {}
    n_code = 0
    codes_hit = {}
    for code in VOLTAGE_CODES:
        n = int(by_code.get(code) or 0)
        if n:
            codes_hit[code] = n
            n_code += n

    n_msg = 0
    samples = []
    seen = set()
    for r in _iter_messages(summary):
        code = str(r.get("Codigo") or r.get("Code") or "").strip()
        text = str(r.get("Mensaje") or r.get("Message") or r.get("Detalle") or "")
        key = (code, text[:80])
        if key in seen:
            continue
        seen.add(key)
        hit = False
        if code in VOLTAGE_CODES:
            hit = True
        elif _RE_VOLTAGE.search(text):
            hit = True
        if hit:
            n_msg += 1
            if len(samples) < 8:
                samples.append({
                    "Codigo": code,
                    "Mensaje": text[:160],
                    "ID_CYMDIST": r.get("ID_CYMDIST") or r.get("ID") or "",
                })

    # Evitar doble conteo: usar max(códigos, mensajes) como señal principal
    n = max(n_code, n_msg)
    return {
        "n_voltage_issues": n,
        "n_from_codes": n_code,
        "n_from_messages": n_msg,
        "codes": codes_hit,
        "samples": samples,
    }


def build_voltage_opt_recommendations(summary, settings=None):
    """Si hay muchas caídas/problemas de tensión → recomendar 7.1c luego 7.1b.

    Threshold: settings.voltage_drop_opt_threshold (default 3).
    """
    s = settings or {}
    try:
        threshold = int(s.get("voltage_drop_opt_threshold") or 3)
    except Exception:
        threshold = 3
    if threshold < 1:
        threshold = 1

    stats = count_voltage_issues(summary)
    n = int(stats.get("n_voltage_issues") or 0)
    out = {
        "ok": True,
        "triggered": False,
        "n_voltage_issues": n,
        "threshold": threshold,
        "codes": stats.get("codes") or {},
        "samples": stats.get("samples") or [],
        "recommendations": [],
        "msg": "",
    }
    if n < threshold:
        out["msg"] = (
            "Sin recomendación §7: problemas de tensión=%d (umbral=%d)."
            % (n, threshold)
        )
        return out

    caps_eq = None
    reg_eq = None
    de = s.get("default_equipment") or {}
    if isinstance(de, dict):
        caps_eq = de.get("ShuntCapacitor") or de.get("Capacitor")
        reg_eq = de.get("Regulator")
    caps_eq = caps_eq or s.get("opt_capacitor_equipment") or "BC22.9KV"
    reg_eq = reg_eq or s.get("opt_regulator_equipment") or "REG22.9KV"

    out["triggered"] = True
    out["recommendations"] = [
        {
            "priority": 1,
            "step": "7.1c",
            "action": "capacitors",
            "path": "/api/optimizacion/capacitors",
            "ui_path": "/7",
            "title": "Ubicación óptima de bancos de condensadores",
            "module": "CapacitorPlacement",
            "equipment_id": caps_eq,
            "reason": (
                "Primero compensar reactiva / perfil de tensión con bancos "
                "(equipo CYMDIST %s ya en biblioteca)." % caps_eq
            ),
        },
        {
            "priority": 2,
            "step": "7.1b",
            "action": "regulators",
            "path": "/api/optimizacion/regulators",
            "ui_path": "/7",
            "title": "Ubicación óptima de reguladores",
            "module": "RegulatorPlacement",
            "equipment_id": reg_eq,
            "reason": (
                "Después, ubicar reguladores de tensión "
                "(equipo CYMDIST %s) si persisten caídas." % reg_eq
            ),
        },
    ]
    out["msg"] = (
        "Muchas caidas/problemas de tension (%d >= %d). "
        "Solucion recomendada: 1) §7 · 7.1c Capacitores · 2) §7 · 7.1b Reguladores."
        % (n, threshold)
    )
    return out


def attach_recommendations_to_summary(summary, settings=None):
    """Mutates/returns summary dict with voltage_opt block."""
    summary = dict(summary or {})
    rec = build_voltage_opt_recommendations(summary, settings=settings)
    summary["voltage_opt"] = rec
    if rec.get("triggered"):
        summary["recommendation_msg"] = rec.get("msg")
    return summary
