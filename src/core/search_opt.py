from __future__ import print_function
"""
Busqueda optimizada de cargas / puntos de subestacion en el alimentador.
Algoritmo: ranking multi-criterio (token overlap + prefijo + subsecuencia + fuzzy).
"""
import re

def _norm(s):
    s = (s or "").upper()
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _tokens(s):
    return [t for t in _norm(s).split(" ") if t]

def _lcs_ratio(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    dp = [0] * (lb + 1)
    best = 0
    for i in range(1, la + 1):
        prev = 0
        for j in range(1, lb + 1):
            cur = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev + 1
                if dp[j] > best:
                    best = dp[j]
            else:
                dp[j] = 0
            prev = cur
    return float(best) / float(max(la, lb))

def score_match(query, candidate, extra_fields=None):
    """Devuelve score 0..100. Mayor = mejor coincidencia."""
    q = _norm(query)
    c = _norm(candidate)
    if not q:
        return 0.0
    if q == c:
        return 100.0
    if q in c:
        return 90.0 + min(9.0, 50.0 / max(1, len(c)))

    qt, ct = _tokens(q), set(_tokens(c))
    if not qt:
        return 0.0
    overlap = sum(1 for t in qt if t in ct) / float(len(qt))
    prefix = 1.0 if c.startswith(q[: min(4, len(q))]) else 0.0
    lcs = _lcs_ratio(q, c)

    # Campos extra (cliente, seccion, etc.)
    extra_hit = 0.0
    if extra_fields:
        blob = _norm(" ".join(str(x) for x in extra_fields if x))
        if q in blob:
            extra_hit = 0.25
        else:
            bt = set(_tokens(blob))
            extra_hit = 0.15 * (sum(1 for t in qt if t in bt) / float(len(qt)))

    score = 100.0 * (0.45 * overlap + 0.25 * lcs + 0.15 * prefix + 0.15 * extra_hit)
    return round(min(99.0, score), 2)

def search_items(query, items, key_fields, limit=30):
    """
    items: list of dict
    key_fields: campos a scorear (el primero es primario)
    """
    ranked = []
    for it in items:
        primary = str(it.get(key_fields[0], ""))
        extras = [it.get(k) for k in key_fields[1:]]
        sc = score_match(query, primary, extras)
        # también probar extras como primario
        for ex in extras:
            sc = max(sc, score_match(query, str(ex or ""), [primary]))
        if sc > 0:
            row = dict(it)
            row["_score"] = sc
            ranked.append(row)
    ranked.sort(key=lambda x: (-x["_score"], str(x.get(key_fields[0], ""))))
    return ranked[:limit]
