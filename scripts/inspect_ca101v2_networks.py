# -*- coding: utf-8 -*-
"""Inspecciona CA101V2.sxst: redes, demandas y posibles enlaces (ties)."""
from __future__ import print_function
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from core.common import require_cympy, load_json, run_cympy_main, mkdir, p
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path


def _short_feeder(net_id):
    s = str(net_id or "")
    if "_CA" in s or s.startswith("CA"):
        parts = s.split("_")
        for part in reversed(parts):
            if part.upper().startswith(("CA", "CN", "PE", "PN", "IN", "PA", "SL")):
                return part.upper()
    parts = str(net_id or "").split("_")
    return parts[-1].upper() if parts else str(net_id)


def _safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def main():
    s = load_settings(feeder_id="CA101")
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    if s.get("database_mdb") and os.path.isfile(s["database_mdb"]):
        a.connect_database()
    a.open_study(connect_db=False)

    nets = [str(n) for n in list(c.study.ListNetworks())]
    print("study:", s.get("study_path"))
    print("networks (%d):" % len(nets))
    for n in nets:
        print(" ", n)

    la = getattr(c, "LoadAllocation", None) or getattr(c, "loadallocation", None)
    rows = []
    for net in nets:
        short = _short_feeder(net)
        row = {
            "network_id": net,
            "feeder_short": short,
            "demand": None,
            "demand_error": None,
            "tie_candidates": [],
        }
        # Demand snapshot
        try:
            if la is not None:
                get_fd = getattr(la, "GetFeederDemand", None)
                if callable(get_fd):
                    d = get_fd(net)
                    if d is not None:
                        info = {}
                        for attr in (
                            "TotalKW", "TotalKVAR", "TotalKVA",
                            "KW", "KVAR", "KVA",
                            "ConnectedKW", "ConnectedKVAR",
                        ):
                            if hasattr(d, attr):
                                info[attr] = _safe_float(getattr(d, attr))
                        # Also try GetValue style
                        gv = getattr(d, "GetValue", None)
                        if callable(gv):
                            for key in ("TotalKW", "TotalKVAR", "KW", "KVAR"):
                                try:
                                    info[key] = _safe_float(gv(key))
                                except Exception:
                                    pass
                        row["demand"] = info
        except Exception as ex:
            row["demand_error"] = str(ex)

        # Open / normally-open devices near network (best-effort)
        try:
            devices = []
            for dtype in ("Switch", "Sectionalizer", "Breaker", "Fuse"):
                try:
                    lst = list(c.study.ListDevices(dtype, net))
                except Exception:
                    try:
                        lst = list(c.study.ListDevices(dtype))
                    except Exception:
                        lst = []
                for dev in lst[:200]:
                    did = str(getattr(dev, "ID", None) or getattr(dev, "DeviceNumber", None) or dev)
                    status = None
                    for fld in ("Status", "Closed", "NormallyOpen", "OpenTie", "ConnectionStatus"):
                        try:
                            if hasattr(dev, fld):
                                status = getattr(dev, fld)
                                break
                            gv = getattr(dev, "GetValue", None)
                            if callable(gv):
                                status = gv(fld)
                                break
                        except Exception:
                            continue
                    st_s = str(status).lower() if status is not None else ""
                    if any(x in st_s for x in ("open", "true", "1", "normally")) or status in (0, False):
                        devices.append({"device": did, "type": dtype, "status": str(status)})
                    if len(devices) >= 40:
                        break
                if len(devices) >= 40:
                    break
            row["tie_candidates"] = devices[:40]
        except Exception as ex:
            row["tie_scan_error"] = str(ex)

        rows.append(row)
        print(
            " ",
            short,
            "demand=",
            row.get("demand"),
            "ties=",
            len(row.get("tie_candidates") or []),
        )

    out = {
        "feeder_id": "CA101",
        "study_path": s.get("study_path"),
        "study_file": s.get("study_file") or s.get("ui_study_file"),
        "database_mdb": s.get("database_mdb"),
        "n_networks": len(nets),
        "networks": rows,
        "network_ids": nets,
        "feeder_shorts": [_short_feeder(n) for n in nets],
    }
    out_dir = output_path(s, "inventory")
    mkdir(out_dir)
    out_path = os.path.join(out_dir, "study_networks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("wrote", out_path)
    try:
        a.close_study(save=False)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    run_cympy_main(main)
