# -*- coding: utf-8 -*-
"""Gancho de transferencia de carga por calidad de tensión (estudio multi-red).

Requiere baseline de máxima demanda (apply_max_demand_multi). Evalúa el par
configurado en transfer_pair (p.ej. CA101 ↔ CN101 en CA101V2):

  1) LoadFlow en ambas redes (pico)
  2) Detectar violaciones Vmin/Vmax en origen
  3) Registrar escenario de transferencia (candidato a conmutar ties)
  4) Persistir transfer_voltage_quality.json

La conmutación física de seccionadores es best-effort (open_tie / Close);
si no hay enlace operable se deja el diagnóstico y la recomendación.
"""
from __future__ import print_function

import json
import os
import re
from datetime import datetime

from core.feeder_context import load_settings, output_path
from pipeline.apply_max_demand_multi import network_id_to_feeder_short


def _norm_pair(settings):
    pair = settings.get("transfer_pair") or []
    if isinstance(pair, (str, bytes)):
        pair = [x.strip() for x in str(pair).split(",") if x.strip()]
    pair = [str(x).strip().upper() for x in pair if str(x).strip()]
    if len(pair) < 2:
        # Fallback: primario + primer network distinto
        primary = network_id_to_feeder_short(settings.get("network_id"))
        others = [
            network_id_to_feeder_short(n)
            for n in (settings.get("network_ids") or [])
        ]
        others = [o for o in others if o and o != primary]
        if primary and others:
            pair = [primary, others[0]]
    return pair[:2]


def _match_network(network_ids, feeder_short):
    want = str(feeder_short or "").strip().upper()
    for net in network_ids or []:
        if network_id_to_feeder_short(net) == want:
            return net
    for net in network_ids or []:
        if want and want in str(net).upper():
            return net
    return None


def _vmin_vmax_from_lf(result):
    """Extrae Vmin/Vmax pu de un dict de loadflow (best-effort)."""
    if not isinstance(result, dict):
        return {"Vmin_pu": None, "Vmax_pu": None}
    keys_min = ("Vmin_pu", "vmin_pu", "Vmin", "VoltageMin", "MinVoltagePU")
    keys_max = ("Vmax_pu", "vmax_pu", "Vmax", "VoltageMax", "MaxVoltagePU")
    vmin = vmax = None
    for k in keys_min:
        if result.get(k) is not None:
            try:
                vmin = float(result[k])
                break
            except Exception:
                pass
    for k in keys_max:
        if result.get(k) is not None:
            try:
                vmax = float(result[k])
                break
            except Exception:
                pass
    # Nested summary
    for nest in ("summary", "header", "cabecera", "metrics"):
        sub = result.get(nest)
        if isinstance(sub, dict):
            got = _vmin_vmax_from_lf(sub)
            if vmin is None:
                vmin = got.get("Vmin_pu")
            if vmax is None:
                vmax = got.get("Vmax_pu")
    return {"Vmin_pu": vmin, "Vmax_pu": vmax}


def _run_lf_one(adapter, network_id, settings):
    """Ejecuta LF COM por red (mismo motor anti-130013 que §5)."""
    from core.cymdist_com import run_loadflow_com

    s_net = dict(settings or {})
    s_net["network_id"] = network_id
    s_net["cymdist_leave_open"] = True
    s_net["skip_db_project_save"] = True
    try:
        com = run_loadflow_com(
            s_net,
            network_id=network_id,
            leave_open=True,
            kill_existing=False,
            scenario=None,
        )
    except Exception as ex:
        return {"ok": False, "error": str(ex), "network_id": network_id, "engine": "COM"}

    metrics = _vmin_vmax_from_lf(com)
    topo = (com.get("topo") or {}) if isinstance(com, dict) else {}
    # También mirar topo / summary anidados típicos del COM
    for nest in (com, topo, com.get("summary") or {}, com.get("metrics") or {}):
        if not isinstance(nest, dict):
            continue
        got = _vmin_vmax_from_lf(nest)
        if metrics.get("Vmin_pu") is None and got.get("Vmin_pu") is not None:
            metrics["Vmin_pu"] = got["Vmin_pu"]
        if metrics.get("Vmax_pu") is None and got.get("Vmax_pu") is not None:
            metrics["Vmax_pu"] = got["Vmax_pu"]
        for k, dest in (
            ("VMINPU", "Vmin_pu"),
            ("VMAXPU", "Vmax_pu"),
            ("MinVoltage", "Vmin_pu"),
            ("MaxVoltage", "Vmax_pu"),
            ("VOLTMIN", "Vmin_pu"),
            ("VOLTMAX", "Vmax_pu"),
        ):
            if metrics.get(dest) is None and nest.get(k) is not None:
                try:
                    metrics[dest] = float(nest[k])
                except Exception:
                    pass

    p_kw = com.get("P_kW")
    q_kvar = com.get("Q_kvar")
    if p_kw is None and topo.get("KWTOT") is not None:
        try:
            p_kw = float(topo["KWTOT"])
        except Exception:
            pass
    if q_kvar is None and topo.get("KVARTOT") is not None:
        try:
            q_kvar = float(topo["KVARTOT"])
        except Exception:
            pass

    return {
        "ok": bool(com.get("ok")),
        "error": None if com.get("ok") else (com.get("error") or com.get("msg")),
        "network_id": network_id,
        "Vmin_pu": metrics.get("Vmin_pu"),
        "Vmax_pu": metrics.get("Vmax_pu"),
        "engine": "COM",
        "P_kW": p_kw,
        "Q_kvar": q_kvar,
        "com": {
            "ok": com.get("ok"),
            "method": com.get("calculation_method") or com.get("method_used") or com.get("method"),
            "msg": com.get("msg"),
            "elapsed_sec": com.get("elapsed_sec"),
        },
    }


def evaluate_transfer_voltage_quality(
    settings=None,
    vmin_limit_pu=0.95,
    vmax_limit_pu=1.05,
    apply_switch=False,
    ensure_max_demand=False,
):
    """Evalúa transferencia por calidad de tensión sobre el par configurado."""
    s = dict(settings or load_settings())
    if ensure_max_demand:
        from pipeline.apply_max_demand_multi import apply_max_demand_multi
        apply_max_demand_multi(s, write_cymdist=True, save=True)

    pair = _norm_pair(s)
    # Preferir network_ids de config; si hay snapshot de inspección, usarlo
    nets = list(s.get("network_ids") or [])
    snap = output_path(s, "inventory", "study_networks.json")
    if (not nets) and os.path.isfile(snap):
        try:
            with open(snap, "r", encoding="utf-8") as f:
                data = json.load(f)
            nets = list(data.get("network_ids") or [])
        except Exception:
            nets = []
    if not nets and s.get("network_id"):
        nets = [str(s.get("network_id"))]

    src_short, dst_short = (pair + [None, None])[:2]
    src_net = _match_network(nets, src_short)
    dst_net = _match_network(nets, dst_short)

    baseline = {}
    # No mantener CymPy abierto: cada LF es COM independiente (leave_open)
    for label, net in (("source", src_net), ("destination", dst_net)):
        if not net:
            baseline[label] = {
                "ok": False,
                "error": "red no encontrada en estudio / network_ids",
                "feeder_short": src_short if label == "source" else dst_short,
            }
            continue
        lf = _run_lf_one(None, net, s)
        lf["feeder_short"] = src_short if label == "source" else dst_short
        vmin = lf.get("Vmin_pu")
        vmax = lf.get("Vmax_pu")
        violations = []
        if vmin is not None and vmin < float(vmin_limit_pu):
            violations.append({
                "type": "undervoltage",
                "Vmin_pu": vmin,
                "limit_pu": float(vmin_limit_pu),
            })
        if vmax is not None and vmax > float(vmax_limit_pu):
            violations.append({
                "type": "overvoltage",
                "Vmax_pu": vmax,
                "limit_pu": float(vmax_limit_pu),
            })
        lf["violations"] = violations
        lf["has_voltage_quality_issue"] = bool(violations)
        baseline[label] = lf

    src_has_issue = bool((baseline.get("source") or {}).get("has_voltage_quality_issue"))
    recommendation = {
        "action": "none",
        "reason": "Sin violaciones de tensión en origen (o LF incompleto / sin Vmin)",
    }
    switch_result = None
    after = None

    if src_has_issue and src_net and dst_net:
        recommendation = {
            "action": "transfer_load_to_destination",
            "reason": (
                "Origen %s con violación de tensión en máxima demanda; "
                "evaluar transferencia hacia %s"
                % (src_short, dst_short)
            ),
            "source": src_short,
            "destination": dst_short,
            "source_network_id": src_net,
            "destination_network_id": dst_net,
        }
        if apply_switch:
            switch_result = {
                "ok": False,
                "skipped": True,
                "msg": (
                    "Conmutación automática diferida: defina nodo de enlace "
                    "o Network Configuration Optimization en CYME. "
                    "Baseline y recomendación ya están listos."
                ),
            }
    elif (baseline.get("source") or {}).get("ok") and src_net and dst_net:
        recommendation = {
            "action": "monitor",
            "reason": (
                "LF pico OK en origen %s; mantener vigilancia y par %s↔%s listo "
                "para transferencia si aparece violación"
                % (src_short, src_short, dst_short)
            ),
            "source": src_short,
            "destination": dst_short,
        }

    out = {
        "ok": True,
        "feeder_id": s.get("feeder_id"),
        "study_path": s.get("study_path"),
        "transfer_pair": pair,
        "source_network_id": src_net,
        "destination_network_id": dst_net,
        "limits_pu": {"Vmin": float(vmin_limit_pu), "Vmax": float(vmax_limit_pu)},
        "baseline_peak": baseline,
        "recommendation": recommendation,
        "switch": switch_result,
        "after_transfer": after,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "peak_demand_transfer_voltage_quality",
    }

    path = output_path(s, "demand", "transfer_voltage_quality.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    out["artifact"] = path
    print(
        "transfer_voltage_quality: pair=%s -> %s issue=%s"
        % (pair, path, src_has_issue)
    )
    return out


def main(argv=None):
    import argparse
    from core.common import run_cympy_main

    parser = argparse.ArgumentParser()
    parser.add_argument("--feeder", default="CA101")
    parser.add_argument("--ensure-max-demand", action="store_true")
    parser.add_argument("--apply-switch", action="store_true")
    parser.add_argument("--vmin", type=float, default=0.95)
    parser.add_argument("--vmax", type=float, default=1.05)
    args = parser.parse_args(argv)

    def _run():
        s = load_settings(feeder_id=args.feeder)
        return evaluate_transfer_voltage_quality(
            s,
            vmin_limit_pu=args.vmin,
            vmax_limit_pu=args.vmax,
            apply_switch=bool(args.apply_switch),
            ensure_max_demand=bool(args.ensure_max_demand),
        )

    run_cympy_main(_run)


if __name__ == "__main__":
    main()
