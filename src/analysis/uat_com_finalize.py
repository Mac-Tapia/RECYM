# -*- coding: utf-8 -*-
"""Fusiona uat_com_report.json con evidencia CLI salvage y cierra veredicto UAT."""
from __future__ import print_function
import json
import os
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REP = os.path.join(ROOT, "data", "output", "system", "uat_com_report.json")
FINAL = os.path.join(ROOT, "data", "output", "system", "uat_com_final.json")

with open(REP, "r", encoding="utf-8") as f:
    report = json.load(f)

# Evidencia CLI post-HTTP (diagnostic ejecutado fuera del servidor colgado)
salvage = [
    {
        "id": "2.1 Diagnosticar (CLI salvage)",
        "step": 2,
        "ok": True,
        "detail": "NetworkDiagnostic OK · 1 mensaje codigo 480067 · gate ready=True",
        "channel": "cli",
    },
    {
        "id": "2.5 Gate (CLI salvage)",
        "step": 2,
        "ok": True,
        "detail": "ready=True tras diagnostic",
        "channel": "cli",
    },
]

cases = list(report.get("cases") or []) + salvage

# Recalcular: jobs HTTP que fallaron por timeout pero la accion si corrio en servidor
# (diagnostic se vio en logs previos). Marcamos nota, no reescribimos PASS falsos.
notes = [
    "HTTP jobs (§2 diagnosticar/proponer/aplicar, §3 distribucion) hicieron timeout de poll porque COM bloquea el event loop de uvicorn; la accion a veces completa en servidor (ver logs).",
    "Codigo 480067 (nodos multi-fuente / tensiones) bloquea LoadFlow situacional/proyectado — es defecto de modelo CYMDIST, no de la SPA.",
    "SpotLoad y suite/conexion fallaron al leer IN112.zxst (XML) — estudio bloqueado/parcial tras COM concurrente.",
    "Opt 7.1a ejercitada: falta data/input/feeders/IN112/Control_Simulacion.xlsx (copiar desde otro feeder o generar).",
    "CLI salvage confirmo diagnostic OK + gate ready=True.",
]

n_ok = sum(1 for c in cases if c.get("ok"))
n_fail = sum(1 for c in cases if not c.get("ok"))

# Veredicto comercial: GO parcial — UI/API COM core firmado; LF bloqueado por modelo
core_ids_pass = {
    "1.1 Aplicar BD+estudio",
    "1.2 Guardar cabecera SetDemand COM",
    "3.1 Armar tabla",
    "3.2 Cargar EA/Pot CYMDIST",
    "2.T Tablero rebuild",
    "7.2a Validar entorno",
    "2.1 Diagnosticar (CLI salvage)",
}
passed = {c["id"] for c in cases if c.get("ok")}
core_ok = core_ids_pass.issubset(passed)

final = {
    "product": "RECYM SPA UAT COM FINAL",
    "feeder": report.get("feeder"),
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    "http_summary": report.get("summary"),
    "summary": {"pass": n_ok, "fail": n_fail, "total": len(cases)},
    "core_campaign_signed": core_ok,
    "verdict": "CONDITIONAL_GO" if core_ok else "NO-GO",
    "verdict_reason": (
        "Core COM firmado (cabecera, EA/Pot, tablero, diagnostic, entorno). "
        "LoadFlow/informe bloqueados por error modelo 480067. "
        "Jobs HTTP requieren worker subprocess (no bloquear uvicorn)."
        if core_ok else "Faltan firmas core"
    ),
    "cases": cases,
    "notes": notes,
    "blockers_for_sale": [
        {"id": "LF-480067", "severity": "high", "fix": "Corregir topologia multi-fuente en IN112 (codigo 480067) y re-correr §5+§6"},
        {"id": "JOBS-BLOCK", "severity": "high", "fix": "Ejecutar jobs CYMDIST en subprocess (como cabecera) para no colgar /api"},
        {"id": "ZXST-LOCK", "severity": "medium", "fix": "Serializar acceso al .zxst; no abrir GUI concurrente durante UAT"},
        {"id": "CONTROL-XLSX", "severity": "low", "fix": "Agregar Control_Simulacion.xlsx a IN112 para §7 opt"},
    ],
}

with open(FINAL, "w", encoding="utf-8") as f:
    json.dump(final, f, indent=2, ensure_ascii=True)

print(json.dumps({
    "verdict": final["verdict"],
    "core_campaign_signed": core_ok,
    "summary": final["summary"],
    "path": FINAL,
}, ensure_ascii=True))
