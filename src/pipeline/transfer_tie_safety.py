# -*- coding: utf-8 -*-
"""Fail-closed gate for an explicitly configured inter-feeder transfer point."""
from __future__ import print_function

import json
import math
import os
from collections import defaultdict, deque

from core.cymdist_commit import (
    CommitMode,
    CommitRequest,
    commit_cymdist_action,
)
from core.feeder_context import output_path


SWITCH_TYPES = ("Sectionalizer", "Switch", "Breaker", "Recloser", "Fuse")
OPEN_PHASES = ("", "none", "open", "0")


class TransferTieSafetyError(RuntimeError):
    def __init__(self, result):
        self.result = result
        RuntimeError.__init__(self, result.get("error") or "Transfer tie safety gate failed")


def _short(network_id):
    value = str(network_id or "").strip().upper()
    return value.rsplit("_", 1)[-1] if value else ""


def _read(obj, field):
    try:
        value = obj.GetValue(field)
        return "" if value is None else str(value).strip()
    except Exception:
        return ""


def _sections(cympy, network_id):
    rows = []
    for section in list(cympy.study.ListSections(network_id) or []):
        rows.append({
            "id": str(getattr(section, "ID", None) or section),
            "from": _read(section, "FromNodeID"),
            "to": _read(section, "ToNodeID"),
        })
    return rows


def _switches(cympy, network_id):
    rows = []
    seen = set()
    for type_name in SWITCH_TYPES:
        dtype = getattr(cympy.enums.DeviceType, type_name, None)
        if dtype is None:
            continue
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id) or [])
        except Exception:
            devices = []
        for device in devices:
            device_id = str(
                getattr(device, "DeviceNumber", None)
                or getattr(device, "ID", None)
                or device
            )
            if device_id in seen:
                continue
            seen.add(device_id)
            phase = _read(device, "ClosedPhase")
            normal = _read(device, "NormalStatus")
            is_open = (
                phase.lower() in OPEN_PHASES
                if phase
                else normal.lower() == "open"
            )
            rows.append({
                "device_id": device_id,
                "type": type_name,
                "closed_phase": phase,
                "normal_status": normal,
                "open": is_open,
            })
    return rows


def _node_coordinates(cympy):
    coordinates = {}
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
        )
        if not node_id:
            continue
        try:
            x = float(getattr(node, "X"))
            y = float(getattr(node, "Y"))
        except Exception:
            try:
                x = float(node.GetValue("X"))
                y = float(node.GetValue("Y"))
            except Exception:
                continue
        coordinates[node_id] = (x, y)
    return coordinates


def _trace_network(section_rows):
    adjacency = defaultdict(list)
    by_id = {}
    for row in section_rows:
        by_id[row["id"]] = row
        if row["from"]:
            adjacency[row["from"]].append(row["id"])
        if row["to"]:
            adjacency[row["to"]].append(row["id"])
    terminals = sorted(node for node, section_ids in adjacency.items() if len(section_ids) == 1)
    visited = set()
    branch_order = []
    starts = terminals + sorted(node for node in adjacency if node not in terminals)
    for start in starts:
        queue = deque([start])
        seen_nodes = set([start])
        while queue:
            node = queue.popleft()
            for section_id in adjacency.get(node, []):
                if section_id in visited:
                    continue
                visited.add(section_id)
                branch_order.append(section_id)
                row = by_id[section_id]
                other = row["to"] if row["from"] == node else row["from"]
                if other and other not in seen_nodes:
                    seen_nodes.add(other)
                    queue.append(other)
    return {
        "section_count": len(section_rows),
        "visited_section_count": len(visited),
        "terminal_nodes": terminals,
        "branch_order": branch_order,
        "incident_sections": {node: list(ids) for node, ids in adjacency.items()},
    }


def _section_switch_index(cympy, network_id, section_rows, switches):
    switch_by_id = {row["device_id"]: row for row in switches}
    result = defaultdict(list)
    for section in list(cympy.study.ListSections(network_id) or []):
        section_id = str(getattr(section, "ID", None) or section)
        try:
            devices = list(section.ListDevices() or [])
        except Exception:
            devices = []
        for device in devices:
            device_id = str(
                getattr(device, "DeviceNumber", None)
                or getattr(device, "ID", None)
                or device
            )
            if device_id in switch_by_id:
                result[section_id].append(switch_by_id[device_id])
    return result


def _discover_candidates(cympy, pair, networks, section_rows, switches, max_distance):
    traces = {feeder: _trace_network(section_rows[feeder]) for feeder in pair}
    section_switches = {
        feeder: _section_switch_index(
            cympy, networks[feeder], section_rows[feeder], switches[feeder]
        )
        for feeder in pair
    }
    coordinates = _node_coordinates(cympy)
    left, right = pair
    candidates = []
    nearest_rejected = None
    seen = set()
    left_terminals = set(traces[left]["terminal_nodes"])
    right_terminals = set(traces[right]["terminal_nodes"])
    left_nodes = sorted(traces[left]["incident_sections"])
    right_nodes = sorted(traces[right]["incident_sections"])
    for left_node in left_nodes:
        for right_node in right_nodes:
            same_node = left_node == right_node
            if not same_node and left_node not in left_terminals and right_node not in right_terminals:
                continue
            distance = None
            if left_node in coordinates and right_node in coordinates:
                ax, ay = coordinates[left_node]
                bx, by = coordinates[right_node]
                distance = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
            devices = []
            sections = {}
            for feeder, node in ((left, left_node), (right, right_node)):
                incident = traces[feeder]["incident_sections"].get(node, [])
                sections[feeder] = incident
                for section_id in incident:
                    for row in section_switches[feeder].get(section_id, []):
                        devices.append(dict(row, feeder=feeder, network_id=networks[feeder], section_id=section_id))
            unique = {row["device_id"]: row for row in devices}
            if not unique:
                continue
            if not same_node and (distance is None or distance > max_distance):
                if distance is not None and (
                    nearest_rejected is None
                    or distance < nearest_rejected["distance"]
                ):
                    nearest_rejected = {
                        "nodes": {left: left_node, right: right_node},
                        "sections": sections,
                        "distance": distance,
                        "devices": [unique[key] for key in sorted(unique)],
                    }
                continue
            key = (left_node, right_node, tuple(sorted(unique)))
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "nodes": {left: left_node, right: right_node},
                "sections": sections,
                "distance": 0.0 if same_node else distance,
                "match": "shared_node" if same_node else "coordinate",
                "devices": [unique[key] for key in sorted(unique)],
            })
    return traces, candidates, nearest_rejected


def inspect_transfer_tie_gate(cympy, settings):
    """Verify only the configured pair; never infer or open a nearby switch."""
    pair = [str(x).strip().upper() for x in (settings.get("transfer_pair") or [])]
    pair = [x for x in pair if x]
    required = bool(settings.get("require_open_transfer_tie_for_diagnostic"))
    result = {
        "ok": True,
        "required": required,
        "pair": pair[:2],
        "mode": "read_only_fail_closed",
    }
    if not required:
        return result
    if len(pair) != 2:
        result.update({
            "ok": False,
            "error_code": "TRANSFER_PAIR_NOT_CONFIGURED",
            "error": "Falta configurar exactamente el par de transferencia del diagnóstico",
        })
        return result

    loaded = [str(x) for x in list(cympy.study.ListNetworks() or [])]
    networks = {}
    for feeder in pair:
        matches = [network for network in loaded if _short(network) == feeder]
        if len(matches) != 1:
            result.update({
                "ok": False,
                "error_code": "TRANSFER_NETWORK_IDENTITY_MISMATCH",
                "error": "La red %s no es única en el estudio" % feeder,
                "loaded_networks": loaded,
            })
            return result
        networks[feeder] = matches[0]

    section_rows = {feeder: _sections(cympy, network) for feeder, network in networks.items()}
    node_sets = {
        feeder: set(
            node for row in rows for node in (row["from"], row["to"]) if node
        )
        for feeder, rows in section_rows.items()
    }
    shared_nodes = sorted(node_sets[pair[0]].intersection(node_sets[pair[1]]))
    switches = {feeder: _switches(cympy, network) for feeder, network in networks.items()}
    max_distance = float(settings.get("transfer_tie_max_distance_m") or 2.0)
    traces, candidates, nearest_rejected = _discover_candidates(
        cympy, pair, networks, section_rows, switches, max_distance
    )
    configured_ids = [str(x).strip() for x in (settings.get("transfer_tie_devices") or []) if str(x).strip()]
    indexed = {
        row["device_id"]: dict(row, feeder=feeder, network_id=networks[feeder])
        for feeder in pair for row in switches[feeder]
    }
    configured = [indexed[device_id] for device_id in configured_ids if device_id in indexed]
    if not configured_ids and len(candidates) == 1:
        configured = list(candidates[0]["devices"])

    result.update({
        "networks": networks,
        "shared_nodes": shared_nodes,
        "configured_device_ids": configured_ids,
        "configured_devices": configured,
        "switch_counts": {feeder: len(switches[feeder]) for feeder in pair},
        "trace": traces,
        "discovery": {
            "max_distance_m": max_distance,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "nearest_rejected": nearest_rejected,
        },
    })
    if len(candidates) > 1 and not configured_ids:
        result.update({
            "ok": False,
            "error_code": "TRANSFER_POINT_AMBIGUOUS",
            "error": "Se encontraron varios puntos de enlace; se requiere identidad inequívoca",
        })
        return result
    if not shared_nodes and not configured_ids and not candidates:
        nearest_text = ""
        if nearest_rejected and nearest_rejected.get("distance") is not None:
            nearest_text = "; candidato descartado más cercano: %.3f m" % (
                nearest_rejected["distance"]
            )
        result.update({
            "ok": False,
            "error_code": "TRANSFER_POINT_NOT_MODELED",
            "error": (
                "CYMDIST no contiene un nodo de enlace ni interruptores de transferencia "
                "identificados para %s-%s%s; se bloquea el diagnóstico para no abrir otro equipo"
                % (pair[0], pair[1], nearest_text)
            ),
        })
        return result
    if configured_ids and len(configured) != len(configured_ids):
        result.update({
            "ok": False,
            "error_code": "TRANSFER_DEVICE_IDENTITY_MISMATCH",
            "error": "Uno o más interruptores configurados no pertenecen al par solicitado",
        })
        return result
    closed = [row for row in configured if not row["open"]]
    if closed:
        result.update({
            "ok": False,
            "error_code": "TRANSFER_TIE_CLOSED",
            "error": "El punto de transferencia debe estar abierto antes del diagnóstico",
            "closed_devices": closed,
        })
        return result
    if not configured:
        result.update({
            "ok": False,
            "error_code": "TRANSFER_DEVICE_NOT_IDENTIFIED",
            "error": "Existe coincidencia topológica, pero falta identificar el interruptor de enlace",
        })
        return result
    result["verified_open"] = True
    return result


def _device_objects(cympy, network_id):
    result = {}
    for type_name in SWITCH_TYPES:
        dtype = getattr(cympy.enums.DeviceType, type_name, None)
        if dtype is None:
            continue
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id) or [])
        except Exception:
            devices = []
        for device in devices:
            device_id = str(
                getattr(device, "DeviceNumber", None)
                or getattr(device, "ID", None)
                or device
            )
            result.setdefault(device_id, device)
    return result


def ensure_transfer_ties_open(cympy, settings):
    """Open only the unique, electrically evidenced transfer candidate."""
    before = inspect_transfer_tie_gate(cympy, settings)
    if before.get("ok"):
        before["opened_device_ids"] = []
        return before
    if before.get("error_code") != "TRANSFER_TIE_CLOSED":
        return before
    target_rows = list(before.get("closed_devices") or [])
    objects = {}
    for feeder, network_id in (before.get("networks") or {}).items():
        for device_id, device in _device_objects(cympy, network_id).items():
            objects[(feeder, device_id)] = device
    opened = []
    for row in target_rows:
        device_id = row["device_id"]
        device = objects.get((row["feeder"], device_id))
        if device is None:
            return dict(before, ok=False, error_code="TRANSFER_DEVICE_IDENTITY_MISMATCH")
        device.SetValue("None", "ClosedPhase")
        if _read(device, "ClosedPhase").lower() not in OPEN_PHASES:
            return dict(before, ok=False, error_code="TRANSFER_OPEN_READBACK_FAILED")
        opened.append(device_id)
    after = inspect_transfer_tie_gate(cympy, settings)
    after["opened_device_ids"] = opened
    after["state_before"] = before
    return after


def require_transfer_tie_gate(cympy, settings, adapter=None, auto_open=False):
    result = inspect_transfer_tie_gate(cympy, settings)
    if (
        not result.get("ok")
        and result.get("error_code") == "TRANSFER_TIE_CLOSED"
        and auto_open
    ):
        if adapter is None:
            result.update({
                "error_code": "TRANSFER_COMMIT_ADAPTER_REQUIRED",
                "error": "La apertura exige coordinador de guardado CYMDIST",
            })
        else:
            target_ids = sorted(
                row["device_id"] for row in (result.get("closed_devices") or [])
            )

            def _mutate():
                opened = ensure_transfer_ties_open(cympy, settings)
                if not opened.get("ok"):
                    raise RuntimeError(
                        opened.get("error_code") or "TRANSFER_OPEN_FAILED"
                    )
                return {
                    "opened_device_ids": opened.get("opened_device_ids") or [],
                    "requested_values": {
                        "tie:%s:ClosedPhase" % device_id: "None"
                        for device_id in target_ids
                    },
                }

            def _readback():
                checked = inspect_transfer_tie_gate(cympy, settings)
                open_ids = set(
                    row["device_id"]
                    for row in (checked.get("configured_devices") or [])
                    if row.get("open")
                )
                return {
                    "tie:%s:ClosedPhase" % device_id: (
                        "None" if device_id in open_ids else "Closed"
                    )
                    for device_id in target_ids
                }

            commit = commit_cymdist_action(
                CommitRequest(
                    settings=settings,
                    action="transfer_ties_open",
                    mode=CommitMode.STUDY_AND_DATABASE,
                    adapter=adapter,
                    readback=_readback,
                ),
                _mutate,
            )
            if not commit.get("ok") or not commit.get("reopen_verified"):
                result.update({
                    "ok": False,
                    "error_code": "TRANSFER_COMMIT_NOT_VERIFIED",
                    "error": "No se verificó el guardado del enlace abierto",
                    "commit": commit,
                })
            else:
                result = inspect_transfer_tie_gate(cympy, settings)
                result["opened_device_ids"] = target_ids
                result["commit"] = commit
    path = output_path(settings, "diagnostics", "transfer_tie_gate.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    result["artifact"] = path
    if not result.get("ok"):
        raise TransferTieSafetyError(result)
    return result
