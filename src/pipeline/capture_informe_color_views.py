# -*- coding: utf-8 -*-
"""
Capturas CYMDIST del alimentador coloreado + leyenda para el informe.

Slots (sustituyen graficas matplotlib si existen):
  situacional_tension.png       — escenario sin carga nueva, coloreo VoltageLevel
  situacional_cargabilidad.png  — escenario sin carga nueva, coloreo LoadingLevel
  proyectado_tension.png        — con carga nueva conectada, VoltageLevel
  proyectado_cargabilidad.png   — con carga nueva conectada, LoadingLevel

Flujo por escenario:
  1) Conmuta SpotLoad §4 (desconecta / conecta)
  2) LoadFlow
  3) Activa EnableColorCoding + ColorCodingType
  4) ExportActiveView (CymPy) o captura GUI (PrintWindow)
  5) Compone leyenda ElectroDunas (plantilla) + vista del alimentador
"""
from __future__ import print_function
import json
import os
import shutil
import time
from datetime import datetime

from core.common import mkdir, load_json, require_cympy
from core.feeder_context import load_settings, output_path
from pipeline.generate_informe_charts import REQUIRED_LF_IMAGES

# Tipos GUI CYME (cympy.properties.CymeEnums._CymGUIEnum_GUIDisplayLayerType)
COLOR_VOLTAGE = "VoltageLevel"   # 38 — caida / nivel de tension (%)
COLOR_LOADING = "LoadingLevel"   # 37 — cargabilidad / nivel de carga (%)

# Leyendas estandar ElectroDunas (extraidas de la plantilla informe)
LEGEND_FILES = {
    "tension": "leyenda_tension.png",
    "cargabilidad": "leyenda_cargabilidad.png",
}

SLOT_JOBS = (
    ("situacional", "tension", COLOR_VOLTAGE, "situacional_tension.png"),
    ("situacional", "cargabilidad", COLOR_LOADING, "situacional_cargabilidad.png"),
    ("proyectado", "tension", COLOR_VOLTAGE, "proyectado_tension.png"),
    ("proyectado", "cargabilidad", COLOR_LOADING, "proyectado_cargabilidad.png"),
)


def _images_dir(settings):
    out_base = settings.get("output_dir") or os.path.join(
        "data", "output", "feeders", str(settings.get("feeder_id") or "feeder")
    )
    if not os.path.isabs(out_base):
        from core.common import p
        return p(*(out_base.replace("\\", "/").split("/") + ["informe_images"]))
    return os.path.join(out_base, "informe_images")


def _plantilla_legends_dir():
    from core.common import p
    return p("data", "output", "informe", "legends")


def ensure_standard_legends(force=False):
    """
    Copia leyendas de codificacion por color desde la plantilla Word
    (image2/image4 = tension/cargabilidad) a informe/legends/.
    """
    from core.common import p
    dest_dir = _plantilla_legends_dir()
    mkdir(dest_dir)
    plantilla = p("data", "output", "informe", "informe.docx")
    mapping = {
        "word/media/image2.png": os.path.join(dest_dir, LEGEND_FILES["tension"]),
        "word/media/image4.png": os.path.join(dest_dir, LEGEND_FILES["cargabilidad"]),
    }
    out = {"ok": True, "copied": [], "errors": []}
    if not os.path.isfile(plantilla):
        out["ok"] = False
        out["errors"].append("faltan plantilla: %s" % plantilla)
        return out
    need = [d for d in mapping.values() if force or not os.path.isfile(d)]
    if not need:
        out["skipped"] = True
        return out
    import zipfile
    try:
        with zipfile.ZipFile(plantilla, "r") as zf:
            for src, dst in mapping.items():
                if not force and os.path.isfile(dst):
                    continue
                try:
                    data = zf.read(src)
                    with open(dst, "wb") as f:
                        f.write(data)
                    out["copied"].append(dst)
                except Exception as ex:
                    out["errors"].append("%s: %s" % (src, ex))
        out["ok"] = not out["errors"]
    except Exception as ex:
        out["ok"] = False
        out["errors"].append(str(ex))
    return out


def _set_color_coding(cympy, color_type):
    """Activa codificacion por color del LoadFlow (VoltageLevel | LoadingLevel)."""
    sim = cympy.sim.LoadFlow()
    notes = []
    pairs = (
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding", True),
        (
            "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType",
            str(color_type),
        ),
    )
    for path, val in pairs:
        try:
            sim.SetValue(val, path)
            notes.append("%s=%s" % (path.split(".")[-1], val))
        except Exception as ex:
            notes.append("FAIL %s: %s" % (path.split(".")[-1], ex))
    # Refresco GUI si existe
    try:
        cympy.app.ActivateRefresh(True)
        notes.append("ActivateRefresh=True")
    except Exception:
        pass
    return notes


def _export_active_view(cympy, out_path):
    """Exporta la vista activa a PNG. Retorna (ok, error)."""
    mkdir(os.path.dirname(out_path))
    try:
        fmt = cympy.enums.ImageFormat.Png
        cympy.app.ExportActiveView(out_path, fmt)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 2000:
            return True, None
        return False, "ExportActiveView no produjo PNG util"
    except Exception as ex:
        return False, str(ex)


def _capture_gui_fallback(out_path):
    """Si ExportActiveView falla, captura Cyme.exe visible (PrintWindow)."""
    try:
        from pipeline.capture_study_views import capture_cyme_view
        res = capture_cyme_view(out_path, bring_to_front=True, settle_s=1.0)
        return bool(res.get("ok")), res.get("error")
    except Exception as ex:
        return False, str(ex)


def _compose_legend_and_feeder(legend_path, feeder_path, out_path, title=None):
    """
    Compone leyenda (arriba) + alimentador coloreado (abajo) en un solo PNG
    para el slot del informe (alimentador + significado de colores).
    """
    from PIL import Image, ImageDraw, ImageFont

    if not os.path.isfile(feeder_path):
        return False
    feeder = Image.open(feeder_path).convert("RGB")
    parts = [feeder]
    if legend_path and os.path.isfile(legend_path):
        legend = Image.open(legend_path).convert("RGB")
        # Escalar leyenda al ancho del alimentador (max 55% altura relativa)
        tw = feeder.width
        scale = float(tw) / float(max(legend.width, 1))
        nh = max(40, int(legend.height * scale))
        if nh > int(feeder.height * 0.55):
            nh = int(feeder.height * 0.55)
            scale = float(nh) / float(max(legend.height, 1))
            tw = max(120, int(legend.width * scale))
        legend = legend.resize((tw if tw <= feeder.width else feeder.width, nh), Image.LANCZOS)
        # Centrar leyenda en lienzo del ancho del feeder
        canvas_leg = Image.new("RGB", (feeder.width, legend.height + 16), (255, 255, 255))
        ox = max(0, (feeder.width - legend.width) // 2)
        canvas_leg.paste(legend, (ox, 8))
        parts = [canvas_leg, feeder]

    gap = 8
    total_h = sum(im.height for im in parts) + gap * (len(parts) - 1)
    if title:
        total_h += 28
    canvas = Image.new("RGB", (feeder.width, total_h), (255, 255, 255))
    y = 0
    if title:
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("segoeui.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        draw.text((8, 6), title, fill=(30, 30, 30), font=font)
        y = 28
    for i, im in enumerate(parts):
        canvas.paste(im, (0, y))
        y += im.height + (gap if i < len(parts) - 1 else 0)
    mkdir(os.path.dirname(out_path))
    canvas.save(out_path, "PNG", optimize=True)
    return os.path.isfile(out_path)


def _write_sidecar(png_path, meta):
    side = png_path + ".cymdist.json"
    meta = dict(meta or {})
    meta["source"] = "cymdist_color"
    meta["captured_at"] = datetime.now().isoformat(timespec="seconds")
    with open(side, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def is_cymdist_capture(png_path):
    """True si el PNG es captura CYMDIST (sidecar) o mas reciente que graficas tipicas."""
    if not png_path or not os.path.isfile(png_path):
        return False
    side = png_path + ".cymdist.json"
    if os.path.isfile(side):
        try:
            meta = json.load(open(side, encoding="utf-8"))
            return str(meta.get("source") or "").startswith("cymdist")
        except Exception:
            return True
    return False


def is_live_cymdist_view(png_path):
    """
    True solo si la imagen viene de CYMDIST vivo (ExportActiveView / GUI),
    no del render topologico de inventario, y el PNG es un unifilar real.
    """
    if not is_cymdist_capture(png_path):
        return False
    if not _is_schematic_png(png_path):
        return False
    side = png_path + ".cymdist.json"
    try:
        meta = json.load(open(side, encoding="utf-8"))
    except Exception:
        return False
    export = str(meta.get("export") or "").strip().lower()
    if export in ("topology_render", "inventory", "matplotlib"):
        return False
    if export in ("exportactiveview", "gui_capture", "com_capture", "cympy", ""):
        if not export:
            notes = meta.get("color_notes") or []
            if not notes and not meta.get("color_type"):
                return False
        return True
    return export not in ("topology_render",)


def _needs_cyme_python():
    """True si este intérprete no puede hablar con CYMDIST (COM 32-bit / CymPy)."""
    if os.environ.get("RECYM_CAPTURE_WORKER") == "1":
        return False
    try:
        import struct
        if struct.calcsize("P") * 8 != 32:
            return True
    except Exception:
        return True
    try:
        import comtypes  # noqa: F401
    except Exception:
        return True
    return False


def _capture_via_cyme_python(settings, scenarios, open_gui, force):
    """Delegar captura al Python 32-bit (.tools/python37-win32) vía job aislado."""
    from core.cympy_job import run_cympy_job

    s = settings or {}
    timeout = float(
        s.get("informe_capture_timeout_sec")
        or s.get("cympy_job_timeout_sec")
        or 600
    )
    payload = {
        "feeder_id": s.get("feeder_id") or s.get("active_feeder"),
        "network_id": s.get("network_id"),
        "study_path": s.get("study_path"),
        "database_mdb": s.get("database_mdb"),
        "database_connection_name": s.get("database_connection_name"),
        "output_dir": s.get("output_dir"),
        "cyme_root": s.get("cyme_root"),
        "scenarios": list(scenarios) if scenarios else None,
        "open_gui": bool(open_gui),
        "force": bool(force),
    }
    res = run_cympy_job(
        "capture_informe_color",
        payload,
        settings=s,
        timeout_sec=timeout,
    )
    if isinstance(res, dict):
        res.setdefault("via", "python37-win32")
    return res


def capture_informe_color_views(settings=None, scenarios=None, open_gui=True, force=False):
    """
    Genera los 4 PNG de coloreo CYMDIST para el informe.

    scenarios: None | ['situacional','proyectado'] | uno solo
    open_gui: abre Cyme visible (mejora ExportActiveView / fallback PrintWindow)

    Si el proceso actual es Python 64-bit (UI), delega al worker 32-bit.
    """
    s = dict(settings or load_settings())
    if _needs_cyme_python():
        return _capture_via_cyme_python(s, scenarios, open_gui, force)

    img_dir = _images_dir(s)
    mkdir(img_dir)
    ensure_standard_legends(force=False)

    want = scenarios
    if want is None:
        want = ("situacional", "proyectado")
    elif isinstance(want, str):
        want = (want,)
    want = tuple(x for x in want if x in ("situacional", "proyectado"))

    result = {
        "ok": False,
        "images_dir": img_dir,
        "generated": [],
        "errors": [],
        "skipped": [],
        "notes": [],
    }

    # Pausar GUI previa; run_load_flow reabre si keep_open
    if open_gui:
        try:
            from core.cymdist_com import pause_cymdist_for_cympy
            pause_cymdist_for_cympy(s)
        except Exception as ex:
            result["notes"].append("pause gui: %s" % ex)

    # Forzar sesion keep_open para poder capturar la GUI tras LF
    if open_gui:
        try:
            from pipeline.run_demand_allocation import load_session, save_session
            sess = load_session(s)
            sess["cymdist_keep_open"] = True
            sess["cymdist_keep_open_reason"] = "informe_color_capture"
            save_session(s, sess)
        except Exception as ex:
            result["notes"].append("keep_open: %s" % ex)

    cympy = None
    adapter = None
    net = str(s.get("network_id") or "")
    legend_dir = _plantilla_legends_dir()
    gui_opened = False

    for scen in want:
        # run_load_flow guarda loadflow_<scen>.json y conmuta SpotLoad
        try:
            from pipeline.run_load_flow import run_load_flow
            lf_res = run_load_flow(s, scenario=scen)
            if str(lf_res.get("status") or "") not in ("ok", "dry_run"):
                result["errors"].append(
                    "%s LF status=%s err=%s"
                    % (scen, lf_res.get("status"), lf_res.get("error"))
                )
                continue
            result["notes"].append(
                "%s LF ok engine=%s" % (scen, (lf_res.get("engine") or "?"))
            )
            gui_opened = bool(lf_res.get("cymdist_open"))
            # Tras LF: si no hay GUI, abrir CymPy para ExportActiveView
            if not gui_opened:
                try:
                    api = load_json("config/cympy_api_map.json")
                    if cympy is None:
                        cympy = require_cympy(s)
                    if adapter is None:
                        from core.cympy_adapter import CymPyAdapter
                        adapter = CymPyAdapter(cympy, api, s)
                    adapter.open_study(force_backup=False)
                except Exception as ex:
                    result["notes"].append("%s reopen: %s" % (scen, ex))
                    # Ultimo recurso: abrir GUI COM
                    try:
                        from core.cymdist_com import open_cymdist_gui
                        open_cymdist_gui(s, kill_existing=False, reason="informe_color")
                        time.sleep(2.0)
                        gui_opened = True
                    except Exception as ex2:
                        result["errors"].append("%s sin vista: %s" % (scen, ex2))
                        continue
        except Exception as ex:
            result["errors"].append("%s run_load_flow: %s" % (scen, ex))
            continue

        for scen_key, kind, color_type, fname in SLOT_JOBS:
            if scen_key != scen:
                continue
            out = os.path.join(img_dir, fname)
            # Conservar captura viva; forzar sobrescribe topology_render y todo
            if not force and is_live_cymdist_view(out):
                result["skipped"].append({"file": fname, "reason": "live_cymdist_view"})
                continue
            if not force and is_cymdist_capture(out):
                result["skipped"].append({"file": fname, "reason": "cymdist_capture_exists"})
                continue

            raw = os.path.join(img_dir, "_raw_" + fname)
            legend = os.path.join(
                legend_dir,
                LEGEND_FILES["tension" if kind == "tension" else "cargabilidad"],
            )
            title = (
                "CYMDIST · %s · coloreo por %s"
                % (
                    "estado situacional (sin carga nueva)"
                    if scen == "situacional"
                    else "estado proyectado (con carga nueva)",
                    "caida de tension (%)" if kind == "tension" else "cargabilidad (%)",
                )
            )

            color_notes = []
            export_ok = False
            export_err = None
            export_method = None

            if gui_opened:
                try:
                    export_ok, export_err = _try_com_color_and_capture(
                        s, color_type, raw
                    )
                    if export_ok:
                        export_method = "com_capture"
                except Exception as ex:
                    export_err = str(ex)

            if not export_ok:
                try:
                    if cympy is None:
                        cympy = require_cympy(s)
                    color_notes = _set_color_coding(cympy, color_type)
                    try:
                        cympy.sim.LoadFlow().Run([net] if net else None)
                    except Exception:
                        try:
                            cympy.sim.LoadFlow().Run()
                        except Exception:
                            pass
                    time.sleep(0.4)
                    export_ok, export_err = _export_active_view(cympy, raw)
                    if export_ok and not _is_schematic_png(raw):
                        export_ok = False
                        export_err = "ExportActiveView sin unifilar visible"
                    if export_ok:
                        export_method = "ExportActiveView"
                except Exception as ex:
                    export_err = str(ex)

            if not export_ok:
                # Abrir GUI, OpenStudy + coloreo + captura del unifilar
                try:
                    export_ok, export_err2 = _try_com_color_and_capture(
                        s, color_type, raw
                    )
                    if export_ok:
                        export_method = "com_capture"
                    if not export_ok:
                        export_ok, export_err2 = _capture_gui_fallback(raw)
                        if export_ok and not _is_schematic_png(raw):
                            export_ok = False
                            export_err2 = "gui_capture sin unifilar (panel Datos)"
                        if export_ok:
                            export_method = "gui_capture"
                    if not export_ok:
                        result["errors"].append(
                            "%s: export=%s fallback=%s"
                            % (fname, export_err, export_err2)
                        )
                        continue
                except Exception as ex:
                    result["errors"].append("%s: %s | %s" % (fname, export_err, ex))
                    continue

            # Defensa final: no publicar capturas de carcasa CYMDIST
            if not _is_schematic_png(raw if os.path.isfile(raw) else out):
                result["errors"].append(
                    "%s: rechazada (no es unifilar coloreado)" % fname
                )
                try:
                    if os.path.isfile(raw):
                        os.remove(raw)
                except Exception:
                    pass
                continue

            composed = _compose_legend_and_feeder(legend, raw, out, title=title)
            if not composed:
                shutil.copy2(raw, out)
            try:
                if os.path.isfile(raw):
                    os.remove(raw)
            except Exception:
                pass

            _write_sidecar(out, {
                "scenario": scen,
                "kind": kind,
                "color_type": color_type,
                "export": export_method or "gui_capture",
                "color_notes": color_notes,
                "title": title,
            })
            result["generated"].append({
                "file": fname,
                "path": out,
                "scenario": scen,
                "kind": kind,
                "color_type": color_type,
                "export": export_method,
                "bytes": os.path.getsize(out) if os.path.isfile(out) else 0,
            })

    present = [f for f in REQUIRED_LF_IMAGES if os.path.isfile(os.path.join(img_dir, f))]
    result["present"] = present
    result["missing"] = [f for f in REQUIRED_LF_IMAGES if f not in present]
    result["ok"] = len(result["missing"]) == 0 and not result["errors"]
    result["captured_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def _is_schematic_png(png_path):
    """
    Rechaza capturas de la carcasa CYMDIST (panel Datos / Mensajes)
    y acepta unifilares / mapas con trazos coloreados.
    """
    if not png_path or not os.path.isfile(png_path):
        return False
    try:
        from PIL import Image
        im = Image.open(png_path).convert("RGB")
        w, h = im.size
        if w < 400 or h < 280:
            return False
        # Muestreo bajo para clasificar
        small = im.resize((96, 64))
        pixels = list(small.getdata())
        n = float(len(pixels))
        # Blancos / grises UI
        whiteish = sum(1 for r, g, b in pixels if r > 245 and g > 245 and b > 245)
        grayish = sum(
            1 for r, g, b in pixels
            if abs(r - g) < 12 and abs(g - b) < 12 and 160 < r < 245
        )
        # Colores de codificacion ElectroDunas (naranja/azul/verde/amarillo/rojo)
        colored = sum(
            1 for r, g, b in pixels
            if (r > 180 and g < 160 and b < 80)          # naranja/rojo
            or (b > 150 and r < 120 and g < 160)         # azul
            or (g > 150 and r < 120 and b < 120)         # verde
            or (r > 200 and g > 180 and b < 80)          # amarillo
        )
        # Trazos finos del unifilar: cromaticos aunque ocupen poco %
        chromatic = sum(
            1 for r, g, b in pixels if max(r, g, b) - min(r, g, b) > 35
        )
        white_ratio = whiteish / n
        gray_ratio = grayish / n
        color_ratio = colored / n
        chroma_ratio = chromatic / n
        # Unifilar: algo de color de bandas + no es casi solo gris UI
        if color_ratio >= 0.02 and white_ratio < 0.95:
            return True
        if chroma_ratio >= 0.03 and white_ratio < 0.97 and gray_ratio < 0.55:
            return True
        # Alternativa: muchos pixeles no-blancos (mapa denso) y poco gris panel
        nonwhite = 1.0 - white_ratio
        if nonwhite >= 0.12 and gray_ratio < 0.50 and (color_ratio >= 0.01 or chroma_ratio >= 0.02):
            return True
        return False
    except Exception:
        return False


def _capture_best_cyme_view(out_path, settle_s=1.0):
    """
    Captura el unifilar: prueba ventana principal y los hijos grandes,
    elige el PNG que pase _is_schematic_png.
    """
    from pipeline.capture_study_views import cyme_hwnd, capture_hwnd_png
    import ctypes
    from ctypes import wintypes

    hwnd = cyme_hwnd()
    if not hwnd:
        return False, "Cyme.exe no visible"
    try:
        ctypes.windll.user32.ShowWindow(hwnd, 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(float(settle_s))

    candidates = [hwnd]
    try:
        user32 = ctypes.windll.user32
        EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        kids = []

        def _cb(h, _lp):
            if not user32.IsWindowVisible(h):
                return True
            rect = wintypes.RECT()
            user32.GetClientRect(h, ctypes.byref(rect))
            ww = int(rect.right - rect.left)
            hh = int(rect.bottom - rect.top)
            if ww >= 400 and hh >= 300:
                kids.append((ww * hh, h))
            return True

        user32.EnumChildWindows(hwnd, EnumChildProc(_cb), 0)
        kids.sort(reverse=True)
        candidates.extend([h for _, h in kids[:6]])
    except Exception:
        pass

    mkdir(os.path.dirname(out_path))
    best = None
    last_err = None
    for i, h in enumerate(candidates):
        tmp = out_path + ".__cand%d.png" % i
        try:
            ok = capture_hwnd_png(h, tmp)
            if not ok:
                last_err = "PrintWindow fallo hwnd=%s" % int(h)
                continue
            if _is_schematic_png(tmp):
                shutil.move(tmp, out_path)
                # limpia otros candidatos
                for j in range(len(candidates)):
                    p = out_path + ".__cand%d.png" % j
                    if os.path.isfile(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass
                return True, None
            if best is None or os.path.getsize(tmp) > os.path.getsize(best):
                if best and os.path.isfile(best):
                    try:
                        os.remove(best)
                    except Exception:
                        pass
                best = tmp
            else:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
        except Exception as ex:
            last_err = str(ex)

    # Ninguno paso el filtro esquematico
    if best and os.path.isfile(best):
        try:
            os.remove(best)
        except Exception:
            pass
    for j in range(12):
        p = out_path + ".__cand%d.png" % j
        if os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass
    return False, last_err or "captura sin unifilar visible (panel Datos/Mensajes)"


def _try_com_color_and_capture(settings, color_type, out_path):
    """
    Abre/usa Cyme COM, OpenStudy, activa coloreo LoadFlow y captura el unifilar.
    Retorna (ok, error).
    """
    try:
        from core.cymdist_com import _ensure_comtypes, open_cymdist_gui, cyme_is_running
        _ensure_comtypes(settings.get("cyme_root"))
        import comtypes.client

        if not cyme_is_running():
            opened = open_cymdist_gui(settings, kill_existing=False, reason="informe_color")
            if not opened.get("ok"):
                return False, opened.get("error") or "open_cymdist_gui fallo"
            time.sleep(2.0)

        try:
            app = comtypes.client.GetActiveObject("Cymdist.Application")
        except Exception:
            app = comtypes.client.CreateObject("Cymdist.Application")
            try:
                app.ShowWindow(1)
            except Exception:
                pass
            mdb = settings.get("database_mdb") or ""
            study = settings.get("study_path") or ""
            if mdb and study:
                try:
                    from core.cymdist_com import _access_version
                    app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
                except Exception:
                    try:
                        app.SelectUniqueDatabaseAccess(mdb, 0, 0)
                    except Exception:
                        pass
                try:
                    app.OpenStudy(study)
                    time.sleep(1.5)
                except Exception:
                    pass

        try:
            app.ShowWindow(1)
        except Exception:
            pass

        try:
            lf = comtypes.client.CreateObject("Cymdist.LoadFlow")
            for path, val in (
                ("ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding", True),
                (
                    "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType",
                    str(color_type),
                ),
            ):
                try:
                    lf.SetValue(val, path)
                except Exception:
                    pass
            try:
                lf.Run()
            except Exception:
                pass
        except Exception:
            pass

        time.sleep(1.2)
        ok, err = _capture_best_cyme_view(out_path, settle_s=0.8)
        if ok and not _is_schematic_png(out_path):
            return False, "PNG no parece unifilar coloreado"
        return ok, err
    except Exception as ex:
        return False, str(ex)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Capturas CYMDIST coloreo informe")
    ap.add_argument("--scenario", choices=("situacional", "proyectado", "both"), default="both")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    sc = None if args.scenario == "both" else args.scenario
    res = capture_informe_color_views(
        scenarios=sc, open_gui=not args.no_gui, force=args.force
    )
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    raise SystemExit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
