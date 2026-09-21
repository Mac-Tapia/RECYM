# -*- coding: utf-8 -*-
"""Helpers para nueva SpotLoad concentrada trifasica (sin EA/kWh)."""
from __future__ import print_function
import math


def compute_pq(mode, p_kw, q_kvar=None, cosfi=None):
    """
    Calcula P/Q para carga nueva.
    mode: KW_COSFI | KW_KVAR
    """
    if p_kw is None or p_kw == "":
        raise ValueError("Indique potencia activa P (kW).")
    p = float(p_kw)
    if p < 0:
        raise ValueError("P (kW) no puede ser negativa.")
    m = (mode or "KW_COSFI").upper().strip()
    if m == "KW_COSFI":
        if cosfi is None or cosfi == "":
            raise ValueError("Indique cos φ.")
        fp = float(cosfi)
        if fp <= 0 or fp > 1:
            raise ValueError("cos φ debe estar entre 0.01 y 1.")
        q = p * math.tan(math.acos(min(1.0, max(0.01, fp))))
        return p, q, fp
    if m == "KW_KVAR":
        if q_kvar is None or q_kvar == "":
            raise ValueError("Indique Q (kvar).")
        q = float(q_kvar)
        s = math.sqrt(p * p + q * q) or 1.0
        fp = abs(p) / s if s else 1.0
        return p, q, fp
    raise ValueError("Modo no soportado: use KW_COSFI o KW_KVAR.")


def sanitize_load_name(name):
    """
    Nombre visible en CYMDIST = DeviceNumber.
    Solo letras, digitos, _ y -; mayusculas (CYME fuerza uppercase).
    """
    import re
    raw = str(name or "").strip()
    if not raw:
        return ""
    # Espacios -> _
    raw = raw.replace(" ", "_")
    raw = re.sub(r"[^A-Za-z0-9_\-]", "", raw)
    raw = raw.strip("_-")
    if not raw:
        return ""
    return raw.upper()


def load_id_from_section(section_id, node_id=None):
    """Convencion Electro Dunas: SEC_xxx -> DEV_xxx."""
    sid = str(section_id or "").strip()
    if sid.upper().startswith("SEC_"):
        return "DEV_" + sid[4:]
    if sid:
        return "DEV_" + sid
    nid = str(node_id or "").strip()
    if not nid:
        raise ValueError("Sin SectionID ni NodeID para generar LoadID.")
    return "DEV_LOAD_" + nid


def unique_load_id(base_id, existing_ids):
    """Evita colision con SpotLoads ya presentes."""
    existing = set(str(x) for x in (existing_ids or []))
    base = str(base_id)
    if base not in existing:
        return base
    n = 2
    while True:
        cand = "%s_%d" % (base, n)
        if cand not in existing:
            return cand
        n += 1


def _qid(v):
    s = str(v or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')):
        return s[1:-1].strip()
    return s


def pick_section_for_node(node_id, sections, prefer_to_node=True):
    """
    Elige un tramo ligado al nodo.
    Preferencia: ToNode == nodo (carga al final del tramo), luego FromNode.
    Si hay varios, el primero de la preferencia.
    """
    nid = _qid(node_id)
    to_hits = []
    from_hits = []
    for s in sections or []:
        sid = _qid(s.get("SectionID"))
        if not sid:
            continue
        if _qid(s.get("ToNode")) == nid:
            to_hits.append(s)
        if _qid(s.get("FromNode")) == nid:
            from_hits.append(s)
    if prefer_to_node and to_hits:
        return to_hits[0]
    if from_hits:
        return from_hits[0]
    if to_hits:
        return to_hits[0]
    return None


def filter_nodes(nodes, query, limit=80):
    """Filtro parcial case-insensitive sobre NodeID / Label."""
    q = (query or "").strip().lower()
    rows = list(nodes or [])
    if q:
        rows = [
            n for n in rows
            if q in str(n.get("NodeID") or "").lower()
            or q in str(n.get("Label") or "").lower()
        ]
    return rows[: int(limit)]
