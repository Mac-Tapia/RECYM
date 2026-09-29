# -*- coding: utf-8 -*-
"""Inventario de interruptores de enlace del contexto CYMDIST activo (solo lectura)."""
from __future__ import print_function

import argparse
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.common import load_json, require_cympy, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path


FIELDS = (
    "IsTie", "TieSwitch", "OpenTie", "NormallyOpen", "NormalStatus",
    "Status", "ConnectionStatus", "ClosedPhase", "IsClosed", "Closed",
    "SectionID", "FromNodeID", "ToNodeID", "DeviceType",
)

NODE_FIELDS = (
    "X", "Y", "Longitude", "Latitude", "CoordX", "CoordY",
    "UTMX", "UTMY", "NetworkID",
)

SOURCE_FIELDS = (
    "NominalVoltage", "BaseVoltage", "OperatingVoltage", "Voltage",
    "KVLL", "NetworkID", "ConnectionStatus",
)


def _read(device, field):
    try:
        value = device.GetValue(field)
        return None if value is None else str(value)
    except Exception:
        return None


def _section_rows(cympy, network_id):
    rows = []
    for section in list(cympy.study.ListSections(network_id) or []):
        section_id = str(getattr(section, "ID", None) or section)
        rows.append({
            "section_id": section_id,
            "from_node": _read(section, "FromNodeID") or str(getattr(section, "FromNodeID", "") or ""),
            "to_node": _read(section, "ToNodeID") or str(getattr(section, "ToNodeID", "") or ""),
        })
    return rows


def _devices_on_section(cympy, network_id, section_id):
    rows = []
    for type_name in ("Sectionalizer", "Switch", "Breaker", "Recloser", "Fuse"):
        dtype = getattr(cympy.enums.DeviceType, type_name, None)
        if dtype is None:
            continue
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id, section_id))
        except Exception:
            devices = []
        for device in devices:
            rows.append({
                "device_id": str(
                    getattr(device, "DeviceNumber", None)
                    or getattr(device, "ID", None)
                    or device
                ),
                "type": type_name,
                "section_id": section_id,
                "values": {field: _read(device, field) for field in FIELDS},
            })
    return rows


def _all_devices(cympy, network_id):
    rows = []
    for type_name in ("Sectionalizer", "Switch", "Breaker", "Recloser", "Fuse"):
        dtype = getattr(cympy.enums.DeviceType, type_name, None)
        if dtype is None:
            continue
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id))
        except Exception:
            devices = []
        for device in devices:
            device_id = str(
                getattr(device, "DeviceNumber", None)
                or getattr(device, "ID", None)
                or device
            )
            values = {field: _read(device, field) for field in FIELDS}
            rows.append({
                "device_id": device_id,
                "type": type_name,
                "values": values,
            })
    return rows


def _node_coordinates(cympy):
    result = {}
    try:
        nodes = list(cympy.study.ListNodes() or [])
    except Exception:
        nodes = []
    for node in nodes:
        node_id = str(
            getattr(node, "ID", None)
            or getattr(node, "NodeID", None)
            or getattr(node, "NodeNumber", None)
            or ""
        ).strip("'\"")
        if not node_id:
            continue
        values = {field: _read(node, field) for field in NODE_FIELDS}
        try:
            x = float(values.get("X") or getattr(node, "X"))
            y = float(values.get("Y") or getattr(node, "Y"))
        except Exception:
            continue
        result[node_id] = {"x": x, "y": y, "values": values}
    return result


def _section_device_rows(cympy, network_id, sections):
    """Use Section.ListDevices so the section association is authoritative."""
    rows = []
    for section in list(cympy.study.ListSections(network_id) or []):
        section_id = str(getattr(section, "ID", None) or section)
        endpoints = next(
            (row for row in sections if row["section_id"] == section_id),
            {"from_node": "", "to_node": ""},
        )
        try:
            devices = list(section.ListDevices() or [])
        except Exception:
            devices = []
        for device in devices:
            rows.append({
                "device_id": str(
                    getattr(device, "DeviceNumber", None)
                    or getattr(device, "ID", None)
                    or device
                ),
                "section_id": section_id,
                "from_node": endpoints.get("from_node"),
                "to_node": endpoints.get("to_node"),
                "values": {field: _read(device, field) for field in FIELDS},
            })
    return rows


def _source_rows(cympy, network_id):
    try:
        devices = list(cympy.study.ListDevices(cympy.enums.DeviceType.Source, network_id))
    except Exception:
        devices = []
    return [{
        "device_id": str(
            getattr(device, "DeviceNumber", None)
            or getattr(device, "ID", None)
            or device
        ),
        "values": {field: _read(device, field) for field in SOURCE_FIELDS},
    } for device in devices]


def inspect(settings, peer_network=None):
    api = load_json("config/cympy_api_map.json")
    cympy = require_cympy(settings)
    adapter = CymPyAdapter(cympy, api, settings)
    adapter.open_study(force_backup=False)
    network_id = str(settings.get("network_id") or "")
    peer_network = str(peer_network or "").strip()
    devices_by_network = {network_id: _all_devices(cympy, network_id)}
    if peer_network:
        devices_by_network[peer_network] = _all_devices(cympy, peer_network)
    rows = devices_by_network[network_id]
    for row in rows:
        device_id = row["device_id"]
        values = row["values"]
        explicit_tie = any(
            str(values.get(field) or "").strip().lower()
            in ("true", "1", "yes", "tie", "open tie")
            for field in ("IsTie", "TieSwitch", "OpenTie")
        )
        normally_open = (
            str(values.get("NormallyOpen") or "").strip().lower()
            in ("true", "1", "yes")
            or str(values.get("NormalStatus") or "").strip().lower() == "open"
        )
        name_hint = any(
            token in device_id.upper()
            for token in ("TIE", "ENLACE", "INTERCONEX", "N.O", "NO_")
        )
        row.update({
            "explicit_tie": explicit_tie,
            "normally_open": normally_open,
            "name_hint": name_hint,
        })
    sections = {network_id: _section_rows(cympy, network_id)}
    if peer_network:
        sections[peer_network] = _section_rows(cympy, peer_network)
    section_devices = {
        net: _section_device_rows(cympy, net, section_rows)
        for net, section_rows in sections.items()
    }
    sources_by_network = {
        net: _source_rows(cympy, net) for net in sections
    }
    transfer_points = []
    if peer_network:
        primary_nodes = {}
        peer_nodes = {}
        for row in sections[network_id]:
            for node in (row["from_node"], row["to_node"]):
                if node:
                    primary_nodes.setdefault(node, []).append(row["section_id"])
        for row in sections[peer_network]:
            for node in (row["from_node"], row["to_node"]):
                if node:
                    peer_nodes.setdefault(node, []).append(row["section_id"])
        for node_id in sorted(set(primary_nodes).intersection(peer_nodes)):
            sides = {}
            for net, section_ids in (
                (network_id, primary_nodes[node_id]),
                (peer_network, peer_nodes[node_id]),
            ):
                devices = []
                for section_id in section_ids:
                    devices.extend(_devices_on_section(cympy, net, section_id))
                sides[net] = {"sections": section_ids, "devices": devices}
            transfer_points.append({
                "node_id": node_id,
                "networks": [network_id, peer_network],
                "sides": sides,
            })

    coordinates = _node_coordinates(cympy)
    device_type_names = sorted(
        name for name in dir(cympy.enums.DeviceType)
        if not name.startswith("_")
    )
    nearest_endpoint_pairs = []
    if peer_network and coordinates:
        left = sorted({
            node for row in sections[network_id]
            for node in (row["from_node"], row["to_node"])
            if node in coordinates
        })
        right = sorted({
            node for row in sections[peer_network]
            for node in (row["from_node"], row["to_node"])
            if node in coordinates
        })
        distances = []
        for left_id in left:
            a = coordinates[left_id]
            for right_id in right:
                b = coordinates[right_id]
                distance = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5
                distances.append((distance, left_id, right_id))
        for distance, left_id, right_id in sorted(distances)[:20]:
            nearest_endpoint_pairs.append({
                "distance": distance,
                "primary_node": left_id,
                "peer_node": right_id,
                "primary_coordinate": coordinates[left_id],
                "peer_coordinate": coordinates[right_id],
                "primary_sections": [
                    row["section_id"] for row in sections[network_id]
                    if left_id in (row["from_node"], row["to_node"])
                ],
                "peer_sections": [
                    row["section_id"] for row in sections[peer_network]
                    if right_id in (row["from_node"], row["to_node"])
                ],
            })

    result = {
        "ok": True,
        "feeder_id": settings.get("feeder_id"),
        "network_id": network_id,
        "study_path": settings.get("study_path"),
        "database_mdb": settings.get("database_mdb"),
        "peer_network_id": peer_network,
        "sections": sections,
        "devices_by_network": devices_by_network,
        "section_devices": section_devices,
        "sources_by_network": sources_by_network,
        "transfer_points": transfer_points,
        "nearest_endpoint_pairs": nearest_endpoint_pairs,
        "device_type_names": device_type_names,
        "devices": rows,
        "tie_candidates": [
            row for row in rows
            if row["explicit_tie"] or row["normally_open"] or row["name_hint"]
        ],
    }
    path = output_path(settings, "inventory", "tie_switches.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    result["artifact"] = path
    print(json.dumps({
        "ok": True,
        "network_id": network_id,
        "peer_network_id": peer_network,
        "n_devices": len(rows),
        "n_tie_candidates": len(result["tie_candidates"]),
        "n_transfer_points": len(transfer_points),
        "transfer_points": transfer_points,
        "nearest_endpoint_pairs": nearest_endpoint_pairs[:10],
        "artifact": path,
    }, indent=2, ensure_ascii=False))
    try:
        adapter.close_study(save=False)
    except Exception:
        pass
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--feeder", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--peer-network")
    parser.add_argument("--study", required=True)
    parser.add_argument("--mdb", required=True)
    args = parser.parse_args(argv)

    def _run():
        settings = load_settings(
            feeder_id=args.feeder,
            network_id=args.network,
            synthesize=False,
        )
        settings.update({
            "feeder_id": args.feeder,
            "network_id": args.network,
            "study_path": os.path.realpath(args.study),
            "ui_study_path": os.path.realpath(args.study),
            "database_mdb": os.path.realpath(args.mdb),
        })
        inspect(settings, peer_network=args.peer_network)
        return 0

    run_cympy_main(_run)


if __name__ == "__main__":
    main()
