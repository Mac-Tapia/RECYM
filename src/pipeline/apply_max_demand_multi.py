# -*- coding: utf-8 -*-
"""Máxima demanda multi-alimentador para estudios con varias redes (p.ej. CA101V2).

Flujo:
  1) Resolver network_ids del estudio / config
  2) Extraer P_max/Q por alimentador (Excel medicioncabecera + medidoralimentador)
  3) SetDemand en cada red (CymPy; COM opcional)
  4) Persistir max_demanda_by_network.json + actualizar sesión del feeder primario
"""
from __future__ import print_function

import json
import os
import re
from datetime import datetime

from core.common import load_json, require_cympy
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path, feeder_family_code


def network_id_to_feeder_short(network_id):
    """NET_2030_131_CA101 → CA101; NET_2030_1192582_CN101 → CN101."""
    s = str(network_id or "").strip()
    if not s:
        return ""
    m = re.search(r"_([A-Z]{1,3}\d{2,4})(?:$|_)", s.upper())
    if m:
        return m.group(1)
    fam = feeder_family_code(s)
    if fam:
        return fam
    parts = s.split("_")
    return parts[-1].upper() if parts else s.upper()


def resolve_study_network_ids(settings, cympy=None):
    """Lista de network_id a operar: config.network_ids o ListNetworks() del estudio."""
    configured = settings.get("network_ids") or []
    if isinstance(configured, (str, bytes)):
        configured = [configured]
    configured = [str(x).strip() for x in configured if str(x).strip()]
    live = []
    if cympy is not None:
        try:
            live = [str(n) for n in list(cympy.study.ListNetworks())]
        except Exception:
            live = []
    if configured and live:
        # Preferir orden de config; solo redes presentes en el estudio
        live_set = set(live)
        ordered = [n for n in configured if n in live_set]
        for n in live:
            if n not in ordered:
                ordered.append(n)
        return ordered
    if configured:
        return configured
    if live:
        return live
    primary = str(settings.get("network_id") or "").strip()
    return [primary] if primary else []


def extract_max_demanda_for_networks(
    settings, network_ids=None, medicion_file=None, medicion_files=None
):
    """Extrae máxima demanda por red. No aborta el lote si un medidor falta.

    medicion_files ({network_id: archivo}) tiene prioridad sobre medicion_file,
    que se aplica a todas las redes; así el receptor de una transferencia no
    hereda el Excel del alimentador origen.
    """
    from core.cabecera_medicion_excel import extract_cabecera_medicion

    s = settings or load_settings()
    nets = network_ids or resolve_study_network_ids(s)
    rows = []
    warnings = []
    for net in nets:
        short = network_id_to_feeder_short(net)
        row = {
            "network_id": net,
            "feeder_short": short,
            "ok": False,
            "P_kW": None,
            "Q_kvar": None,
            "S_kVA": None,
            "P_avg_kW": None,
            "factor_carga_pct": None,
            "fecha_medicion": None,
            "medidor": None,
            "Vll_kV": None,
            "medicion_file": None,
            "error": None,
        }
        try:
            stats = extract_cabecera_medicion(
                short,
                medicion_file=(medicion_files or {}).get(net, medicion_file),
                settings=s,
                auto_find_file=True,
            )
            row.update({
                "ok": True,
                "P_kW": stats.get("P_kW"),
                "Q_kvar": stats.get("Q_kvar"),
                "S_kVA": stats.get("S_kVA"),
                "P_avg_kW": stats.get("P_avg_kW"),
                "factor_carga_pct": stats.get("factor_carga_pct"),
                "fecha_medicion": stats.get("fecha_medicion"),
                "medidor": stats.get("medidor"),
                "Vll_kV": stats.get("Vll_kV"),
                "medicion_file": stats.get("medicion_file"),
                "msg": stats.get("msg"),
            })
            for w in (stats.get("warnings") or []):
                warnings.append("%s: %s" % (short, w))
        except Exception as ex:
            row["error"] = str(ex)
            warnings.append("%s: %s" % (short, ex))
            print("AVISO max demanda %s (%s): %s" % (short, net, ex))
        rows.append(row)
    return {
        "ok": any(r.get("ok") for r in rows),
        "feeder_id": s.get("feeder_id"),
        "study_path": s.get("study_path"),
        "n_networks": len(rows),
        "n_ok": sum(1 for r in rows if r.get("ok")),
        "n_fail": sum(1 for r in rows if not r.get("ok")),
        "networks": rows,
        "warnings": warnings,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
    }


def apply_max_demand_multi(
    settings=None,
    network_ids=None,
    medicion_file=None,
    write_cymdist=True,
    save=True,
    use_com=False,
    extracted=None,
    run_allocation=True,
    medicion_files=None,
):
    """Extrae (si hace falta) y escribe máxima demanda en cada red del estudio.

    Si run_allocation=True, tras SetDemand ejecuta LoadAllocation COM por red
    OK para dejar el modelo en condición de pico (máxima demanda).
    """
    from pipeline.run_demand_allocation import (
        set_network_demand,
        set_source_phase_voltages,
        save_session,
        load_session,
    )

    s = dict(settings or load_settings())
    api = load_json("config/cympy_api_map.json")
    pack = extracted or extract_max_demanda_for_networks(
        s,
        network_ids=network_ids,
        medicion_file=medicion_file,
        medicion_files=medicion_files,
    )
    if network_ids:
        wanted = set(str(x) for x in network_ids)
        pack["networks"] = [
            r for r in pack.get("networks") or [] if r.get("network_id") in wanted
        ]

    writes = []
    allocations = []
    cympy_info = None
    if write_cymdist and pack.get("n_ok"):
        s["skip_db_project_save"] = False
        s["isolated_work_study"] = False
        s["persist_cabecera_to_db"] = True
        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        a.open_study(force_backup=False)
        # Re-resolver redes con estudio abierto
        nets_live = resolve_study_network_ids(s, cympy=c)
        by_net = {r["network_id"]: r for r in (pack.get("networks") or [])}
        for net in nets_live:
            row = by_net.get(net)
            if not row or not row.get("ok"):
                continue
            p_kw = float(row["P_kW"])
            q_kvar = float(row.get("Q_kvar") or 0.0)
            w = {"network_id": net, "feeder_short": row.get("feeder_short"), "ok": False}
            try:
                if use_com:
                    from core.cymdist_com import set_network_demand_com
                    s_net = dict(s)
                    s_net["network_id"] = net
                    info_com = set_network_demand_com(
                        s_net, p_kw, q_kvar, leave_open=True, kill_existing=False
                    )
                    w["com"] = info_com
                    w["ok"] = bool(info_com.get("ok"))
                info = set_network_demand(c, net, p_kw, q_kvar, settings=s)
                w["cympy"] = info
                w["ok"] = True
                vll = row.get("Vll_kV")
                if vll not in (None, ""):
                    try:
                        import math
                        vln = float(vll) / math.sqrt(3.0)
                        w["source_voltage"] = set_source_phase_voltages(
                            c, net, vln, vln, vln, vll_kv=float(vll)
                        )
                    except Exception as ex_v:
                        w["source_voltage_error"] = str(ex_v)
            except Exception as ex:
                w["error"] = str(ex)
                print("AVISO SetDemand multi %s: %s" % (net, ex))
            writes.append(w)

        if save and writes:
            try:
                persist = a.persist_study_and_database(force_db=True)
                cympy_info = {"persist": persist, "saved": bool(persist.get("study_saved"))}
            except Exception as ex_save:
                cympy_info = {"saved": False, "save_error": str(ex_save)}
            try:
                a.close_study(save=False)
            except Exception:
                pass
        else:
            cympy_info = {"saved": False}

        # LoadAllocation en pico por red (COM, tras cerrar CymPy)
        if run_allocation:
            from core.cymdist_com import run_loadallocation_com
            for w in writes:
                if not w.get("ok"):
                    continue
                net = w["network_id"]
                row = by_net.get(net) or {}
                s_net = dict(s)
                s_net["network_id"] = net
                try:
                    alloc = run_loadallocation_com(
                        s_net,
                        network_id=net,
                        p_kw=row.get("P_kW"),
                        q_kvar=row.get("Q_kvar"),
                        method="KWH",
                        kill_existing=False,
                        leave_open=True,
                    )
                    allocations.append({
                        "network_id": net,
                        "feeder_short": w.get("feeder_short"),
                        "ok": bool(alloc.get("ok")),
                        "error": alloc.get("error"),
                        "P_kW": row.get("P_kW"),
                        "Q_kvar": row.get("Q_kvar"),
                    })
                    print(
                        "LoadAllocation pico %s: ok=%s"
                        % (w.get("feeder_short"), alloc.get("ok"))
                    )
                except Exception as ex_al:
                    allocations.append({
                        "network_id": net,
                        "feeder_short": w.get("feeder_short"),
                        "ok": False,
                        "error": str(ex_al),
                    })
                    print("AVISO LoadAllocation pico %s: %s" % (net, ex_al))

    # Sesión del alimentador primario = fila OK de network_id principal
    primary_net = str(s.get("network_id") or "").strip()
    primary_row = None
    for r in pack.get("networks") or []:
        if r.get("network_id") == primary_net and r.get("ok"):
            primary_row = r
            break
    if primary_row is None:
        for r in pack.get("networks") or []:
            if r.get("ok"):
                primary_row = r
                break
    session_updated = False
    if primary_row:
        try:
            sess = load_session(s)
            sess["mode"] = "KW_KVAR"
            sess["P_kW"] = primary_row.get("P_kW")
            sess["Q_kvar"] = primary_row.get("Q_kvar")
            sess["Vll_kV"] = primary_row.get("Vll_kV") or s.get("voltage_ll_kv")
            sess["fecha_medicion"] = primary_row.get("fecha_medicion") or ""
            sess["medidor"] = primary_row.get("medidor")
            sess["status"] = "max_demand_multi"
            sess["max_demand_multi"] = True
            save_session(s, sess)
            session_updated = True
        except Exception as ex_sess:
            pack.setdefault("warnings", []).append("sesion: %s" % ex_sess)

    out = {
        "ok": bool(pack.get("n_ok")) and (
            (not write_cymdist) or any(w.get("ok") for w in writes)
        ),
        "feeder_id": s.get("feeder_id"),
        "study_path": s.get("study_path"),
        "primary_network_id": primary_net,
        "extraction": pack,
        "writes": writes,
        "allocations": allocations,
        "n_written": sum(1 for w in writes if w.get("ok")),
        "n_allocated": sum(1 for a in allocations if a.get("ok")),
        "cympy": cympy_info,
        "session_updated": session_updated,
        "mode": "max_demand_all",
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }

    out_path = output_path(s, "demand", "max_demanda_by_network.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    out["artifact"] = out_path
    print(
        "max_demand_multi: ok=%s extracted=%s/%s written=%s allocated=%s -> %s"
        % (
            out["ok"],
            pack.get("n_ok"),
            pack.get("n_networks"),
            out["n_written"],
            out["n_allocated"],
            out_path,
        )
    )
    return out


def main(argv=None):
    import argparse
    from core.common import run_cympy_main

    parser = argparse.ArgumentParser(description="Máxima demanda multi-alimentador")
    parser.add_argument("--feeder", default="CA101")
    parser.add_argument("--medicion-file", default=None)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--use-com", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--no-allocation", action="store_true")
    args = parser.parse_args(argv)

    def _run():
        s = load_settings(feeder_id=args.feeder)
        if args.extract_only:
            pack = extract_max_demanda_for_networks(s, medicion_file=args.medicion_file)
            path = output_path(s, "demand", "max_demanda_by_network.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ok": pack.get("ok"), "extraction": pack}, f, indent=2, ensure_ascii=False)
            print("extract-only ->", path, "ok=%s n_ok=%s" % (pack.get("ok"), pack.get("n_ok")))
            return pack
        return apply_max_demand_multi(
            s,
            medicion_file=args.medicion_file,
            write_cymdist=True,
            save=not args.no_save,
            use_com=bool(args.use_com),
            run_allocation=not args.no_allocation,
        )

    run_cympy_main(_run)


if __name__ == "__main__":
    main()
