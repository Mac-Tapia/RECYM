# -*- coding: utf-8 -*-
"""
Diagnóstico NetworkDiagnostic del sistema completo (todos los alimentadores de la BD).

Independiente de §1 cabecera, §2 EA/Pot, §3 SpotLoad y §4 flujos situacional/proyectado.
Usa el modelo ya poblado en la MDB (redes + equipos). Valores por defecto de cabecera
por alimentador no son prerequisito: solo aplican a LoadAllocation.

Flujo (evita error de estudio vacío):
  1. Conectar BD (database_connection_name)
  2. study.New()
  3. LoadNetworks(todas)
  4. Por cada red: NetworkDiagnostic.Run([net]) → mensajes del último comando
  5. CSV/JSON agregados por Codigo / Severidad / Tipo / Feeder

Uso:
  python -u src/analysis/run_system_network_diagnostic.py
  python -u src/analysis/run_system_network_diagnostic.py --limit 5
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import time
import traceback
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))

from core.common import load_json, write_csv, ts, mkdir, p  # noqa: E402
from analysis.run_network_diagnostic import (  # noqa: E402
    PROBLEM_SEVERITIES,
    _sev_name,
    is_informational_noise,
    parse_issue,
)


def _system_out_dir(settings):
    base = settings.get("system_diagnostics_dir") or os.path.join(
        "data", "output", "system", "diagnostics"
    )
    full = base if os.path.isabs(base) else p(*base.replace("\\", "/").split("/"))
    mkdir(full)
    return full


def feeder_id_from_network(network_id):
    """NET_2030_179_PA217 → PA217; NET_2030_156_SL141 → SL141."""
    parts = str(network_id or "").split("_")
    return parts[-1] if parts else str(network_id or "")


def _message_rows(c, feeder_id, network_id):
    rows = []
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
        details = []
        try:
            details = [str(x) for x in list(m.GetDetails())]
        except Exception:
            pass
        rows.append({
            "Feeder": feeder_id,
            "NetworkID": network_id,
            "Codigo": code,
            "Severidad": sev,
            "Categoria": cat,
            "Tipo": tipo,
            "ID_CYMDIST": obj_id,
            "Mensaje": text,
            "Detalle": " | ".join(details),
            "Requiere_Correccion": "SI" if sev in PROBLEM_SEVERITIES else "NO",
        })
    return rows


def run_system_diagnostic(settings=None, network_ids=None, limit=0, connection_name=None):
    """
    Diagnostica todas (o un subconjunto) de redes de la BD compartida.

    Returns dict: ok, summary, rows, csv, json, by_code, by_feeder, errors_by_net
    """
    import cympy
    import cympy.db as db
    import cympy.study as study

    settings = settings or load_json("config/settings.json")
    conn = (
        connection_name
        or settings.get("database_connection_name")
        or "20260919"
    )
    out_dir = _system_out_dir(settings)

    print("[system-diag] Conectar BD:", conn)
    db.ConnectDatabaseByName(conn)

    nets = list(network_ids) if network_ids else list(db.ListNetworks())
    nets = [str(n) for n in nets]
    if limit and limit > 0:
        nets = nets[: int(limit)]
        print("[system-diag] --limit=%d → %d redes" % (limit, len(nets)))
    if not nets:
        raise RuntimeError("No hay redes en la BD / lista vacía.")

    print("[system-diag] Redes a diagnosticar:", len(nets))
    print("[system-diag] study.New() + LoadNetworks...")
    study.New()
    opt = cympy.enums.LoadNetworkOption.NoDependencies
    t_load = time.time()
    study.LoadNetworks(nets, opt)
    loaded = list(study.ListNetworks())
    print(
        "[system-diag] Cargadas %d/%d en %.1fs"
        % (len(loaded), len(nets), time.time() - t_load)
    )

    # cympy root (mismo objeto que usa el adapter: tiene .app / .enums / .study)
    c = cympy
    nd = c.study.NetworkDiagnostic()

    all_rows = []
    per_feeder = {}
    errors_by_net = []
    t0 = time.time()

    for i, net in enumerate(nets, 1):
        fid = feeder_id_from_network(net)
        try:
            nd.Run([str(net)])
            rows = _message_rows(c, fid, net)
            all_rows.extend(rows)
            n_prob = sum(1 for r in rows if r.get("Requiere_Correccion") == "SI")
            per_feeder[fid] = {
                "NetworkID": net,
                "n_messages": len(rows),
                "n_problems": n_prob,
                "n_errors": sum(1 for r in rows if r.get("Severidad") == "Error"),
                "n_warnings": sum(1 for r in rows if r.get("Severidad") == "Warning"),
                "n_hints": sum(1 for r in rows if r.get("Severidad") == "Hint"),
            }
            print(
                "  [%d/%d] %s (%s) msg=%d problems=%d"
                % (i, len(nets), fid, net, len(rows), n_prob)
            )
        except Exception as ex:
            err = {"Feeder": fid, "NetworkID": net, "error": str(ex)}
            errors_by_net.append(err)
            print("  [%d/%d] FAIL %s: %s" % (i, len(nets), net, ex))

    by_code = Counter((r.get("Codigo") or "(sin_codigo)") for r in all_rows)
    by_type = Counter((r.get("Tipo") or "(sin_tipo)") for r in all_rows if r.get("Tipo"))
    by_sev = Counter((r.get("Severidad") or "") for r in all_rows)
    problems = [r for r in all_rows if r.get("Requiere_Correccion") == "SI"]

    # Agrupación por tipo de error (código) → alimentadores afectados
    code_to_feeders = defaultdict(set)
    for r in problems:
        code_to_feeders[r.get("Codigo") or "(sin_codigo)"].add(r.get("Feeder") or "")

    by_code_detail = []
    for code, cnt in by_code.most_common():
        feeders = sorted(code_to_feeders.get(code) or [])
        sample = next((r for r in problems if (r.get("Codigo") or "(sin_codigo)") == code), None)
        by_code_detail.append({
            "Codigo": code,
            "Count": cnt,
            "n_feeders": len(feeders),
            "Feeders": ",".join(feeders[:40]),
            "Tipo": (sample or {}).get("Tipo") or "",
            "Severidad": (sample or {}).get("Severidad") or "",
            "Mensaje_ejemplo": ((sample or {}).get("Mensaje") or "")[:160],
        })

    headers = [
        "Feeder", "NetworkID", "Codigo", "Severidad", "Categoria",
        "Tipo", "ID_CYMDIST", "Mensaje", "Detalle", "Requiere_Correccion",
    ]
    csv_path = os.path.join(out_dir, "cymdist_diagnostic_errors_system.csv")
    write_csv(csv_path, all_rows, headers)

    code_csv = os.path.join(out_dir, "diagnostic_by_code_system.csv")
    write_csv(
        code_csv,
        by_code_detail,
        ["Codigo", "Count", "n_feeders", "Feeders", "Tipo", "Severidad", "Mensaje_ejemplo"],
    )

    summary = {
        "scope": "system",
        "utility": settings.get("utility_name"),
        "connection": conn,
        "timestamp": ts(),
        "independent_of": ["cabecera", "ea_pot", "spot_load_s3", "loadflow_s4"],
        "n_networks_requested": len(nets),
        "n_networks_loaded": len(loaded),
        "n_networks_ok": len(per_feeder),
        "n_networks_fail": len(errors_by_net),
        "elapsed_s": round(time.time() - t0, 1),
        "total_messages": len(all_rows),
        "n_problems": len(problems),
        "n_errors": sum(1 for r in problems if r.get("Severidad") == "Error"),
        "n_warnings": sum(1 for r in problems if r.get("Severidad") == "Warning"),
        "n_hints": sum(1 for r in problems if r.get("Severidad") == "Hint"),
        "by_code": dict(by_code.most_common()),
        "by_type": dict(by_type.most_common()),
        "by_severity": dict(by_sev.most_common()),
        "by_code_detail": by_code_detail[:80],
        "per_feeder": per_feeder,
        "errors_by_net": errors_by_net,
        "ready_model_system": len(problems) == 0 and len(errors_by_net) == 0,
        "csv": csv_path,
        "csv_by_code": code_csv,
        "top_errors": [
            {
                "Feeder": r.get("Feeder"),
                "NetworkID": r.get("NetworkID"),
                "Codigo": r.get("Codigo"),
                "Tipo": r.get("Tipo"),
                "ID_CYMDIST": r.get("ID_CYMDIST"),
                "Severidad": r.get("Severidad"),
                "Mensaje": (r.get("Mensaje") or "")[:180],
            }
            for r in problems[:60]
        ],
    }
    json_path = os.path.join(out_dir, "dashboard_summary_system.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    summary["json"] = json_path

    print("[system-diag] DONE problems=%d csv=%s" % (len(problems), csv_path))
    return {
        "ok": True,
        "summary": summary,
        "rows": all_rows,
        "csv": csv_path,
        "json": json_path,
        "by_code_detail": by_code_detail,
    }


def main(argv=None):
    settings = load_json("config/settings.json")
    ap = argparse.ArgumentParser(description="NetworkDiagnostic sistema (96 alimentadores)")
    ap.add_argument("--limit", type=int, default=0, help="Solo N primeras redes (prueba)")
    ap.add_argument("--connection", default="", help="Nombre conexion CYME")
    ap.add_argument(
        "--networks",
        default="",
        help="Lista NetworkID separada por comas (opcional)",
    )
    args = ap.parse_args(argv)
    nets = [x.strip() for x in args.networks.split(",") if x.strip()] or None
    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(settings)
    except Exception as ex:
        print("AVISO pause CYMDIST:", ex)
    try:
        result = run_system_diagnostic(
            settings,
            network_ids=nets,
            limit=args.limit,
            connection_name=args.connection or None,
        )
        s = result["summary"]
        print(
            "EXPORT OK · redes=%d problems=%d E=%d W=%d H=%d"
            % (
                s.get("n_networks_ok"),
                s.get("n_problems"),
                s.get("n_errors"),
                s.get("n_warnings"),
                s.get("n_hints"),
            )
        )
        return 0
    except Exception as e:
        print("EXPORT FAIL:", e)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
