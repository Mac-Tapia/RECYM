from __future__ import print_function
"""Ejecuta NetworkDiagnostic de CYMDIST y exporta errores al tablero."""
import os
import re
import sys
import json
from collections import Counter
from core.common import require_cympy, load_json, write_csv, ts, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path

RE_NODE = re.compile(r"nodo\s+(\S+)", re.IGNORECASE)
RE_LOOP = re.compile(r"nodo\s+de\s+bucle\s+(\S+)", re.IGNORECASE)
RE_OH = re.compile(r"L[ií]nea\s+a[eé]rea\s+(\S+)", re.IGNORECASE)
RE_UG = re.compile(r"(?:Cable|subterr[aá]ne[oa]|Underground)\s+(\S+)", re.IGNORECASE)
RE_SW = re.compile(r"Seccionador\s+(\S+)", re.IGNORECASE)
RE_TR = re.compile(r"Transformador\s+(\S+)", re.IGNORECASE)
RE_LOAD = re.compile(r"carga\s+concentrada\s+(\S+)", re.IGNORECASE)
RE_CAP = re.compile(r"(?:condensador|capacitor|shunt)\s+(\S+)", re.IGNORECASE)
RE_INFO_DONE = re.compile(r"Diagn[oó]stico\s+finalizado", re.IGNORECASE)

# Severidades que exigen corrección en el gate de calidad
PROBLEM_SEVERITIES = ("Error", "Warning", "Hint")

def _sev_name(cympy, sev):
    for n in ("Error", "Warning", "Information", "Hint", "All"):
        if getattr(cympy.enums.Severity, n) == sev:
            return n
    return str(sev)

def is_informational_noise(code, text, severity=""):
    """Mensajes de cierre / sin problema real — no generan corrección."""
    if (severity or "").lower() == "information" and not (code or "").strip():
        return True
    if RE_INFO_DONE.search(text or ""):
        return True
    return False

def parse_issue(code, text):
    code_s = str(code or "")
    text_s = text or ""
    low = text_s.lower()

    m = RE_LOOP.search(text_s)
    if m or code_s == "220048" or "nodo de bucle" in low:
        node = m.group(1).rstrip(".,;") if m else ""
        if not node:
            m2 = RE_NODE.search(text_s)
            node = m2.group(1).rstrip(".,;") if m2 else ""
        return "Node", node, "220048"

    m = RE_NODE.search(text_s)
    if m and (code_s == "220052" or "voltaje de base" in low):
        return "Node", m.group(1).rstrip(".,;"), "220052"

    m = RE_OH.search(text_s)
    if m:
        return "OverheadLine", m.group(1).rstrip(".,;"), code_s or "220047"
    m = RE_SW.search(text_s)
    if m:
        return "Sectionalizer", m.group(1).rstrip(".,;"), code_s or "220047"
    m = RE_UG.search(text_s)
    if m:
        return "Cable", m.group(1).rstrip(".,;"), code_s or "220047"
    m = RE_TR.search(text_s)
    if m:
        return "Transformer", m.group(1).rstrip(".,;"), code_s or "220047"
    m = RE_LOAD.search(text_s)
    if m:
        return "Load", m.group(1).rstrip(".,;"), code_s or "260044"
    m = RE_CAP.search(text_s)
    if m:
        return "ShuntCapacitor", m.group(1).rstrip(".,;"), code_s or "480010"

    # Códigos conocidos sin ID en el texto
    if code_s == "480010":
        return "StudyParam", "ShuntCapacitor", code_s
    if code_s == "260035":
        return "StudyParam", "VoltageSensitivity", code_s
    return "", "", code_s

def _suffix():
    for arg in sys.argv[1:]:
        if arg.startswith("--suffix="):
            return arg.split("=", 1)[1].strip()
    return os.environ.get("RECYM_DIAG_SUFFIX", "").strip()

def main(settings=None):
    """settings opcional: si viene de la UI, no re-leer RECYM_FEEDER/activo."""
    s = settings or load_settings()
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()

    net = s.get("network_id")
    if not net:
        raise RuntimeError("Falta network_id para NetworkDiagnostic (feeder=%s)" % s.get("feeder_id"))
    # Asegurar red cargada (estudios multi-red / ELD)
    try:
        loaded = [str(x) for x in list(c.study.ListNetworks())]
        if str(net) not in loaded:
            c.study.LoadNetwork(str(net), c.enums.LoadNetworkOption.NoDependencies)
    except Exception as ex:
        print("AVISO LoadNetwork %s: %s" % (net, ex))
    nd = c.study.NetworkDiagnostic()
    nd.Run([str(net)])
    print("[%s] NetworkDiagnostic OK" % s["feeder_id"])

    tag = _suffix()
    suffix = ("_" + tag) if tag else ""

    rows = []
    by_code = Counter()
    by_type = Counter()
    for m in list(c.app.GetMessages(c.enums.Severity.All)):
        code = str(getattr(m, "Code", "") or "")
        text = str(getattr(m, "Text", "") or "")
        sev = _sev_name(c, getattr(m, "Severity", None))
        cat = str(getattr(m, "Category", "") or "")
        if cat.lower().startswith("script"):
            continue
        if is_informational_noise(code, text, sev):
            continue
        tipo, obj_id, code2 = parse_issue(code, text)
        code = code2 or code
        by_code[code or "(sin_codigo)"] += 1
        if tipo:
            by_type[tipo] += 1
        details = []
        try:
            details = [str(x) for x in list(m.GetDetails())]
        except Exception:
            pass
        rows.append({
            "Feeder": s["feeder_id"],
            "NetworkID": net,
            "Codigo": code,
            "Severidad": sev,
            "Categoria": cat,
            "Tipo": tipo,
            "ID_CYMDIST": obj_id,
            "Mensaje": text,
            "Detalle": " | ".join(details),
            "Requiere_Correccion": "SI" if sev in PROBLEM_SEVERITIES else "NO",
        })

    out_csv = output_path(s, "diagnostics", "cymdist_diagnostic_errors%s.csv" % suffix)
    _diag_headers = [
        "Feeder", "NetworkID", "Codigo", "Severidad", "Categoria",
        "Tipo", "ID_CYMDIST", "Mensaje", "Detalle", "Requiere_Correccion",
    ]
    write_csv(out_csv, rows, _diag_headers)
    # CSV canónico para el builder (solo fase before)
    if not tag:
        canon = output_path(s, "diagnostics", "cymdist_diagnostic_errors.csv")
        if out_csv != canon:
            write_csv(canon, rows, _diag_headers)

    n_problems = sum(1 for r in rows if (r.get("Requiere_Correccion") or "") == "SI")
    summary = {
        "utility": s.get("utility_name"),
        "feeder_id": s["feeder_id"],
        "network_id": net,
        "study_path": s.get("study_path"),
        "timestamp": ts(),
        "phase": tag or "before",
        "total_messages": len(rows),
        "n_problems": n_problems,
        "n_errors": sum(1 for r in rows if (r.get("Severidad") or "") == "Error"),
        "n_warnings": sum(1 for r in rows if (r.get("Severidad") or "") == "Warning"),
        "n_hints": sum(1 for r in rows if (r.get("Severidad") or "") == "Hint"),
        "by_code": dict(by_code.most_common()),
        "by_type": dict(by_type.most_common()),
        "by_severity": dict(Counter(r["Severidad"] for r in rows)),
        "top_errors": [
            {
                "Codigo": r["Codigo"],
                "Tipo": r["Tipo"],
                "ID_CYMDIST": r["ID_CYMDIST"],
                "Severidad": r["Severidad"],
                "Mensaje": (r["Mensaje"] or "")[:180],
            }
            for r in rows[:40]
        ],
        "ready_model": n_problems == 0,
        "csv": out_csv,
    }
    out_json = output_path(s, "diagnostics", "dashboard_summary%s.json" % suffix)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    if not tag:
        with open(output_path(s, "diagnostics", "dashboard_summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

    print("Total mensajes:", len(rows))
    print("Por codigo:", dict(by_code.most_common(10)))
    print("Por tipo:", dict(by_type.most_common()))
    print("CSV:", out_csv)
    print("JSON:", out_json)
    # No llamar Close: dispara ACCESS_VIOLATION en CymPy 9.2; salir con os._exit.

if __name__ == "__main__":
    run_cympy_main(main)
