# -*- coding: utf-8 -*-
"""Inventario de nodos y tramos del alimentador activo (para nueva SpotLoad)."""
from __future__ import print_function
import json
from core.common import require_cympy, load_json, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path


def _normalize_id(v):
    """CymPy a veces devuelve IDs con comillas literales: '16730'."""
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) >= 2 and ((s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')):
        s = s[1:-1].strip()
    return s


def _safe_attr(obj, *names):
    for name in names:
        try:
            v = getattr(obj, name, None)
            if v is not None and str(v) != "":
                return v
        except Exception:
            pass
    return ""


def _safe_get(obj, field):
    try:
        return obj.GetValue(field)
    except Exception:
        return ""


def _section_id(sec):
    return _normalize_id(
        _safe_attr(sec, "SectionNumber", "ID")
        or _safe_get(sec, "SectionNumber")
        or ""
    )


def _node_ends(sec):
    # Preferir GetValue(FromNodeID/ToNodeID): sin comillas literales.
    frm = (
        _safe_get(sec, "FromNodeID")
        or _safe_attr(sec, "FromNode", "FromNodeID", "FromNodeNumber")
        or _safe_get(sec, "FromNode")
    )
    to = (
        _safe_get(sec, "ToNodeID")
        or _safe_attr(sec, "ToNode", "ToNodeID", "ToNodeNumber")
        or _safe_get(sec, "ToNode")
    )
    return _normalize_id(frm), _normalize_id(to)


def collect_nodes_sections(cympy, network_id=None):
    """Lista nodos + tramos y el mapa nodo -> tramos."""
    nodes = []
    try:
        raw_nodes = list(cympy.study.ListNodes())
    except Exception:
        raw_nodes = []
    for n in raw_nodes:
        nid = _normalize_id(_safe_attr(n, "ID", "NodeID", "NodeNumber") or "")
        if not nid:
            continue
        nodes.append({
            "NodeID": nid,
            "Label": nid,
            "X": str(_safe_attr(n, "X") or ""),
            "Y": str(_safe_attr(n, "Y") or ""),
        })

    sections = []
    try:
        if network_id:
            try:
                raw_secs = list(cympy.study.ListSections(str(network_id)))
            except TypeError:
                raw_secs = list(cympy.study.ListSections())
        else:
            raw_secs = list(cympy.study.ListSections())
    except Exception:
        raw_secs = []

    by_node = {}
    for sec in raw_secs:
        sid = _section_id(sec)
        if not sid:
            continue
        frm, to = _node_ends(sec)
        row = {
            "SectionID": sid,
            "FromNode": frm,
            "ToNode": to,
            "NetworkID": str(network_id or ""),
        }
        sections.append(row)
        for nid in (frm, to):
            if not nid:
                continue
            by_node.setdefault(nid, []).append(row)

    # Anotar cuantos tramos tiene cada nodo
    for n in nodes:
        linked = by_node.get(n["NodeID"]) or []
        n["n_sections"] = len(linked)
        n["sections"] = [s["SectionID"] for s in linked]

    return {
        "nodes": nodes,
        "sections": sections,
        "by_node": by_node,
    }


def save_inventory(settings, data):
    out = output_path(settings, "inventory", "nodes.json")
    payload = {
        "feeder_id": settings.get("feeder_id"),
        "network_id": settings.get("network_id"),
        "n_nodes": len(data.get("nodes") or []),
        "n_sections": len(data.get("sections") or []),
        "nodes": data.get("nodes") or [],
        "sections": data.get("sections") or [],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return out


def load_inventory(settings):
    path = output_path(settings, "inventory", "nodes.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), path
    except Exception:
        return None, path


def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    data = collect_nodes_sections(c, s.get("network_id"))
    out = save_inventory(s, data)
    print("Nodos:", len(data["nodes"]), "| Tramos:", len(data["sections"]))
    print(out)


if __name__ == "__main__":
    run_cympy_main(main)
