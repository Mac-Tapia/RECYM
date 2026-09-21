# -*- coding: utf-8 -*-
from __future__ import print_function
"""Inventario de cargas SpotLoad / DistributedLoad.

- Por alimentador: data/output/feeders/<ID>/inventory/loads.json
- Sistema (~96): una pasada sobre ELD.zxst / BD → todos los JSON + índice global
"""
import json
import os
import time

from core.common import require_cympy, load_json, run_cympy_main, ts
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path


def _safe_get(dev, field):
    try:
        return dev.GetValue(field)
    except Exception:
        return ""


def collect_loads(cympy, network_id):
    rows = []
    for dtype, label in (
        (cympy.enums.DeviceType.SpotLoad, "SpotLoad"),
        (cympy.enums.DeviceType.DistributedLoad, "DistributedLoad"),
    ):
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id))
        except Exception:
            devices = []
        for d in devices:
            load_id = getattr(d, "DeviceNumber", None) or _safe_get(d, "DeviceNumber")
            kw = ""
            kvar = ""
            base = "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue"
            for p_path, q_path in (
                (base + ".KW", base + ".KVAR"),
                (base + ".KW", base + ".PF"),
                (base + ".KVA", base + ".PF"),
            ):
                try:
                    kw = d.GetValue(p_path)
                    kvar = d.GetValue(q_path)
                    break
                except Exception:
                    pass
            try:
                vtype = d.GetValue(base + ".GetType()")
            except Exception:
                vtype = ""
            rows.append({
                "LoadID": str(load_id),
                "Tipo": label,
                "SectionID": str(getattr(d, "SectionID", "") or ""),
                "kW": str(kw),
                "kvar": str(kvar),
                "LoadValueType": str(vtype),
                "ZoneID": str(_safe_get(d, "ZoneID") or ""),
                "Label": "%s (%s)" % (load_id, label),
                "NetworkID": str(network_id or ""),
            })
    return rows


def feeder_id_from_network(network_id):
    parts = str(network_id or "").split("_")
    return parts[-1] if parts else str(network_id or "")


def _system_index_path(settings=None):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "data", "output", "system", "loads_inventory.json")


def save_feeder_loads(feeder_id, network_id, loads, settings=None):
    """Escribe inventory/loads.json del alimentador (sintetiza config si falta)."""
    fs = load_settings(
        feeder_id=str(feeder_id).strip().upper(),
        network_id=str(network_id or "").strip() or None,
        synthesize=True,
        persist_synth=True,
    )
    if network_id:
        fs["network_id"] = str(network_id)
    out = output_path(fs, "inventory", "loads.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    payload = {
        "feeder_id": fs.get("feeder_id"),
        "network_id": fs.get("network_id") or network_id,
        "n_loads": len(loads or []),
        "timestamp": ts(),
        "loads": loads or [],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out


def inventory_system_loads(settings=None, study_path=None, limit=0, network_ids=None):
    """Inventaria SpotLoad de TODAS las redes (~96) en una sola apertura de estudio.

    Preferencia de estudio: ELD.zxst (todas las redes). Si el estudio no tiene redes,
    carga ListNetworks() de la BD.
    """
    s = settings or load_settings()
    from core.cymdist_com import pause_cymdist_for_cympy
    from pipeline.model_quality_gate import feeder_id_from_network as fid_from_net

    pause_cymdist_for_cympy(s)
    eld = (
        (study_path or "").strip()
        or (s.get("eld_study_path") or "").strip()
        or ""
    )
    if not eld or not os.path.isfile(eld):
        # fallback: estudio activo
        eld = (s.get("study_path") or "").strip()
    if not eld or not os.path.isfile(eld):
        raise RuntimeError(
            "Sin estudio para inventario sistema (eld_study_path / study_path)."
        )

    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    # Abrir ELD (no el zxst mono-feeder de §1)
    a.open_study(study_path=eld, force_backup=False)

    t0 = time.time()
    try:
        import cympy.db as db

        loaded = [str(n) for n in list(c.study.ListNetworks())]
        if not loaded:
            cname = s.get("database_connection_name") or "20260919"
            try:
                db.ConnectDatabaseByName(cname)
            except Exception:
                pass
            all_nets = [str(n) for n in list(db.ListNetworks())]
            print("[inventory] Estudio vacío → LoadNetworks(%d)" % len(all_nets))
            try:
                opt = c.enums.LoadNetworkOption.NoDependencies
                c.study.LoadNetworks(all_nets, opt)
            except Exception:
                c.study.LoadNetworks(all_nets)
            loaded = [str(n) for n in list(c.study.ListNetworks())]

        nets = list(network_ids) if network_ids else list(loaded)
        nets = [str(n) for n in nets]
        if limit and int(limit) > 0:
            nets = nets[: int(limit)]

        print("[inventory] Estudio:", eld)
        print("[inventory] Redes a inventariar:", len(nets))

        per_feeder = []
        total_loads = 0
        errors = []
        for i, net in enumerate(nets, 1):
            fid = fid_from_net(net)
            try:
                loads = collect_loads(c, net)
                # Anotar feeder en cada fila
                for L in loads:
                    L["Feeder"] = fid
                    L["NetworkID"] = net
                path = save_feeder_loads(fid, net, loads, settings=s)
                total_loads += len(loads)
                per_feeder.append({
                    "feeder_id": fid,
                    "network_id": net,
                    "n_loads": len(loads),
                    "path": path,
                })
                if i % 10 == 0 or i == len(nets):
                    print("[inventory] %d/%d %s → %d cargas" % (i, len(nets), fid, len(loads)))
            except Exception as ex:
                errors.append({"feeder_id": fid, "network_id": net, "error": str(ex)})
                print("[inventory] ERROR", fid, ex)

        index = {
            "ok": True,
            "timestamp": ts(),
            "study_path": eld,
            "n_networks": len(nets),
            "n_feeders_ok": len(per_feeder),
            "n_loads_total": total_loads,
            "elapsed_sec": round(time.time() - t0, 1),
            "feeders": per_feeder,
            "errors": errors,
        }
        idx_path = _system_index_path(s)
        os.makedirs(os.path.dirname(idx_path), exist_ok=True)
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        index["index_path"] = idx_path
        print("[inventory] TOTAL cargas:", total_loads, "→", idx_path)
        return index
    finally:
        try:
            a.close_study(save=False)
        except Exception:
            pass


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Inventario SpotLoad (1 feeder o sistema 96)")
    ap.add_argument("feeder", nargs="?", default="", help="ID feeder (vacío = sistema/ELD)")
    ap.add_argument("--system", action="store_true", help="Inventariar todas las redes del ELD/BD")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    if args.system or not args.feeder:
        s = load_settings()
        res = inventory_system_loads(s, limit=args.limit)
        print("OK sistema:", res.get("n_feeders_ok"), "feeders,", res.get("n_loads_total"), "loads")
        return 0

    s = load_settings(feeder_id=args.feeder.strip().upper())
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    rows = collect_loads(c, s.get("network_id"))
    out = save_feeder_loads(s.get("feeder_id"), s.get("network_id"), rows, settings=s)
    print("Cargas:", len(rows))
    print(out)
    return 0


if __name__ == "__main__":
    run_cympy_main(lambda: main())
