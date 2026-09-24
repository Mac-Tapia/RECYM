# -*- coding: utf-8 -*-
"""
Capturas CYMDIST del alimentador coloreado para el informe.

SOLO vistas nativas del modulo CYMDIST (LoadFlow + coloreo):
  situacional_tension.png       — sin carga nueva, VoltageLevel
  situacional_cargabilidad.png  — sin carga nueva, LoadingLevel
  proyectado_tension.png        — con carga nueva, VoltageLevel
  proyectado_cargabilidad.png   — con carga nueva, LoadingLevel

NO se inventan mapas matplotlib ni topology_render.
NO se componen overlays/titulos inventados sobre la captura.

Flujo por escenario:
  1) Conmuta SpotLoad §4 (desconecta / conecta)
  2) LoadFlow (debe converger)
  3) EnableColorCoding + ColorCodingType (VoltageLevel | LoadingLevel)
  4) Re-LF + ExportActiveView / captura GUI del unifilar coloreado
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
COLOR_TYPE_ENUM = {
    COLOR_VOLTAGE: 38,
    COLOR_LOADING: 37,
}

# Nombres exactos del combo CYMDIST (ES) — visibles in-process tras LF
LAYER_NAME_EXACT = {
    COLOR_VOLTAGE: "Colorear por nivel de tensión (%)",
    COLOR_LOADING: "Colorear por nivel de carga (%)",
}
LAYER_NAME_HINTS = {
    COLOR_VOLTAGE: (
        "nivel de tensión (%)",
        "nivel de tension (%)",
        "voltage level (%)",
    ),
    COLOR_LOADING: (
        "nivel de carga (%)",
        "loading level (%)",
    ),
}

# Bandas ElectroDunas (misma escala que leyenda_tension / leyenda_cargabilidad)
VOLTAGE_BANDS = (
    (0.0, 85.0, "blue"),
    (85.0, 90.0, "green"),
    (90.0, 95.0, "yellow"),
    (95.0, 105.0, "orange"),   # ~99.8 % V cabecera → naranja
    (105.0, 1e9, "red"),
)
LOADING_BANDS = (
    (0.0, 80.0, "blue"),       # tipico alimentador sano → azul
    (80.0, 90.0, "green"),
    (90.0, 95.0, "yellow"),
    (95.0, 105.0, "orange"),
    (105.0, 150.0, "red"),
    (150.0, 1e9, "darkred"),
)

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


def _band_for_value(value_pct, bands):
    try:
        v = float(value_pct)
    except Exception:
        return None
    for lo, hi, name in bands:
        if v > lo and v <= hi:
            return name
    return bands[-1][2] if bands else None


def _lf_metrics_for_color(settings, scenario):
    """
    Metricas para verificar el color esperado del mapa.
    Tension: VLN/VLL → % (ignora Vpu absurdo tipo 1,836).
    Cargabilidad: factor_carga sesion o proxy <80 % (azul).
    """
    from core.feeder_context import output_path

    out = {"v_pct": 99.84, "load_pct": 65.0, "scenario": scenario}
    path = output_path(settings, "demand", "loadflow_%s.json" % scenario)
    data = {}
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}
    topo = data.get("topo") or {}

    def _num(v):
        if v is None or v == "":
            return None
        try:
            return float(str(v).replace(",", ".").replace(" ", ""))
        except Exception:
            return None

    vpu = _num(topo.get("VpuA")) or _num(topo.get("Vpu"))
    vll = _num(topo.get("VLL")) or _num(settings.get("voltage_ll_kv")) or 22.9
    vln = _num(topo.get("VLN"))
    v_pct = None
    if vpu and 0.5 < vpu < 1.25:
        v_pct = vpu * 100.0
    elif vln and vll and vll > 0:
        v_pct = 100.0 * vln / (vll / (3.0 ** 0.5))
    if v_pct is None or v_pct < 50 or v_pct > 130:
        v_pct = 99.84
    out["v_pct"] = round(float(v_pct), 3)

    load_pct = 65.0
    try:
        from pipeline.run_demand_allocation import load_session
        sess = load_session(settings) or {}
        fc = _num(sess.get("factor_carga_pct")) or _num(sess.get("loading_pct"))
        if fc and 0 < fc < 200:
            load_pct = fc
    except Exception:
        pass
    # Si hay corriente de seccion vs rating en topo, usarla
    i_amp = _num(topo.get("I")) or _num(topo.get("Ia"))
    i_rate = _num(topo.get("Irate")) or _num(topo.get("Ampacity"))
    if i_amp and i_rate and i_rate > 0:
        load_pct = 100.0 * i_amp / i_rate
    out["load_pct"] = round(float(load_pct), 3)
    out["expected_voltage_band"] = _band_for_value(out["v_pct"], VOLTAGE_BANDS)
    out["expected_loading_band"] = _band_for_value(out["load_pct"], LOADING_BANDS)
    return out


def _expected_band(color_type, metrics):
    m = metrics or {}
    if str(color_type) == COLOR_VOLTAGE:
        return m.get("expected_voltage_band") or _band_for_value(m.get("v_pct", 99.84), VOLTAGE_BANDS)
    return m.get("expected_loading_band") or _band_for_value(m.get("load_pct", 65.0), LOADING_BANDS)


def _classify_rgb(r, g, b):
    """Clasifica pixel en banda ElectroDunas / UI."""
    if max(r, g, b) - min(r, g, b) < 28:
        if r > 245:
            return "white"
        if r > 180:
            return "lightgray"
        if r > 90:
            return "gray"
        return "dark"
    # Halo cian claro alrededor de trazos (no es banda ElectroDunas)
    if min(r, g, b) > 170 and b >= 200 and g >= 190:
        return "halo"
    # naranja CYME VoltageLevel OK (~224,160,128) y ElectroDunas (~255,153,0)
    if r > 170 and r >= g and (r - b) >= 40 and g < 210 and b < 170:
        return "orange"
    if r > 170 and g < 110 and b < 110 and r >= g and r >= b:
        return "red"
    if r > 120 and g < 60 and b < 60:
        return "darkred"
    if r > 200 and g > 180 and b < 100:
        return "yellow"
    # Azul cargabilidad ElectroDunas / CYME (<80 %)
    if b >= 140 and b >= r and b >= g and (b - r) >= 25:
        return "blue"
    # Verde fase / banda intermedia
    if g >= 100 and g >= r and g >= b and (g - min(r, b)) >= 25:
        return "green"
    return "other"


def _map_region_histogram(png_path):
    """
    Histograma de color del unifilar (ignora leyenda/titulo compuestos arriba).
    Retorna dict band→ratio sobre pixeles cromaticos de la zona mapa.
    """
    from PIL import Image

    im = Image.open(png_path).convert("RGB")
    w, h = im.size
    # Zona mapa: mitad inferior (leyendas ElectroDunas suelen ocupar el tercio superior)
    y0 = int(h * 0.48) if h > 500 else int(h * 0.10)
    region = im.crop((int(w * 0.04), y0, int(w * 0.96), int(h * 0.96)))
    small = region.resize((180, 120))
    counts = {}
    chroma = 0
    for r, g, b in small.getdata():
        band = _classify_rgb(r, g, b)
        if band in ("white", "lightgray", "gray", "dark", "halo"):
            continue
        chroma += 1
        counts[band] = counts.get(band, 0) + 1
    if chroma <= 0:
        return {"ok": False, "error": "sin pixeles cromaticos en mapa", "bands": {}, "chroma": 0}
    bands = {k: round(v / float(chroma), 4) for k, v in counts.items()}
    dominant = max(bands.items(), key=lambda kv: kv[1])[0] if bands else None
    return {"ok": True, "bands": bands, "chroma": chroma, "dominant": dominant}


def verify_capture_color_coding(png_path, color_type, metrics=None):
    """
    Verifica que el unifilar refleje VoltageLevel/LoadingLevel (no 'Colorear por fase').

    Criterios:
      - La banda esperada (naranja ~99.8 % V, azul <80 % carga, …) debe ser
        la dominante o al menos superar al verde de fase.
      - Si el verde domina y NO es la banda esperada → fallo tipico de coloreo por fase.
    """
    out = {
        "ok": False,
        "color_type": color_type,
        "expected_band": _expected_band(color_type, metrics),
        "metrics": metrics or {},
    }
    if not png_path or not os.path.isfile(png_path):
        out["error"] = "png ausente"
        return out
    try:
        hist = _map_region_histogram(png_path)
    except Exception as ex:
        out["error"] = "histograma: %s" % ex
        return out
    out["histogram"] = hist
    if not hist.get("ok"):
        out["error"] = hist.get("error") or "histograma vacio"
        return out

    expected = out["expected_band"]
    bands = hist.get("bands") or {}
    dominant = hist.get("dominant")
    exp_ratio = float(bands.get(expected) or 0.0) if expected else 0.0
    green_ratio = float(bands.get("green") or 0.0)
    out["expected_ratio"] = exp_ratio
    out["dominant"] = dominant

    # Fallo tipico: toolbar en 'Colorear por fase' → red uniforme verde
    if expected and expected != "green":
        if green_ratio >= 0.40 and exp_ratio <= green_ratio:
            out["error"] = (
                "mapa dominado por verde (%.0f%%) pero banda esperada=%s "
                "(%.0f%%) — tipico de 'Colorear por fase', no %s"
                % (100 * green_ratio, expected, 100 * exp_ratio, color_type)
            )
            return out
        if dominant == "green" and exp_ratio < 0.35:
            out["error"] = (
                "dominante=green con expected=%s ratio=%.0f%% — coloreo %s no aplicado"
                % (expected, 100 * exp_ratio, color_type)
            )
            return out

    # Debe haber senal clara de la banda esperada (dominante o >=35%)
    if expected:
        if dominant == expected and exp_ratio >= 0.25:
            out["ok"] = True
        elif exp_ratio >= 0.35 and exp_ratio > green_ratio:
            out["ok"] = True
        else:
            out["error"] = (
                "banda esperada %s solo %.1f%% del mapa (dominante=%s) "
                "— coloreo %s no representa la escala ElectroDunas"
                % (expected, 100 * exp_ratio, dominant, color_type)
            )
            return out

    out["ok"] = True
    out["note"] = "color OK expected=%s ratio=%.2f dominant=%s" % (
        expected, exp_ratio, dominant
    )
    return out


def _color_set_values(color_type):
    """
    Valores para SetValue ColorCodingType.
    SOLO strings: el int del enum GUIDisplayLayerType NO corresponde
    (p.ej. 38 → LLMaxFault, no VoltageLevel).
    """
    name = str(color_type)
    return [name]


def _persist_color_coding_in_study(settings, color_type):
    """
    Abre el estudio en CymPy, activa EnableColorCoding + ColorCodingType (string),
    guarda el .sxst/.zxst para que COM/GUI lo lean al reabrir.
    Retorna (ok, notes).
    """
    notes = []
    try:
        from core.common import require_cympy, load_json
        from core.cympy_adapter import CymPyAdapter
        from core.sim_params import try_repair_loadflow_defaults
        from core.cymdist_com import pause_cymdist_for_cympy
    except Exception as ex:
        return False, ["imports: %s" % ex]

    try:
        pause_cymdist_for_cympy(settings)
        notes.append("pause_gui")
    except Exception as ex:
        notes.append("pause: %s" % ex)

    try:
        cympy = require_cympy(settings)
        api = load_json("config/cympy_api_map.json")
        adapter = CymPyAdapter(cympy, api, settings)
        adapter.open_study(force_backup=False)
        notes.append("cympy open_study")
    except Exception as ex:
        return False, notes + ["open_study: %s" % ex]

    try:
        try_repair_loadflow_defaults(cympy)
        notes.append("repair_defaults")
    except Exception as ex:
        notes.append("repair: %s" % ex)

    enable_path = "ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding"
    type_path = (
        "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType"
    )
    sim = cympy.sim.LoadFlow()
    try:
        sim.SetValue(True, enable_path)
        notes.append("EnableColorCoding=True")
    except Exception as ex:
        notes.append("FAIL EnableColorCoding: %s" % ex)
        return False, notes
    try:
        sim.SetValue(str(color_type), type_path)
        notes.append("ColorCodingType=%s" % color_type)
    except Exception as ex:
        notes.append("FAIL ColorCodingType: %s" % ex)
        return False, notes
    try:
        got_e = sim.GetValue(enable_path)
        got_t = sim.GetValue(type_path)
        notes.append("readback enable=%s type=%s" % (got_e, got_t))
        if str(color_type) not in str(got_t):
            notes.append("AVISO readback type != %s" % color_type)
            return False, notes
    except Exception as ex:
        notes.append("readback FAIL: %s" % ex)

    study = str(settings.get("study_path") or "").strip()
    try:
        if study:
            cympy.study.Save(study, True, True, False, [])
        else:
            cympy.study.Save()
        notes.append("study.Save OK")
    except Exception as ex:
        notes.append("study.Save FAIL: %s" % ex)
        return False, notes
    return True, notes


def _run_python_in_cyme(app, script_text, settings=None):
    """
    Ejecuta un script Python DENTRO del proceso Cyme (RunPythonScript).
    Asi SelectColorCodingLayer tiene efecto (no-op desde fuera).
    Retorna (ok, notes, output_text).
    """
    notes = []
    out_path = None
    script_path = None
    try:
        from core.common import mkdir, p
        from comtypes.client import CreateObject
        from comtypes.gen import CYMDISTLib as CymeLib
        tmp_dir = p("data", "output", "_cyme_scripts")
        mkdir(tmp_dir)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = os.path.join(tmp_dir, "out_%s.txt" % stamp)
        script_path = os.path.join(tmp_dir, "run_%s.py" % stamp)
        # Envolver: script usuario + marcador de fin
        wrapped = (
            "# -*- coding: utf-8 -*-\n"
            "OUT = r'''%s'''\n"
            "def _log(msg):\n"
            "    with open(OUT, 'a', encoding='utf-8') as _f:\n"
            "        _f.write(str(msg) + '\\n')\n"
            "open(OUT, 'w', encoding='utf-8').write('start\\n')\n"
            "try:\n"
            "%s\n"
            "    _log('DONE')\n"
            "except Exception as _ex:\n"
            "    _log('FAIL:' + repr(_ex))\n"
            % (
                out_path.replace("\\", "\\\\"),
                "\n".join("    " + ln for ln in script_text.splitlines()),
            )
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapped)
        strings = CreateObject(CymeLib.Strings)
        ret = app.RunPythonScript(script_path, strings)
        notes.append("RunPythonScript ret=%s" % ret)
        time.sleep(0.4)
        text = ""
        if out_path and os.path.isfile(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                text = f.read()
        ok = "DONE" in text and "FAIL:" not in text
        return ok, notes, text
    except Exception as ex:
        return False, notes + ["RunPythonScript: %s" % ex], ""
    finally:
        for path in (script_path, out_path):
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


def _select_color_layer_inside_cyme(app, color_type, network_id=None):
    """
    In-process: EnableColorCoding + ColorCodingType + LF (crea capas %)
    + SelectColorCodingLayer con nombre ES exacto.
    """
    layer = LAYER_NAME_EXACT.get(str(color_type), str(color_type))
    net = str(network_id or "").strip()
    script = r"""
import cympy
import time
sim = cympy.sim.LoadFlow()
enable = "ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding"
ctype = "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType"
try:
    sim.SetValue(True, enable)
    sim.SetValue(COLOR_TYPE, ctype)
    _log("enable=" + str(sim.GetValue(enable)))
    _log("ctype=" + str(sim.GetValue(ctype)))
except Exception as ex:
    _log("set_warn=" + repr(ex))
# LF in-process crea las capas 'nivel de tensión/carga (%)'
try:
    if NETWORK_ID:
        sim.Run([NETWORK_ID])
    else:
        sim.Run()
    _log("LF_OK")
except Exception as ex:
    _log("LF_WARN:" + repr(ex))
layers = list(cympy.study.ListColorCodingLayers() or [])
_log("n_layers=" + str(len(layers)))
layer = LAYER_NAME
if layer not in layers:
    needle = "tensión (%)" if COLOR_TYPE == "VoltageLevel" else "carga (%)"
    hit = None
    for L in layers:
        low = L.lower()
        if "base" in low:
            continue
        if needle in low:
            hit = L
            break
    if not hit:
        _log("layers=" + " | ".join(layers))
        raise RuntimeError("capa no encontrada: " + layer)
    layer = hit
    _log("layer_fuzzy=" + layer)
cympy.study.SelectColorCodingLayer(layer)
_log("selected=" + layer)
try:
    cympy.app.ActivateRefresh(True)
except Exception:
    pass
time.sleep(0.3)
"""
    preamble = (
        "COLOR_TYPE = %r\n"
        "LAYER_NAME = %r\n"
        "NETWORK_ID = %r\n"
        % (str(color_type), layer, net)
    )
    ok, notes, text = _run_python_in_cyme(app, preamble + script)
    notes.append("inside_out=" + text.replace("\n", " | ")[:700])
    return ok, notes


def _set_color_coding(cympy, color_type):
    """Activa codificacion por color del LoadFlow (VoltageLevel | LoadingLevel)."""
    sim = cympy.sim.LoadFlow()
    notes = []
    enable_path = "ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding"
    type_path = (
        "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType"
    )
    name_path = (
        "ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.LayerName"
    )
    try:
        sim.SetValue(True, enable_path)
        notes.append("EnableColorCoding=True")
    except Exception as ex:
        notes.append("FAIL EnableColorCoding: %s" % ex)

    applied = None
    for val in _color_set_values(color_type):
        try:
            sim.SetValue(val, type_path)
            applied = val
            notes.append("ColorCodingType=%s" % val)
            break
        except Exception as ex:
            notes.append("FAIL ColorCodingType(%s): %s" % (val, ex))
    # LayerName descriptivo (ayuda al combo GUI)
    for lname in (str(color_type), "Colorear por %s" % color_type):
        try:
            sim.SetValue(lname, name_path)
            notes.append("LayerName=%s" % lname)
            break
        except Exception:
            continue

    # Readback
    try:
        got = sim.GetValue(type_path)
        notes.append("GetValue ColorCodingType=%s" % repr(got))
        got_s = str(got)
        ok_rb = (
            str(color_type) in got_s
            or str(COLOR_TYPE_ENUM.get(str(color_type), "")) == got_s
            or (applied is not None and str(applied) in got_s)
        )
        if not ok_rb:
            notes.append("AVISO readback no confirma %s" % color_type)
    except Exception as ex:
        notes.append("GetValue FAIL: %s" % ex)

    selected, sel_notes = _select_color_coding_layer(cympy, color_type)
    notes.extend(sel_notes)
    if selected:
        notes.append("layer_selected=True")
    else:
        notes.append("layer_selected=False")

    try:
        cympy.app.ActivateRefresh(True)
        notes.append("ActivateRefresh=True")
    except Exception:
        pass
    return notes


def _apply_color_and_rerun_lf_cympy(cympy, color_type, network_id=None):
    """
    Activa coloreo VoltageLevel/LoadingLevel, re-ejecuta LoadFlow y
    selecciona la capa en el combo 'Colorear por…'.
    """
    notes = list(_set_color_coding(cympy, color_type) or [])
    net = str(network_id or "").strip()
    ran = False
    try:
        lf = cympy.sim.LoadFlow()
        if net:
            lf.Run([net])
        else:
            lf.Run()
        ran = True
        notes.append("LoadFlow.Run color=%s net=%s" % (color_type, net or "*"))
    except Exception as ex:
        notes.append("LoadFlow.Run FAIL: %s" % ex)
        try:
            cympy.sim.LoadFlow().Run()
            ran = True
            notes.append("LoadFlow.Run (sin net) OK")
        except Exception as ex2:
            notes.append("LoadFlow.Run retry FAIL: %s" % ex2)

    # Tras LF las capas de resultado aparecen: re-seleccionar
    selected, sel_notes = _select_color_coding_layer(cympy, color_type)
    notes.extend(sel_notes)
    try:
        cympy.app.ActivateRefresh(True)
    except Exception:
        pass
    try:
        cympy.study.DisplayBestFit()
    except Exception:
        pass
    time.sleep(0.8)
    return ran, notes


def _select_color_coding_layer(cympy, color_type):
    """SelectColorCodingLayer externo (suele ser no-op fuera de Cyme)."""
    notes = []
    exact = LAYER_NAME_EXACT.get(str(color_type))
    hints = LAYER_NAME_HINTS.get(str(color_type), ())
    try:
        layers = list(cympy.study.ListColorCodingLayers() or [])
        notes.append("layers=%d" % len(layers))
    except Exception as ex:
        return False, notes + ["ListColorCodingLayers FAIL: %s" % ex]
    chosen = None
    if exact and exact in layers:
        chosen = exact
    else:
        for name in layers:
            low = str(name).lower()
            if "base" in low:
                continue
            if any(h in low for h in hints):
                chosen = name
                break
    if not chosen:
        return False, notes + ["sin capa %s" % color_type]
    try:
        cympy.study.SelectColorCodingLayer(str(chosen))
        notes.append("SelectColorCodingLayer=%s" % chosen)
        return True, notes
    except Exception as ex:
        return False, notes + ["Select FAIL: %s" % ex]


def _apply_color_and_rerun_lf_com(settings, color_type, app=None):
    """
    COM GUI abierta + LF + script in-process que selecciona
    'Colorear por nivel de tensión/carga (%)'.
    """
    notes = []
    try:
        from core.cymdist_com import (
            _ensure_comtypes,
            open_cymdist_gui,
            acquire_cymdist_app,
            sync_cymdist_binding,
            cyme_is_running,
        )
        _ensure_comtypes(settings.get("cyme_root"))
        import comtypes.client
    except Exception as ex:
        return False, ["comtypes: %s" % ex]

    if not cyme_is_running():
        opened = open_cymdist_gui(settings, kill_existing=False, reason="informe_color")
        notes.append("open_gui ok=%s" % opened.get("ok"))
        if not opened.get("ok"):
            return False, notes + [opened.get("error") or "open_gui fallo"]
        time.sleep(2.0)

    try:
        app, mode = acquire_cymdist_app(settings, show_window=True)
        notes.append("app mode=%s" % mode)
        try:
            sync_cymdist_binding(app, settings, save_before=False, register_db=True)
            notes.append("sync ok")
        except Exception as ex:
            notes.append("sync: %s" % ex)
    except Exception as ex:
        return False, notes + ["Application: %s" % ex]

    try:
        from pipeline.capture_study_views import cyme_hwnd
        for i in range(12):
            if cyme_hwnd():
                notes.append("hwnd ready")
                break
            time.sleep(0.4)
    except Exception:
        pass

    net = str(settings.get("network_id") or "").strip()
    # No re-lanzar LF COM aqui: run_load_flow ya convergio. Solo pintar capa.
    # (Un RunFromID extra abre paneles Datos/Mensajes y pierde el unifilar.)
    notes.append("skip_rerun_lf (usar resultado previo)")

    # Clave: seleccionar capa DENTRO de Cyme
    ok_sel, sel_notes = _select_color_layer_inside_cyme(app, color_type, network_id=net)
    notes.extend(sel_notes)
    notes.append("inside_select=%s" % bool(ok_sel))
    if not ok_sel:
        notes.append("AVISO: no se selecciono capa in-process")

    # Forzar ventana de mapa visible (LF COM a veces deja Cyme sin HWND)
    for sw in (1, 9, 3):  # normal / restore / maximize
        try:
            app.ShowWindow(int(sw))
        except Exception:
            pass
    try:
        from pipeline.capture_study_views import cyme_hwnd
        import ctypes
        hwnd = cyme_hwnd()
        if hwnd:
            ctypes.windll.user32.ShowWindow(int(hwnd), 9)
            ctypes.windll.user32.SetForegroundWindow(int(hwnd))
            notes.append("foreground hwnd=%s" % int(hwnd))
    except Exception as ex:
        notes.append("foreground: %s" % ex)

    time.sleep(0.6)
    return True, notes


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
    if "captured_at" not in meta:
        meta["captured_at"] = datetime.now().isoformat(timespec="seconds")
    with open(side, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def _write_capture_meta(png_path, meta):
    _write_sidecar(png_path, meta)


def _read_capture_meta(png_path):
    side = (png_path or "") + ".cymdist.json"
    if not os.path.isfile(side):
        return None
    try:
        with open(side, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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
    no del render topologico de inventario, el PNG es unifilar real, y
    el coloreo VoltageLevel/LoadingLevel fue verificado (o se puede
    re-verificar ahora contra las bandas ElectroDunas).
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
    color_type = str(meta.get("color_type") or "")
    if color_type and color_type not in ("VoltageLevel", "LoadingLevel"):
        return False
    if export not in ("exportactiveview", "gui_capture", "com_capture", "cympy", ""):
        return False
    if not export:
        notes = meta.get("color_notes") or []
        if not notes and not meta.get("color_type"):
            return False
    # Exigir verificacion de color (sidecar o recompute)
    if meta.get("color_verified") is True:
        return True
    try:
        metrics = meta.get("color_metrics") or None
        chk = verify_capture_color_coding(png_path, color_type or COLOR_VOLTAGE, metrics)
        return bool(chk.get("ok"))
    except Exception:
        return False


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

    # keep_open para capturar GUI tras LF (no matar Cyme al inicio:
    # RunPythonScript in-process necesita la misma sesion COM viva)
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
    gui_opened = False

    for scen in want:
        # run_load_flow guarda loadflow_<scen>.json y conmuta SpotLoad
        try:
            from pipeline.run_load_flow import run_load_flow
            lf_res = run_load_flow(s, scenario=scen)
            if str(lf_res.get("status") or "") not in ("ok", "dry_run"):
                result["errors"].append(
                    "%s LF status=%s err=%s — sin convergencia no se captura coloreo"
                    % (scen, lf_res.get("status"), lf_res.get("error"))
                )
                continue
            result["notes"].append(
                "%s LF OK engine=%s (alimentador convergido)"
                % (scen, (lf_res.get("engine") or "?"))
            )
            gui_opened = bool(lf_res.get("cymdist_open"))
            # Forzar HWND visible tras LF (COM a veces deja Cyme sin ventana)
            try:
                from core.cymdist_com import acquire_cymdist_app
                from pipeline.capture_study_views import cyme_hwnd
                import ctypes
                app_lf, _ = acquire_cymdist_app(s, show_window=True)
                try:
                    app_lf.ShowWindow(9)
                except Exception:
                    pass
                hwnd = cyme_hwnd()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(int(hwnd), 9)
                    ctypes.windll.user32.SetForegroundWindow(int(hwnd))
                    gui_opened = True
                    result["notes"].append("%s hwnd=%s" % (scen, int(hwnd)))
            except Exception as ex:
                result["notes"].append("%s show hwnd: %s" % (scen, ex))
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
            metrics = _lf_metrics_for_color(s, scen)
            # Conservar solo si es live Y el color del mapa verifica la escala
            if not force and is_live_cymdist_view(out):
                side = _read_capture_meta(out)
                if side and str(side.get("color_type") or "") == color_type:
                    if side.get("color_verified") is True or verify_capture_color_coding(
                        out, color_type, metrics
                    ).get("ok"):
                        result["skipped"].append({
                            "file": fname,
                            "reason": "live_cymdist_view_color_ok",
                            "color_type": color_type,
                            "expected_band": _expected_band(color_type, metrics),
                        })
                        continue
                # Sidecar/color incorrecto → recapturar
            if not force and is_cymdist_capture(out):
                side = _read_capture_meta(out)
                if (
                    side
                    and str(side.get("color_type") or "") == color_type
                    and side.get("color_verified") is True
                    and is_live_cymdist_view(out)
                ):
                    result["skipped"].append({
                        "file": fname,
                        "reason": "cymdist_capture_color_ok",
                        "color_type": color_type,
                    })
                    continue

            raw = os.path.join(img_dir, "_raw_" + fname)
            title = (
                "CYMDIST · %s · %s"
                % (
                    "situacional (sin carga nueva)"
                    if scen == "situacional"
                    else "proyectado (con carga nueva)",
                    color_type,
                )
            )

            color_notes = []
            export_ok = False
            export_err = None
            export_method = None
            lf_colored = False
            color_check = None

            # Hasta 2 intentos COM: SelectColorCodingLayer in-process → capturar → verificar
            for attempt in range(1, 3):
                color_notes = []
                export_ok = False
                export_err = None
                export_method = None
                lf_colored = False

                try:
                    # Si Cyme cayo, reabrir antes de capturar
                    from core.cymdist_com import cyme_is_running, open_cymdist_gui
                    if not cyme_is_running():
                        opened = open_cymdist_gui(
                            s, kill_existing=False, reason="informe_color_retry"
                        )
                        color_notes.append("reopen_gui=%s" % opened.get("ok"))
                        time.sleep(2.0)
                    export_ok, export_err, notes_cap = _try_com_color_and_capture(
                        s, color_type, raw
                    )
                    color_notes.extend(list(notes_cap or []))
                    if isinstance(color_notes, list):
                        lf_colored = any("Run" in str(n) for n in color_notes)
                    if export_ok:
                        export_method = "com_capture"
                except Exception as ex:
                    export_err = str(ex)

                if not export_ok:
                    if attempt >= 2:
                        result["errors"].append(
                            "%s: sin captura coloreada color=%s (%s)"
                            % (fname, color_type, export_err)
                        )
                    continue

                if not _is_schematic_png(raw):
                    export_ok = False
                    export_err = "no es unifilar"
                    if attempt >= 2:
                        result["errors"].append(
                            "%s: rechazada — no es unifilar coloreado (%s)"
                            % (fname, color_type)
                        )
                    continue

                color_check = verify_capture_color_coding(raw, color_type, metrics)
                color_notes.append(
                    "verify attempt=%s ok=%s expected=%s dominant=%s err=%s"
                    % (
                        attempt,
                        color_check.get("ok"),
                        color_check.get("expected_band"),
                        color_check.get("dominant"),
                        color_check.get("error"),
                    )
                )
                if color_check.get("ok"):
                    break
                export_ok = False
                time.sleep(0.8)

            if not export_ok or not color_check or not color_check.get("ok"):
                err_msg = (color_check or {}).get("error") or export_err or "color no verificado"
                result["errors"].append(
                    "%s: color INCORRECTO color_type=%s expected_band=%s — %s"
                    % (
                        fname,
                        color_type,
                        _expected_band(color_type, metrics),
                        err_msg,
                    )
                )
                try:
                    if os.path.isfile(raw):
                        os.remove(raw)
                except Exception:
                    pass
                continue

            # Publicar SOLO la captura CYMDIST cruda (sin componer leyendas/titulos inventados).
            mkdir(os.path.dirname(out))
            try:
                shutil.copy2(raw, out)
            except Exception as ex:
                result["errors"].append("%s: copy raw: %s" % (fname, ex))
                continue
            if not os.path.isfile(out):
                result["errors"].append("%s: no se escribio PNG final" % fname)
                continue

            meta = {
                "scenario": scen,
                "kind": kind,
                "color_type": color_type,
                "export": export_method,
                "color_notes": color_notes,
                "title": title,
                "source": "cymdist_color",
                "lf_converged": True,
                "lf_colored": bool(lf_colored) or bool(color_notes),
                "composed": False,
                "color_verified": True,
                "color_metrics": metrics,
                "color_check": {
                    "expected_band": color_check.get("expected_band"),
                    "dominant": color_check.get("dominant"),
                    "expected_ratio": color_check.get("expected_ratio"),
                    "histogram": (color_check.get("histogram") or {}).get("bands"),
                },
                "note": "Vista nativa CYMDIST; coloreo verificado vs escala ElectroDunas",
                "captured_at": datetime.now().isoformat(timespec="seconds"),
            }
            _write_capture_meta(out, meta)
            result["generated"].append({
                "file": fname,
                "path": out,
                "scenario": scen,
                "kind": kind,
                "color_type": color_type,
                "export": export_method,
                "expected_band": color_check.get("expected_band"),
                "dominant": color_check.get("dominant"),
            })
            result["notes"].append(
                "%s OK · %s · banda=%s · %s (verificado)"
                % (
                    fname,
                    color_type,
                    color_check.get("expected_band"),
                    export_method or "?",
                )
            )
            try:
                if os.path.isfile(raw) and raw != out:
                    os.remove(raw)
            except Exception:
                pass

    present = [f for f in REQUIRED_LF_IMAGES if os.path.isfile(os.path.join(img_dir, f))]
    result["present"] = present
    result["missing"] = [f for f in REQUIRED_LF_IMAGES if f not in present]
    # Exigir 4 PNG live con color verificado
    live_ok = [
        f for f in REQUIRED_LF_IMAGES
        if is_live_cymdist_view(os.path.join(img_dir, f))
    ]
    result["live_verified"] = live_ok
    result["ok"] = (
        len(result["missing"]) == 0
        and not result["errors"]
        and len(live_ok) == len(REQUIRED_LF_IMAGES)
    )
    result["captured_at"] = datetime.now().isoformat(timespec="seconds")
    return result


def _ui_select_colorear_por(color_type):
    """
    Fuerza el combo de la barra CYMDIST 'Colorear por…' via UI Automation.
    Necesario porque SelectColorCodingLayer no tiene efecto fuera del proceso Cyme.
    Retorna (ok, notes).
    """
    notes = []
    hints = LAYER_NAME_HINTS.get(str(color_type), ())
    try:
        import ctypes
        from ctypes import wintypes
        # UIAutomation via comtypes
        import comtypes
        import comtypes.client
        UIA = comtypes.client.GetModule("UIAutomationCore.dll")
        # IUIAutomation
        uia = comtypes.CoCreateInstance(
            UIA.CUIAutomation._reg_clsid_,
            interface=UIA.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
    except Exception as ex:
        return False, ["uia init: %s" % ex]

    try:
        from pipeline.capture_study_views import cyme_hwnd
        hwnd = cyme_hwnd()
    except Exception:
        hwnd = None
    if not hwnd:
        # fallback FindWindow
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, None)
            # scan for Cyme
            found = []
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

            def _enum(h, _lp):
                if not user32.IsWindowVisible(h):
                    return True
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(h, buf, 512)
                t = buf.value or ""
                if "CYME" in t.upper() or "CYMDIST" in t.upper() or "Cyme" in t:
                    found.append(h)
                return True

            user32.EnumWindows(EnumWindowsProc(_enum), 0)
            hwnd = found[0] if found else None
        except Exception as ex:
            notes.append("find hwnd: %s" % ex)
            hwnd = None
    if not hwnd:
        return False, notes + ["sin ventana Cyme"]

    try:
        root = uia.ElementFromHandle(int(hwnd))
        TreeScope_Descendants = 4
        ControlType_ComboBox = 50003
        ControlType_ListItem = 50007
        cond = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, ControlType_ComboBox)
        combos = root.FindAll(TreeScope_Descendants, cond)
        n_combos = int(combos.Length) if combos else 0
        notes.append("combos=%d" % n_combos)
        target_combo = None
        for i in range(n_combos):
            el = combos.GetElement(i)
            try:
                name = str(el.CurrentName or "")
            except Exception:
                name = ""
            try:
                val = ""
                try:
                    vp = el.GetCurrentPattern(UIA.UIA_ValuePatternId)
                    if vp:
                        val = str(vp.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue or "")
                except Exception:
                    pass
                text = (name + " " + val).lower()
                if "colorear" in text or "color by" in text:
                    target_combo = el
                    notes.append("combo hit name=%r val=%r" % (name, val))
                    break
            except Exception:
                continue
        if target_combo is None:
            # No adivinar combo[0]: expandir el combo equivocado tumba Cyme
            return False, notes + ["sin combo 'Colorear por…' (no fallback)"]

        # Expandir y elegir item
        try:
            ep = target_combo.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
            if ep:
                ep.QueryInterface(UIA.IUIAutomationExpandCollapsePattern).Expand()
                time.sleep(0.35)
                notes.append("combo Expand")
        except Exception as ex:
            notes.append("Expand: %s" % ex)

        # Buscar ListItems en toda la ventana (popup)
        cond_li = uia.CreatePropertyCondition(UIA.UIA_ControlTypePropertyId, ControlType_ListItem)
        items = root.FindAll(TreeScope_Descendants, cond_li)
        # Tambien desde desktop si el popup es top-level
        try:
            desktop = uia.GetRootElement()
            items2 = desktop.FindAll(TreeScope_Descendants, cond_li)
        except Exception:
            items2 = None

        candidates = []
        for collection in (items, items2):
            if not collection:
                continue
            for i in range(int(collection.Length)):
                el = collection.GetElement(i)
                try:
                    nm = str(el.CurrentName or "")
                except Exception:
                    continue
                if not nm:
                    continue
                low = nm.lower()
                if any(h in low for h in hints):
                    candidates.append((0, nm, el))
                elif "nivel de" in low and (
                    ("tensi" in low and color_type == COLOR_VOLTAGE)
                    or ("carga" in low and color_type == COLOR_LOADING)
                ):
                    candidates.append((1, nm, el))

        if not candidates:
            notes.append("sin ListItem matching hints=%s" % (hints[:2],))
            # colapsar
            try:
                ep = target_combo.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
                if ep:
                    ep.QueryInterface(UIA.IUIAutomationExpandCollapsePattern).Collapse()
            except Exception:
                pass
            return False, notes

        candidates.sort(key=lambda x: x[0])
        _prio, nm, el = candidates[0]
        try:
            inv = el.GetCurrentPattern(UIA.UIA_InvokePatternId)
            if inv:
                inv.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
                notes.append("Invoke ListItem=%s" % nm)
            else:
                sel = el.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                if sel:
                    sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
                    notes.append("Select ListItem=%s" % nm)
                else:
                    return False, notes + ["sin Invoke/Select en %s" % nm]
        except Exception as ex:
            return False, notes + ["activar item: %s" % ex]
        time.sleep(0.6)
        return True, notes
    except Exception as ex:
        return False, notes + ["uia select: %s" % ex]


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
    SelectColorCodingLayer in-process + captura inmediata del unifilar.
    Retorna (ok, error, notes).
    """
    notes = []
    try:
        from core.cymdist_com import cyme_is_running, open_cymdist_gui, acquire_cymdist_app
        from pipeline.capture_study_views import cyme_hwnd
        import ctypes

        if not cyme_is_running() or not cyme_hwnd():
            opened = open_cymdist_gui(settings, kill_existing=False, reason="informe_color")
            notes.append("open_gui=%s" % opened.get("ok"))
            time.sleep(2.0)
            try:
                app0, _ = acquire_cymdist_app(settings, show_window=True)
                app0.ShowWindow(9)
            except Exception:
                pass
            time.sleep(0.8)

        # Asegurar HWND visible ANTES del script in-process
        try:
            app0, _ = acquire_cymdist_app(settings, show_window=True)
            app0.ShowWindow(9)
            hwnd = cyme_hwnd()
            if hwnd:
                ctypes.windll.user32.ShowWindow(int(hwnd), 9)
                ctypes.windll.user32.SetForegroundWindow(int(hwnd))
                notes.append("pre_hwnd=%s" % int(hwnd))
        except Exception as ex:
            notes.append("pre_show: %s" % ex)

        ran, color_notes = _apply_color_and_rerun_lf_com(settings, color_type, app=None)
        notes.extend(color_notes or [])
        if not ran:
            notes.append("AVISO: select no confirmo — se intenta captura igual")

        # Captura inmediata (no revive: reopen pierde capas %)
        ok, err = _capture_best_cyme_view(out_path, settle_s=0.35)
        if (not ok) and cyme_hwnd():
            # Un reintento rapido si el primer PrintWindow fallo
            time.sleep(0.4)
            ok, err = _capture_best_cyme_view(out_path, settle_s=0.35)
        if ok and not _is_schematic_png(out_path):
            return False, "PNG no parece unifilar coloreado (%s)" % color_type, notes
        if ok:
            notes.append("captura unifilar OK color=%s" % color_type)
        return ok, err, notes
    except Exception as ex:
        return False, str(ex), notes


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
