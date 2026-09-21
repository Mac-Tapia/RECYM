# -*- coding: utf-8 -*-
"""
Herramienta diagnóstica CYMDIST (API NetworkDiagnostic) sobre el estudio ELD.

Estudio: D:\\BaseDatosElectroDunas\\260919BaseDatos\\proyectos\\ELD.zxst
BD: conexion 20260919 (MDB compartida Electro Dunas)

Aplica los mismos checks de la pestaña Topología de la GUI:
  - LoopNodesVerification = Yes
  - PhaseMergingNodesVerification = Yes
  - DisconnectedSectionsVerification = Yes
  - PreDeterminedNetworkBaseVoltagesVerification.Enable = No
  - LoopPointConfigurationMissmatchVerification = Yes

No requiere §1 cabecera / §3 SpotLoad / §4 escenarios.

Uso:
  python -u src/analysis/run_eld_diagnostic.py
  python -u src/analysis/run_eld_diagnostic.py --limit 5
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
from analysis.run_system_network_diagnostic import feeder_id_from_network  # noqa: E402

# Defaults alineados a la GUI «Herramienta diagnóstica» → Topología
TOPOLOGY_SETTINGS = {
    "LoopNodesVerification": True,
    "PhaseMergingNodesVerification": True,
    "DisconnectedSectionsVerification": True,
    "LoopPointConfigurationMissmatchVerification": True,
    "PreDeterminedNetworkBaseVoltagesVerification.Enable": False,
}

# Verificaciones de dispositivos/equipos típicas (pestaña Dispositivos/equipos)
DEVICE_SETTINGS = {
    "DefaultEquipmentVerification.Enable": True,
    "BasicDeviceVerification.Enable": True,
    "PowerFactorValuesVerification.Enable": True,
    "LineCableLengthVerification.Enable": True,
    "DeviceRatedVoltageVerification.Enable": True,
    "ControlsSettingsVerification.Enable": True,
    "ControlRemoteLocationsVerification.Enable": True,
    "IncompleteTCCSettingsVerification.Enable": True,
    "MissingPickupCurrentsVerification.Enable": True,
}

DEFAULT_ELD_STUDY = r"D:\BaseDatosElectroDunas\260919BaseDatos\proyectos\ELD.zxst"


def _out_dir(settings):
    base = settings.get("eld_diagnostics_dir") or os.path.join(
        "data", "output", "system", "diagnostics", "ELD"
    )
    full = base if os.path.isabs(base) else p(*base.replace("\\", "/").split("/"))
    mkdir(full)
    return full


def apply_diagnostic_tool_settings(nd, extra=None):
    """Configura NetworkDiagnostic como la Herramienta diagnóstica de la GUI."""
    applied = {}
    for path, val in list(TOPOLOGY_SETTINGS.items()) + list(DEVICE_SETTINGS.items()):
        try:
            nd.SetValue(val, path)
            applied[path] = nd.GetValue(path)
        except Exception as ex:
            applied[path] = "FAIL:%s" % ex
    if extra:
        for path, val in extra.items():
            try:
                nd.SetValue(val, path)
                applied[path] = nd.GetValue(path)
            except Exception as ex:
                applied[path] = "FAIL:%s" % ex
    return applied


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


def _infer_network_from_text(text, known_nets):
    """Intenta asociar mensaje a NetworkID si aparece en el texto/detalle."""
    t = text or ""
    for net in known_nets:
        if net and net in t:
            return net
    # sufijo alimentador tipo PA217 / SL141
    for net in known_nets:
        fid = feeder_id_from_network(net)
        if fid and ("_%s" % fid) in t:
            return net
    return ""


def run_eld_diagnostic(
    settings=None,
    study_path=None,
    connection_name=None,
    limit=0,
    network_ids=None,
    run_all_at_once=True,
):
    """
    Abre ELD.zxst, configura Herramienta diagnóstica y corre NetworkDiagnostic
    sobre todas las redes del estudio (equivalente a Ejecutar en la GUI).

    Por defecto Run(todas) UNA vez — igual que la herramienta con el estudio ELD
    abierto. Evita el efecto de ~59k mensajes repetidos por red.
    """
    import cympy
    import cympy.db as db
    import cympy.study as study

    settings = settings or load_json("config/settings.json")
    conn = connection_name or settings.get("database_connection_name") or "20260919"
    study_path = study_path or settings.get("eld_study_path") or DEFAULT_ELD_STUDY
    if not os.path.isfile(study_path):
        raise RuntimeError("No existe estudio ELD: %s" % study_path)

    out_dir = _out_dir(settings)
    print("[ELD-diag] BD:", conn)
    print("[ELD-diag] Estudio:", study_path)
    db.ConnectDatabaseByName(conn)
    study.Open(study_path)

    loaded = [str(n) for n in list(study.ListNetworks())]
    print("[ELD-diag] Redes en estudio:", len(loaded))
    if not loaded:
        all_nets = [str(n) for n in list(db.ListNetworks())]
        print("[ELD-diag] Estudio sin redes cargadas → LoadNetworks(%d)" % len(all_nets))
        opt = cympy.enums.LoadNetworkOption.NoDependencies
        study.LoadNetworks(all_nets, opt)
        loaded = [str(n) for n in list(study.ListNetworks())]

    nets = list(network_ids) if network_ids else list(loaded)
    nets = [str(n) for n in nets]
    if limit and limit > 0:
        nets = nets[: int(limit)]
        print("[ELD-diag] --limit=%d" % limit)

    nd = cympy.study.NetworkDiagnostic()
    applied = apply_diagnostic_tool_settings(nd)
    print("[ELD-diag] Parametros Topologia/Equipos:")
    for k, v in sorted(applied.items()):
        print("  ", k, "=", v)

    c = cympy
    all_rows = []
    per_feeder = {}
    errors_by_net = []
    t0 = time.time()

    if run_all_at_once:
        print("[ELD-diag] Ejecutar Herramienta diagnostica Run(%d redes)..." % len(nets))
        nd.Run(nets)
        raw = _message_rows(c, "ELD", "ALL")
        print("[ELD-diag] Mensajes crudos:", len(raw))
        for r in raw:
            blob = "%s %s" % (r.get("Mensaje") or "", r.get("Detalle") or "")
            net = _infer_network_from_text(blob, nets)
            if net:
                r["NetworkID"] = net
                r["Feeder"] = feeder_id_from_network(net)
            all_rows.append(r)
            fid = r.get("Feeder") or "ELD"
            bucket = per_feeder.setdefault(fid, {
                "NetworkID": r.get("NetworkID") or "",
                "n_messages": 0,
                "n_problems": 0,
                "n_errors": 0,
                "n_warnings": 0,
                "n_hints": 0,
            })
            bucket["n_messages"] += 1
            if r.get("Requiere_Correccion") == "SI":
                bucket["n_problems"] += 1
            sev = r.get("Severidad") or ""
            if sev == "Error":
                bucket["n_errors"] += 1
            elif sev == "Warning":
                bucket["n_warnings"] += 1
            elif sev == "Hint":
                bucket["n_hints"] += 1
    else:
        # Modo lento: una red a la vez (descargar resto) — atribucion exacta
        opt = cympy.enums.LoadNetworkOption.NoDependencies
        for i, net in enumerate(nets, 1):
            fid = feeder_id_from_network(net)
            try:
                cur = list(study.ListNetworks())
                if cur:
                    study.UnloadNetworks([str(x) for x in cur])
                study.LoadNetwork(str(net), opt)
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
                if i % 10 == 0 or n_prob:
                    print("  [%d/%d] %s problems=%d" % (i, len(nets), fid, n_prob))
            except Exception as ex:
                errors_by_net.append({"Feeder": fid, "NetworkID": net, "error": str(ex)})
                print("  FAIL", net, ex)
        # Restaurar todas las redes del estudio
        try:
            study.LoadNetworks(loaded, opt)
        except Exception as ex:
            print("[ELD-diag] AVISO restaurar redes:", ex)

    by_code = Counter((r.get("Codigo") or "(sin_codigo)") for r in all_rows)
    by_type = Counter((r.get("Tipo") or "(sin_tipo)") for r in all_rows if r.get("Tipo"))
    by_sev = Counter((r.get("Severidad") or "") for r in all_rows)
    problems = [r for r in all_rows if r.get("Requiere_Correccion") == "SI"]

    code_to_feeders = defaultdict(set)
    for r in problems:
        code_to_feeders[r.get("Codigo") or "(sin_codigo)"].add(r.get("Feeder") or "")

    by_code_detail = []
    for code, cnt in by_code.most_common():
        feeders = sorted(code_to_feeders.get(code) or [])
        sample = next(
            (r for r in problems if (r.get("Codigo") or "(sin_codigo)") == code), None
        )
        by_code_detail.append({
            "Codigo": code,
            "Count": cnt,
            "n_feeders": len(feeders),
            "Feeders": ",".join(feeders[:50]),
            "Tipo": (sample or {}).get("Tipo") or "",
            "Severidad": (sample or {}).get("Severidad") or "",
            "Mensaje_ejemplo": ((sample or {}).get("Mensaje") or "")[:160],
        })

    headers = [
        "Feeder", "NetworkID", "Codigo", "Severidad", "Categoria",
        "Tipo", "ID_CYMDIST", "Mensaje", "Detalle", "Requiere_Correccion",
    ]
    csv_path = os.path.join(out_dir, "cymdist_diagnostic_errors_ELD.csv")
    write_csv(csv_path, all_rows, headers)
    code_csv = os.path.join(out_dir, "diagnostic_by_code_ELD.csv")
    write_csv(
        code_csv,
        by_code_detail,
        ["Codigo", "Count", "n_feeders", "Feeders", "Tipo", "Severidad", "Mensaje_ejemplo"],
    )

    summary = {
        "scope": "ELD_study",
        "study_path": study_path,
        "connection": conn,
        "utility": settings.get("utility_name"),
        "timestamp": ts(),
        "tool": "NetworkDiagnostic / Herramienta diagnostica",
        "topology_settings": applied,
        "independent_of": ["cabecera", "ea_pot", "spot_load_s3", "loadflow_s4"],
        "n_networks_requested": len(nets),
        "n_networks_in_study": len(loaded),
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
        "ready_model_eld": len(problems) == 0 and len(errors_by_net) == 0,
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
            for r in problems[:80]
        ],
    }
    json_path = os.path.join(out_dir, "dashboard_summary_ELD.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    summary["json"] = json_path

    # Guardar estudio con parametros de diagnostico aplicados
    try:
        study.Save(study_path, False)
        print("[ELD-diag] Estudio guardado:", study_path)
    except Exception as ex:
        print("[ELD-diag] AVISO save:", ex)

    print(
        "[ELD-diag] DONE problems=%d E=%d W=%d H=%d csv=%s"
        % (
            summary["n_problems"],
            summary["n_errors"],
            summary["n_warnings"],
            summary["n_hints"],
            csv_path,
        )
    )
    return {"ok": True, "summary": summary, "rows": all_rows, "csv": csv_path, "json": json_path}


def main(argv=None):
    settings = load_json("config/settings.json")
    ap = argparse.ArgumentParser(description="Herramienta diagnostica API → estudio ELD")
    ap.add_argument("--study", default=DEFAULT_ELD_STUDY, help="Ruta ELD.zxst")
    ap.add_argument("--connection", default="", help="Nombre conexion CYME")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--per-network",
        action="store_true",
        help="Una red a la vez (lento). Default: Run(todas) como la GUI",
    )
    args = ap.parse_args(argv)
    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(settings)
    except Exception as ex:
        print("AVISO pause:", ex)
    try:
        result = run_eld_diagnostic(
            settings,
            study_path=args.study,
            connection_name=args.connection or None,
            limit=args.limit,
            run_all_at_once=not bool(args.per_network),
        )
        s = result["summary"]
        print(
            "ELD DIAG OK · redes=%d problems=%d"
            % (s.get("n_networks_ok"), s.get("n_problems"))
        )
        return 0
    except Exception as e:
        print("ELD DIAG FAIL:", e)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
