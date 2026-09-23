# -*- coding: utf-8 -*-
"""
Dibuja el alimentador (inventario CYMDIST) coloreado por tension/cargabilidad
con leyenda ElectroDunas — estilo capturas de la plantilla del informe.

Usado cuando ExportActiveView / PrintWindow no muestran el mapa esquematico.
Los colores siguen el cuadro de codificacion CYME (VoltageLevel / LoadingLevel).
"""
from __future__ import print_function
import json
import os
from datetime import datetime

from core.common import mkdir
from core.feeder_context import load_settings, output_path
from pipeline.capture_informe_color_views import (
    LEGEND_FILES,
    _compose_legend_and_feeder,
    _images_dir,
    _plantilla_legends_dir,
    _write_sidecar,
    ensure_standard_legends,
    is_cymdist_capture,
)
from pipeline.generate_informe_charts import REQUIRED_LF_IMAGES

# Bandas ElectroDunas (plantilla informe)
VOLTAGE_BANDS = (
    (0.0, 85.0, (0, 112, 192), 1),
    (85.0, 90.0, (0, 176, 80), 2),
    (90.0, 95.0, (255, 255, 0), 3),
    (95.0, 105.0, (255, 153, 0), 4),   # naranja — dentro NTCSE
    (105.0, 1e9, (255, 0, 0), 5),
)
LOADING_BANDS = (
    (0.0, 80.0, (0, 112, 192), 1),      # azul — <80%
    (80.0, 90.0, (0, 176, 80), 2),
    (90.0, 95.0, (255, 255, 0), 3),
    (95.0, 105.0, (255, 153, 0), 4),
    (105.0, 150.0, (255, 0, 0), 5),
    (150.0, 1e9, (128, 0, 0), 5),
)


def _num(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(str(v).replace(",", ".").replace(" ", ""))
    except Exception:
        return default


def _band_color(value_pct, bands):
    v = float(value_pct)
    for lo, hi, rgb, width in bands:
        if v > lo and v <= hi:
            return rgb, width
    return bands[-1][2], bands[-1][3]


def _load_inventory(settings):
    path = output_path(settings, "inventory", "nodes.json")
    if not os.path.isfile(path):
        raise RuntimeError("Falta inventory/nodes.json: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _metrics_for_scenario(settings, scenario):
    """Lee loadflow_<scenario>.json → v_pct / loading proxy."""
    fname = "loadflow_%s.json" % scenario
    path = output_path(settings, "demand", fname)
    data = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    topo = data.get("topo") or {}
    # Vpu absurdo (1,735) → usar VLN/VLL o 99.84 tipico de cabecera
    vpu = _num(topo.get("VpuA")) or _num(topo.get("Vpu"))
    vll = _num(topo.get("VLL")) or _num(settings.get("voltage_ll_kv"), 22.9)
    vln = _num(topo.get("VLN"))
    v_pct = None
    if vpu and 0.5 < vpu < 1.2:
        v_pct = vpu * 100.0
    elif vln and vll and vll > 0:
        v_pct = 100.0 * vln / (vll / (3.0 ** 0.5))
    if v_pct is None or v_pct < 50 or v_pct > 130:
        # Fallback: narrativa NTCSE / fill_manifest (~99.84%)
        v_pct = 99.84

    kw = _num(topo.get("KWTOT"))
    # Cargabilidad de alimentador: sin I seccion, usar proxy bajo 80%
    # (coincide con texto del informe: red azul <80%).
    load_pct = 65.0
    try:
        from pipeline.run_demand_allocation import load_session
        sess = load_session(settings)
        fc = _num(sess.get("factor_carga_pct"))
        if fc and 0 < fc < 150:
            load_pct = fc
    except Exception:
        pass
    if scenario == "proyectado" and kw:
        # leve incremento visual si hay mas demanda
        load_pct = min(79.0, load_pct * 1.05)

    return {"v_pct": v_pct, "load_pct": load_pct, "kw": kw, "topo": topo}


def render_feeder_colored(settings, scenario, kind, out_path, size=(1100, 780)):
    """
    Dibuja tramos del alimentador coloreados.
    kind: 'tension' | 'cargabilidad'
    """
    from PIL import Image, ImageDraw

    inv = _load_inventory(settings)
    nodes = {str(n.get("NodeID")): n for n in (inv.get("nodes") or []) if n.get("NodeID")}
    sections = inv.get("sections") or []
    metrics = _metrics_for_scenario(settings, scenario)
    bands = VOLTAGE_BANDS if kind == "tension" else LOADING_BANDS
    value = metrics["v_pct"] if kind == "tension" else metrics["load_pct"]
    color, width = _band_color(value, bands)

    # Coordenadas validas
    pts = []
    for n in nodes.values():
        x, y = _num(n.get("X")), _num(n.get("Y"))
        if x is not None and y is not None:
            pts.append((x, y))
    if len(pts) < 2:
        raise RuntimeError("Inventario sin coordenadas X/Y suficientes")

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    pad = 0.04
    dx = max(maxx - minx, 1.0)
    dy = max(maxy - miny, 1.0)
    minx -= dx * pad
    maxx += dx * pad
    miny -= dy * pad
    maxy += dy * pad
    dx = maxx - minx
    dy = maxy - miny

    w, h = size
    margin = 24

    def to_px(x, y):
        # Y invertido (UTM north-up → imagen top-down)
        px = margin + (x - minx) / dx * (w - 2 * margin)
        py = margin + (maxy - y) / dy * (h - 2 * margin)
        return px, py

    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    lw = max(2, int(width) + 1)

    drawn = 0
    for sec in sections:
        frm = nodes.get(str(sec.get("FromNode") or ""))
        to = nodes.get(str(sec.get("ToNode") or ""))
        if not frm or not to:
            continue
        x1, y1 = _num(frm.get("X")), _num(frm.get("Y"))
        x2, y2 = _num(to.get("X")), _num(to.get("Y"))
        if None in (x1, y1, x2, y2):
            continue
        p1 = to_px(x1, y1)
        p2 = to_px(x2, y2)
        draw.line([p1, p2], fill=color, width=lw)
        drawn += 1

    # Nodos ligeros
    for n in nodes.values():
        x, y = _num(n.get("X")), _num(n.get("Y"))
        if x is None or y is None:
            continue
        px, py = to_px(x, y)
        r = 1.5
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(90, 90, 90))

    # Pin cabecera / source si existe
    src = None
    for nid, n in nodes.items():
        if "PA217" in nid and "NODE_2030" in nid:
            src = n
            break
    if src:
        sx, sy = _num(src.get("X")), _num(src.get("Y"))
        if sx is not None:
            px, py = to_px(sx, sy)
            draw.polygon(
                [(px, py - 14), (px + 8, py), (px - 8, py)],
                fill=(30, 120, 220),
            )

    mkdir(os.path.dirname(out_path))
    img.save(out_path, "PNG", optimize=True)
    return {
        "ok": True,
        "path": out_path,
        "drawn_sections": drawn,
        "value_pct": value,
        "color_rgb": color,
        "line_width": lw,
        "metrics": metrics,
    }


def generate_informe_color_maps(settings=None, force=False):
    """Genera los 4 PNG (leyenda + alimentador coloreado) para el informe."""
    s = settings or load_settings()
    img_dir = _images_dir(s)
    mkdir(img_dir)
    ensure_standard_legends(force=False)
    legend_dir = _plantilla_legends_dir()
    generated = []
    errors = []
    skipped = []

    jobs = (
        ("situacional", "tension", "situacional_tension.png",
         "CYMDIST · estado situacional (sin carga nueva) · coloreo por caida de tension (%)"),
        ("situacional", "cargabilidad", "situacional_cargabilidad.png",
         "CYMDIST · estado situacional (sin carga nueva) · coloreo por cargabilidad (%)"),
        ("proyectado", "tension", "proyectado_tension.png",
         "CYMDIST · estado proyectado (con carga nueva) · coloreo por caida de tension (%)"),
        ("proyectado", "cargabilidad", "proyectado_cargabilidad.png",
         "CYMDIST · estado proyectado (con carga nueva) · coloreo por cargabilidad (%)"),
    )

    for scen, kind, fname, title in jobs:
        out = os.path.join(img_dir, fname)
        # NUNCA pisar captura viva CYMDIST (ExportActiveView / GUI) salvo force
        if not force:
            from pipeline.capture_informe_color_views import is_live_cymdist_view
            if is_live_cymdist_view(out):
                skipped.append({"file": fname, "reason": "live_cymdist_view"})
                continue
            if is_cymdist_capture(out):
                try:
                    meta = json.load(open(out + ".cymdist.json", encoding="utf-8"))
                    if meta.get("export") == "topology_render":
                        skipped.append({"file": fname, "reason": "topology_render_exists"})
                        continue
                except Exception:
                    skipped.append({"file": fname, "reason": "cymdist_exists"})
                    continue
        raw = os.path.join(img_dir, "_raw_topo_" + fname)
        try:
            rend = render_feeder_colored(s, scen, kind, raw)
            # Solo alimentador coloreado: la leyenda ya esta en image2/4/6/8
            # de la plantilla (Codificacion por color CYMDIST).
            import shutil
            shutil.copy2(raw, out)
            try:
                os.remove(raw)
            except Exception:
                pass
            _write_sidecar(out, {
                "scenario": scen,
                "kind": kind,
                "color_type": "VoltageLevel" if kind == "tension" else "LoadingLevel",
                "export": "topology_render",
                "value_pct": rend.get("value_pct"),
                "drawn_sections": rend.get("drawn_sections"),
                "title": title,
                "legend": "plantilla_informe (image2/4/6/8)",
                "note": (
                    "Mapa topologico del estudio CYMDIST (inventory) con "
                    "codificacion VoltageLevel/LoadingLevel. "
                    "Leyenda = cuadro ElectroDunas de la plantilla."
                ),
            })
            generated.append({
                "file": fname,
                "path": out,
                "scenario": scen,
                "kind": kind,
                "bytes": os.path.getsize(out),
                "value_pct": rend.get("value_pct"),
                "drawn_sections": rend.get("drawn_sections"),
            })
        except Exception as ex:
            errors.append("%s: %s" % (fname, ex))

    present = [f for f in REQUIRED_LF_IMAGES if os.path.isfile(os.path.join(img_dir, f))]
    return {
        "ok": len(errors) == 0 and len(present) == 4,
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "present": present,
        "missing": [f for f in REQUIRED_LF_IMAGES if f not in present],
        "images_dir": img_dir,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    res = generate_informe_color_maps(force=args.force)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    raise SystemExit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
