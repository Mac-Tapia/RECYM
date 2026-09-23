# -*- coding: utf-8 -*-
"""
Genera topologia.png = mapa satelite de la carga nueva conectada (§2.1 informe).

Fuente de ubicacion:
  1) data/output/.../loads/new_spot_loads_report.csv (ultima OK)
  2) demand/session.json → last_spot_load
  3) Coord X/Y del nodo en inventory/nodes.json (UTM → WGS84)

Mapa:
  - Si hay GOOGLE_MAPS_API_KEY o settings.google_maps_api_key → Static Maps hybrid
  - Si no → mosaico Esri World Imagery (satelite) + marcador PIL
"""
from __future__ import print_function

import csv
import json
import math
import os
import ssl
import urllib.request
import urllib.parse
from datetime import datetime

from core.common import mkdir, p
from core.feeder_context import load_settings, output_path
from pipeline.inventory_nodes import load_inventory

TOPOLOGIA_PNG = "topologia.png"
DEFAULT_UTM_ZONE = 18
DEFAULT_SIZE = (900, 640)
DEFAULT_ZOOM = 17


def _images_dir(settings):
    out_base = settings.get("output_dir") or os.path.join(
        "data", "output", "feeders", str(settings.get("feeder_id") or "feeder")
    )
    if not os.path.isabs(out_base):
        return p(*(out_base.replace("\\", "/").split("/") + ["informe_images"]))
    return os.path.join(out_base, "informe_images")


def _num(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except Exception:
        return None


def utm_to_wgs84(easting, northing, zone=DEFAULT_UTM_ZONE, southern=True):
    """Conversion UTM → lat/lon WGS84 (sin pyproj)."""
    # Constantes WGS84
    a = 6378137.0
    e2 = 0.00669437999014
    k0 = 0.9996
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    x = float(easting) - 500000.0
    y = float(northing)
    if southern:
        y -= 10000000.0

    m = y / k0
    mu = m / (a * (1 - e2 / 4.0 - 3 * e2 * e2 / 64.0 - 5 * e2 ** 3 / 256.0))

    phi1 = (
        mu
        + (3 * e1 / 2.0 - 27 * e1 ** 3 / 32.0) * math.sin(2 * mu)
        + (21 * e1 * e1 / 16.0 - 55 * e1 ** 4 / 32.0) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96.0) * math.sin(6 * mu)
    )

    n2 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t2 = math.tan(phi1) ** 2
    c2 = e2 * math.cos(phi1) ** 2 / (1 - e2)
    r2 = a * (1 - e2) / ((1 - e2 * math.sin(phi1) ** 2) ** 1.5)
    d = x / (n2 * k0)

    lat = phi1 - (n2 * math.tan(phi1) / r2) * (
        d * d / 2.0
        - (5 + 3 * t2 + 10 * c2 - 4 * c2 * c2 - 9 * e2) * d ** 4 / 24.0
        + (61 + 90 * t2 + 298 * c2 + 45 * t2 * t2 - 252 * e2 - 3 * c2 * c2)
        * d ** 6
        / 720.0
    )
    lon = (
        d
        - (1 + 2 * t2 + c2) * d ** 3 / 6.0
        + (5 - 2 * c2 + 28 * t2 - 3 * c2 * c2 + 8 * e2 + 24 * t2 * t2)
        * d ** 5
        / 120.0
    ) / math.cos(phi1)

    lon_deg = math.degrees(lon) + (zone * 6.0 - 183.0)
    lat_deg = math.degrees(lat)
    return lat_deg, lon_deg


def _latlon_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = (lon + 180.0) / 360.0 * n
    ytile = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def _tile_to_pixel(lat, lon, zoom, tile_x0, tile_y0, tile_size=256):
    xt, yt = _latlon_to_tile(lat, lon, zoom)
    px = (xt - tile_x0) * tile_size
    py = (yt - tile_y0) * tile_size
    return int(round(px)), int(round(py))


def _http_get(url, timeout=45):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RECYM-informe/1.0 (Electro Dunas)"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _google_api_key(settings):
    return (
        (settings or {}).get("google_maps_api_key")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or os.environ.get("RECYM_GOOGLE_MAPS_KEY")
        or ""
    ).strip()


def _fetch_google_static(lat, lon, out_path, size, zoom, label, api_key):
    w, h = size
    # Google max 640 without premium; allow up to that
    w = min(int(w), 640)
    h = min(int(h), 640)
    marker = "color:0xFFFF00|label:%s|%s,%s" % (
        (label or "C")[:1].upper() or "C",
        "%.6f" % lat,
        "%.6f" % lon,
    )
    url = (
        "https://maps.googleapis.com/maps/api/staticmap"
        "?center=%.6f,%.6f&zoom=%d&size=%dx%d&maptype=hybrid&scale=2"
        "&markers=%s&key=%s"
        % (lat, lon, int(zoom), w, h, urllib.parse.quote(marker, safe="|,."), api_key)
    )
    data = _http_get(url)
    if not data or data[:8] == b"<html" or data[:15] == b"The Google Maps":
        raise RuntimeError("Google Static Maps no devolvio imagen")
    with open(out_path, "wb") as f:
        f.write(data)
    return {"provider": "google_static", "url_host": "maps.googleapis.com"}


def _fetch_esri_mosaic(lat, lon, out_path, size, zoom, label, nearby_lines=None):
    """Mosaico World Imagery + marcador + tramos cercanos."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    tile_size = 256
    cx, cy = _latlon_to_tile(lat, lon, zoom)
    # tiles necesarios para cubrir w×h centrado en el punto
    tiles_x = int(math.ceil(w / float(tile_size))) + 2
    tiles_y = int(math.ceil(h / float(tile_size))) + 2
    x0 = int(math.floor(cx - tiles_x / 2.0))
    y0 = int(math.floor(cy - tiles_y / 2.0))

    mosaic = Image.new("RGB", (tiles_x * tile_size, tiles_y * tile_size), (30, 30, 30))
    base = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%d/%d/%d"
    for iy in range(tiles_y):
        for ix in range(tiles_x):
            tx = x0 + ix
            ty = y0 + iy
            try:
                raw = _http_get(base % (zoom, ty, tx), timeout=30)
                tile = Image.open(__import__("io").BytesIO(raw)).convert("RGB")
                mosaic.paste(tile, (ix * tile_size, iy * tile_size))
            except Exception:
                pass

    # recortar centrado en el punto de carga
    px, py = _tile_to_pixel(lat, lon, zoom, x0, y0, tile_size)
    left = max(0, px - w // 2)
    top = max(0, py - h // 2)
    if left + w > mosaic.width:
        left = max(0, mosaic.width - w)
    if top + h > mosaic.height:
        top = max(0, mosaic.height - h)
    img = mosaic.crop((left, top, left + w, top + h))
    draw = ImageDraw.Draw(img)

    # tramos cercanos (cian)
    for ln in nearby_lines or []:
        try:
            x1, y1 = _tile_to_pixel(ln["lat1"], ln["lon1"], zoom, x0, y0, tile_size)
            x2, y2 = _tile_to_pixel(ln["lat2"], ln["lon2"], zoom, x0, y0, tile_size)
            p1 = (x1 - left, y1 - top)
            p2 = (x2 - left, y2 - top)
            draw.line([p1, p2], fill=(0, 220, 255), width=3)
        except Exception:
            pass

    mx, my = px - left, py - top
    # flecha / pin amarillo
    r = 14
    draw.ellipse((mx - r, my - r, mx + r, my + r), outline=(255, 220, 0), width=4)
    draw.ellipse((mx - 5, my - 5, mx + 5, my + 5), fill=(255, 60, 60))
    # punta
    draw.polygon(
        [(mx, my + r + 18), (mx - 10, my + r - 2), (mx + 10, my + r - 2)],
        fill=(255, 220, 0),
        outline=(40, 40, 0),
    )

    try:
        font = ImageFont.truetype("arial.ttf", 18)
        font_sm = ImageFont.truetype("arial.ttf", 13)
    except Exception:
        font = ImageFont.load_default()
        font_sm = font

    tag = (label or "CARGA NUEVA")[:48]
    # cartel
    tw = max(160, min(w - 20, 12 * len(tag) + 24))
    box = (mx + 18, my - 42, mx + 18 + tw, my - 8)
    if box[2] > w - 8:
        box = (mx - 18 - tw, my - 42, mx - 18, my - 8)
    draw.rectangle(box, fill=(255, 255, 255), outline=(180, 0, 0), width=2)
    draw.text((box[0] + 8, box[1] + 6), tag, fill=(180, 0, 0), font=font)

    # pie
    footer = "Vista satelite · carga nueva conectada · %.6f, %.6f" % (lat, lon)
    draw.rectangle((0, h - 28, w, h), fill=(0, 0, 0, 160) if img.mode == "RGBA" else (20, 20, 20))
    draw.text((10, h - 22), footer, fill=(240, 240, 240), font=font_sm)

    img.save(out_path, format="PNG", optimize=True)
    return {"provider": "esri_world_imagery", "zoom": zoom, "size": [w, h]}


def _load_session(settings):
    path = output_path(settings, "demand", "session.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _load_spot_rows(settings):
    path = output_path(settings, "loads", "new_spot_loads_report.csv")
    if not os.path.isfile(path):
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except Exception:
        return []
    return rows


def resolve_new_load_node(settings):
    """Devuelve dict con NodeID/LoadID/SectionID/X/Y/lat/lon para la carga nueva."""
    inv, inv_path = load_inventory(settings)
    nodes = {str(n.get("NodeID")): n for n in ((inv or {}).get("nodes") or [])}
    sections = {(s.get("SectionID") or ""): s for s in ((inv or {}).get("sections") or [])}

    node_id = ""
    load_id = ""
    section_id = ""
    p_kw = None
    source = None

    rows = [r for r in _load_spot_rows(settings) if str(r.get("Estado") or "").upper() in ("OK", "TRUE", "1", "CREATED", "")]
    # Preferir ultima fila con LoadID
    for r in reversed(_load_spot_rows(settings)):
        if str(r.get("created") or "").lower() in ("false", "0", "no") and str(r.get("Estado") or "").upper() not in ("OK", ""):
            continue
        if str(r.get("Estado") or "").upper() in ("ERROR", "FAIL", "SKIP"):
            continue
        lid = str(r.get("LoadID") or "").strip()
        nid = str(r.get("NodeID") or "").strip()
        sid = str(r.get("SectionID") or "").strip()
        if lid or nid:
            load_id = lid
            node_id = nid or lid
            section_id = sid
            p_kw = _num(r.get("P_kW"))
            source = "new_spot_loads_report.csv"
            break

    if not node_id:
        sess = _load_session(settings)
        last = str(sess.get("last_spot_load") or "").strip()
        if last:
            load_id = last
            node_id = last
            source = "session.json"

    if not node_id:
        return {
            "ok": False,
            "error": "No hay carga nueva registrada (SpotLoad §4).",
            "inventory": inv_path,
        }

    # Si NodeID no esta en inventario, probar LoadID o extremos del tramo
    node = nodes.get(node_id) or nodes.get(load_id)
    if not node and section_id and section_id in sections:
        sec = sections[section_id]
        for cand in (sec.get("ToNode"), sec.get("FromNode")):
            if cand and cand in nodes:
                node = nodes[cand]
                node_id = cand
                break

    if not node:
        return {
            "ok": False,
            "error": "Nodo %s no encontrado en inventario (sin X/Y)." % node_id,
            "NodeID": node_id,
            "LoadID": load_id,
            "inventory": inv_path,
        }

    x = _num(node.get("X"))
    y = _num(node.get("Y"))
    if x is None or y is None:
        return {
            "ok": False,
            "error": "Nodo %s sin coordenadas X/Y." % node_id,
            "NodeID": node_id,
        }

    zone = int((settings or {}).get("map_utm_zone") or DEFAULT_UTM_ZONE)
    southern = bool((settings or {}).get("map_utm_southern", True))
    lat, lon = utm_to_wgs84(x, y, zone=zone, southern=southern)

    return {
        "ok": True,
        "NodeID": node_id,
        "LoadID": load_id or node_id,
        "SectionID": section_id,
        "P_kW": p_kw,
        "X": x,
        "Y": y,
        "lat": lat,
        "lon": lon,
        "utm_zone": zone,
        "source": source,
        "inventory": inv_path,
        "label": load_id or node_id,
    }


def _nearby_lines(settings, center_node_id, max_m=350.0, limit=80):
    """Tramos cercanos en lat/lon para dibujar la red en el mapa."""
    inv, _ = load_inventory(settings)
    nodes = {str(n.get("NodeID")): n for n in ((inv or {}).get("nodes") or [])}
    center = nodes.get(str(center_node_id))
    if not center:
        return []
    cx, cy = _num(center.get("X")), _num(center.get("Y"))
    if cx is None or cy is None:
        return []
    zone = int((settings or {}).get("map_utm_zone") or DEFAULT_UTM_ZONE)
    southern = bool((settings or {}).get("map_utm_southern", True))
    lines = []
    for sec in (inv or {}).get("sections") or []:
        a = nodes.get(str(sec.get("FromNode")))
        b = nodes.get(str(sec.get("ToNode")))
        if not a or not b:
            continue
        ax, ay = _num(a.get("X")), _num(a.get("Y"))
        bx, by = _num(b.get("X")), _num(b.get("Y"))
        if None in (ax, ay, bx, by):
            continue
        mid_x = (ax + bx) / 2.0
        mid_y = (ay + by) / 2.0
        if abs(mid_x - cx) > max_m or abs(mid_y - cy) > max_m:
            continue
        lat1, lon1 = utm_to_wgs84(ax, ay, zone, southern)
        lat2, lon2 = utm_to_wgs84(bx, by, zone, southern)
        lines.append({"lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2})
        if len(lines) >= limit:
            break
    return lines


def generate_location_map(settings=None, out_dir=None, force=False):
    """
    Genera informe_images/topologia.png con mapa satelite de la carga nueva.
    Retorna dict {ok, path, ...}.
    """
    s = settings or load_settings()
    img_dir = out_dir or _images_dir(s)
    mkdir(img_dir)
    out_path = os.path.join(img_dir, TOPOLOGIA_PNG)

    loc = resolve_new_load_node(s)
    if not loc.get("ok"):
        return {"ok": False, "error": loc.get("error"), "path": out_path, "location": loc}

    size = (
        int((s or {}).get("map_width") or DEFAULT_SIZE[0]),
        int((s or {}).get("map_height") or DEFAULT_SIZE[1]),
    )
    zoom = int((s or {}).get("map_zoom") or DEFAULT_ZOOM)
    label = loc.get("label") or loc.get("LoadID") or "CARGA"
    lat, lon = loc["lat"], loc["lon"]
    nearby = _nearby_lines(s, loc["NodeID"])

    provider_info = {}
    api_key = _google_api_key(s)
    errors = []
    if api_key:
        try:
            provider_info = _fetch_google_static(lat, lon, out_path, size, zoom, label, api_key)
        except Exception as ex:
            errors.append("google: %s" % ex)
            provider_info = {}

    if not provider_info:
        try:
            provider_info = _fetch_esri_mosaic(
                lat, lon, out_path, size, zoom, label, nearby_lines=nearby
            )
        except Exception as ex:
            return {
                "ok": False,
                "error": "No se pudo generar mapa: %s" % ex,
                "errors": errors + [str(ex)],
                "location": loc,
            }

    meta = {
        "ok": True,
        "path": out_path,
        "file": TOPOLOGIA_PNG,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "location": loc,
        "nearby_sections": len(nearby),
        "provider": provider_info,
        "errors": errors,
        "msg": "Mapa ubicacion carga nueva: %s (%.6f, %.6f)" % (label, lat, lon),
    }
    meta_path = os.path.join(img_dir, "topologia_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False, default=str)
        meta["meta_path"] = meta_path
    except Exception:
        pass
    print("[mapa]", meta["msg"], "→", out_path)
    return meta


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Genera topologia.png (mapa carga nueva)")
    ap.add_argument("--feeder", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    s = load_settings(feeder_id=args.feeder or None, synthesize=True)
    res = generate_location_map(s, force=True)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
