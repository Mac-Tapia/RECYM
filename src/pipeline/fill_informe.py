# -*- coding: utf-8 -*-
"""
Rellena automaticamente informe.docx + justificacion.xlsx con resultados LoadFlow.

Flujo:
  1) Copia plantilla limpia (data/output/informe) → doc/
  2) Exige ambos LoadFlow (situacional + proyectado) y meta OCR minima
  3) Genera graficas PNG desde JSON LF (o respeta override manual CYMDIST)
  4) Escribe metricas situacional/proyectado en Excel
  5) Sustituye valores clave en Word + reemplaza imagenes LF

Imagenes LF obligatorias (auto desde LoadFlow o captura CYMDIST):
  situacional_tension.png | situacional_cargabilidad.png
  proyectado_tension.png  | proyectado_cargabilidad.png

Opcionales: topologia.png | trafo_cargabilidad.png
"""
from __future__ import print_function
import json
import math
import os
import re
import shutil
import zipfile
from datetime import datetime
from xml.etree import ElementTree as ET

from openpyxl import load_workbook

from core.common import mkdir, p
from core.feeder_context import load_settings, output_path
from pipeline.assemble_informe import assemble_informe, informe_paths, TEMPLATE_DIR, DOC_DIR
from pipeline.generate_informe_charts import (
    REQUIRED_LF_IMAGES,
    generate_informe_charts,
)
from pipeline.extract_informe_meta_pdf import (
    load_informe_meta,
    meta_is_complete,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ET.register_namespace("w", W_NS)
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
ET.register_namespace("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing")
ET.register_namespace("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture")
ET.register_namespace("v", "urn:schemas-microsoft-com:vml")

# Plantilla EMAPICA → media a reemplazar si existen capturas nuevas
IMAGE_MAP = {
    "topologia.png": "word/media/image1.png",
    "situacional_tension.png": "word/media/image3.png",
    "situacional_cargabilidad.png": "word/media/image5.png",
    "proyectado_tension.png": "word/media/image7.png",
    "proyectado_cargabilidad.png": "word/media/image9.png",
    "trafo_cargabilidad.png": "word/media/image10.png",
}

LF_OK_STATUS = ("ok", "dry_run")


def _num(val, default=None):
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "")
    if s.upper().startswith("ERR"):
        return default
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return default


def _fmt(val, nd=2, comma=True):
    if val is None:
        return ""
    try:
        x = float(val)
    except Exception:
        return str(val)
    s = ("%." + str(nd) + "f") % x
    if comma:
        s = s.replace(".", ",")
    return s


def _sva(kw, kvar):
    if kw is None or kvar is None:
        return None
    return math.sqrt(kw * kw + kvar * kvar)


def _fp_pct(kw, kva):
    if not kva or kva == 0 or kw is None:
        return None
    return 100.0 * kw / kva


def _amps(kva, vll_kv):
    if not kva or not vll_kv or vll_kv <= 0:
        return None
    return kva / (math.sqrt(3.0) * vll_kv)


def metrics_from_lf(lf_data, settings=None):
    """Normaliza un loadflow_*.json a metricas de informe."""
    lf = lf_data or {}
    topo = lf.get("topo") or {}
    settings = settings or {}
    kw = _num(topo.get("KWTOT"))
    kvar = _num(topo.get("KVARTOT"))
    kw_loss = _num(topo.get("KWLOSS"))
    kvar_loss = _num(topo.get("KVARLOSS"))
    vll = _num(topo.get("VLL")) or _num(settings.get("voltage_ll_kv")) or 22.9
    vln = _num(topo.get("VLN"))
    if vln is None and vll:
        vln = vll / math.sqrt(3.0)
    vpu = _num(topo.get("Vpu"))
    vpua = _num(topo.get("VpuA"), vpu)
    vpub = _num(topo.get("VpuB"), vpu)
    vpuc = _num(topo.get("VpuC"), vpu)
    # Corregir Vpu absurdo (>1.2) usando VLN / (VLL/sqrt3)
    nom_vln = (vll / math.sqrt(3.0)) if vll else None
    if nom_vln and vln and (vpu is None or vpu > 1.2 or vpu < 0.5):
        vpu = vln / nom_vln
        vpua = vpua if (vpua and 0.5 <= vpua <= 1.2) else vpu
        vpub = vpub if (vpub and 0.5 <= vpub <= 1.2) else vpu
        vpuc = vpuc if (vpuc and 0.5 <= vpuc <= 1.2) else vpu
    kva = _sva(kw, kvar) if (kw is not None and kvar is not None) else None
    i_a = _num(topo.get("I")) or _amps(kva, vll)
    return {
        "status": lf.get("status"),
        "scenario": lf.get("scenario"),
        "feeder_id": lf.get("feeder_id") or settings.get("feeder_id"),
        "network_id": lf.get("network_id") or settings.get("network_id"),
        "engine": lf.get("engine"),
        "kw": kw,
        "kvar": kvar,
        "kva": kva,
        "fp_pct": _fp_pct(kw, kva),
        "kw_loss": kw_loss if kw_loss is not None else 0.0,
        "kvar_loss": kvar_loss if kvar_loss is not None else 0.0,
        "kva_loss": _sva(kw_loss or 0.0, kvar_loss or 0.0),
        "fp_loss_pct": _fp_pct(kw_loss or 0.0, _sva(kw_loss or 0.0, kvar_loss or 0.0)) if (kw_loss or kvar_loss) else 0.0,
        "vll": vll,
        "vln": vln,
        "vpu": vpu,
        "vpu_a": vpua,
        "vpu_b": vpub,
        "vpu_c": vpuc,
        "v_pct_a": (vpua * 100.0) if vpua is not None else None,
        "v_pct_b": (vpub * 100.0) if vpub is not None else None,
        "v_pct_c": (vpuc * 100.0) if vpuc is not None else None,
        "i_a": i_a,
        "source_node": lf.get("source_node"),
        "raw_topo": topo,
    }


def _read_json(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_scenarios(settings):
    paths = informe_paths(settings)
    sit = _read_json(paths["loadflow_situacional"])
    proy = _read_json(paths["loadflow_proyectado"])
    gen = _read_json(paths["loadflow_result"])
    # Fallback: un solo flujo general alimenta situacional
    if sit is None and gen and gen.get("status") in ("ok", "dry_run"):
        sit = dict(gen)
        sit["scenario"] = "situacional"
        sit["_fallback_from"] = "loadflow_result.json"
    if proy is None and gen and str(gen.get("scenario") or "").lower() == "proyectado":
        proy = dict(gen)
    return {
        "situacional": metrics_from_lf(sit, settings) if sit else None,
        "proyectado": metrics_from_lf(proy, settings) if proy else None,
        "raw_situacional": sit,
        "raw_proyectado": proy,
        "paths": paths,
    }


def _lf_status_ok(raw):
    if not raw:
        return False
    return str(raw.get("status") or "").lower() in LF_OK_STATUS


def _meta_cliente(settings):
    """Cabecera del informe: prioriza OCR (informe_meta.json), luego spot loads."""
    feeder = settings.get("feeder_id") or "PA217"
    meta = {
        "cliente": "",
        "ubicacion": settings.get("region") or "Electro Dunas",
        "solicitud": "Factibilidad y Punto de Diseño",
        "potencia_txt": "",
        "potencia_kw": None,
        "alimentador": feeder,
        "set": settings.get("substation") or "",
        "tension_kv": _num(settings.get("voltage_ll_kv"), 22.9),
        "transformador": settings.get("transformer") or "",
        "expediente": settings.get("expediente") or ("RECYM-%s" % feeder),
        "meta_source": "defaults",
    }
    ocr = load_informe_meta(settings) or {}
    if ocr:
        meta["meta_source"] = ocr.get("source") or "pdf"
        for key in (
            "cliente", "ubicacion", "solicitud", "potencia_txt", "alimentador",
            "set", "transformador", "expediente",
        ):
            val = ocr.get(key)
            if val is not None and str(val).strip() != "":
                meta[key] = val
        if ocr.get("potencia_kw") is not None:
            meta["potencia_kw"] = _num(ocr.get("potencia_kw"))
        if ocr.get("tension_kv") is not None:
            meta["tension_kv"] = _num(ocr.get("tension_kv"), meta["tension_kv"])
        if ocr.get("source_pdf"):
            meta["source_pdf"] = ocr.get("source_pdf")

    # Spot loads: complementan potencia / cliente solo si OCR no los trajo
    report = output_path(settings, "loads", "new_spot_loads_report.csv")
    if os.path.isfile(report):
        try:
            import csv
            rows = []
            with open(report, "r", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if str(r.get("dry_run") or "").lower() in ("1", "true", "yes"):
                        continue
                    if str(r.get("Estado") or "").upper() in ("DRY_RUN", "ERROR"):
                        continue
                    pk = _num(r.get("P_kW"))
                    if pk is not None:
                        rows.append((pk, r))
            if rows:
                total = sum(x[0] for x in rows)
                if meta.get("potencia_kw") is None:
                    meta["potencia_kw"] = total
                    meta["potencia_txt"] = "%sKW" % _fmt(total, 0, comma=False)
                if not (meta.get("cliente") or "").strip():
                    meta["cliente"] = "Nueva SpotLoad x%d — %s" % (len(rows), feeder)
                    last = rows[-1][1]
                    if last.get("NodeID"):
                        meta["cliente"] = "Carga en nodo %s (%s)" % (last.get("NodeID"), feeder)
        except Exception:
            pass

    if meta.get("potencia_kw") is not None and not (meta.get("potencia_txt") or "").strip():
        meta["potencia_txt"] = "%sKW" % _fmt(meta["potencia_kw"], 0, comma=False)
    if not (meta.get("potencia_txt") or "").strip():
        meta["potencia_txt"] = "—"
    if not (meta.get("alimentador") or "").strip():
        meta["alimentador"] = feeder
    return meta


def _images_dir(settings):
    out_base = settings.get("output_dir") or os.path.join(
        "data", "output", "feeders", str(settings.get("feeder_id") or "feeder")
    )
    if not os.path.isabs(out_base):
        return p(*(out_base.replace("\\", "/").split("/") + ["informe_images"]))
    return os.path.join(out_base, "informe_images")


def _check_delivery_gates(scenarios, meta, img_dir, charts_res=None, settings=None):
    """Valida requisitos de entrega rigurosa. Retorna (ready, missing)."""
    missing = []
    raw_sit = scenarios.get("raw_situacional")
    raw_proy = scenarios.get("raw_proyectado")
    if not scenarios.get("situacional") or not _lf_status_ok(raw_sit):
        missing.append("loadflow_situacional")
    if not scenarios.get("proyectado") or not _lf_status_ok(raw_proy):
        missing.append("loadflow_proyectado")
    # Meta debe existir en informe_meta.json (PDF OCR / UI §5), no solo spot-load
    ocr_meta = load_informe_meta(settings) if settings is not None else None
    if not meta_is_complete(ocr_meta):
        missing.append("informe_meta_ocr (cliente + potencia_kw via PDF §5)")
    for fname in REQUIRED_LF_IMAGES:
        if not os.path.isfile(os.path.join(img_dir, fname)):
            missing.append(fname)
    if charts_res and charts_res.get("errors"):
        for err in charts_res["errors"]:
            missing.append("chart_error:%s" % err)
    return (len(missing) == 0), missing


def _write_escenario_block(ws, m, mode):
    """Escribe bloque situacional (filas ~2-28) o proyectado (filas ~34-62)."""
    if not m:
        return []
    notes = []
    feeder = m.get("feeder_id") or ""
    if mode == "situacional":
        ws["A2"] = "ESCENARIO ACTUAL DEL ALIMENTADOR %s" % feeder
        # Punto / cabecera
        ws["C5"] = round(m["vpu"], 4) if m.get("vpu") is not None else None
        ws["D5"] = round(m["vll"], 2) if m.get("vll") is not None else None
        ws["E5"] = round(m["vln"], 2) if m.get("vln") is not None else None
        ws["F5"] = round(m["i_a"], 1) if m.get("i_a") is not None else None
        ws["G5"] = round(m["kva"], 2) if m.get("kva") is not None else None
        ws["H5"] = round(m["kw"], 2) if m.get("kw") is not None else None
        ws["I5"] = round(m["kvar"], 2) if m.get("kvar") is not None else None
        # Fuentes / produccion
        for row in (12, 14):
            ws["O%d" % row] = round(m["kw"], 2) if m.get("kw") is not None else None
            ws["P%d" % row] = round(m["kvar"], 2) if m.get("kvar") is not None else None
            ws["Q%d" % row] = round(m["kva"], 2) if m.get("kva") is not None else None
            ws["R%d" % row] = round(m["fp_pct"], 2) if m.get("fp_pct") is not None else None
        # Cargas approx = fuente - perdidas
        load_kw = (m["kw"] - (m.get("kw_loss") or 0)) if m.get("kw") is not None else None
        load_kvar = (m["kvar"] - (m.get("kvar_loss") or 0)) if m.get("kvar") is not None else None
        load_kva = _sva(load_kw, load_kvar) if load_kw is not None else None
        for row in (15, 16, 20):
            ws["O%d" % row] = round(load_kw, 2) if load_kw is not None else None
            ws["P%d" % row] = round(load_kvar, 2) if load_kvar is not None else None
            ws["Q%d" % row] = round(load_kva, 2) if load_kva is not None else None
            ws["R%d" % row] = round(_fp_pct(load_kw, load_kva), 2) if load_kva else None
        # Vpu fases (subtension peores)
        ws["L15"] = round(m["vpu_a"], 4) if m.get("vpu_a") is not None else None
        ws["L16"] = round(m["vpu_b"], 4) if m.get("vpu_b") is not None else None
        ws["L17"] = round(m["vpu_c"], 4) if m.get("vpu_c") is not None else None
        # Perdidas
        for row in (24, 28):
            ws["O%d" % row] = round(m.get("kw_loss") or 0.0, 2)
            ws["P%d" % row] = round(m.get("kvar_loss") or 0.0, 2)
            ws["Q%d" % row] = round(m.get("kva_loss") or 0.0, 2)
            ws["R%d" % row] = round(m.get("fp_loss_pct") or 0.0, 2)
        ws["C12"] = round(m.get("kw_loss") or 0.0, 2)
        ws["C16"] = round(m.get("kw_loss") or 0.0, 2)
        notes.append("situacional: kW=%s kvar=%s" % (m.get("kw"), m.get("kvar")))
    else:
        ws["B34"] = "ESCENARIO PROYECTADO DEL ALIMENTADOR %s" % feeder
        ws["C39"] = round(m["vpu"], 4) if m.get("vpu") is not None else None
        ws["D39"] = round(m["vll"], 2) if m.get("vll") is not None else None
        ws["E39"] = round(m["vln"], 2) if m.get("vln") is not None else None
        ws["F39"] = round(m["i_a"], 1) if m.get("i_a") is not None else None
        ws["G39"] = round(m["kva"], 2) if m.get("kva") is not None else None
        ws["H39"] = round(m["kw"], 2) if m.get("kw") is not None else None
        ws["I39"] = round(m["kvar"], 2) if m.get("kvar") is not None else None
        for row in (46, 48):
            ws["O%d" % row] = round(m["kw"], 2) if m.get("kw") is not None else None
            ws["P%d" % row] = round(m["kvar"], 2) if m.get("kvar") is not None else None
            ws["Q%d" % row] = round(m["kva"], 2) if m.get("kva") is not None else None
            ws["R%d" % row] = round(m["fp_pct"], 2) if m.get("fp_pct") is not None else None
        load_kw = (m["kw"] - (m.get("kw_loss") or 0)) if m.get("kw") is not None else None
        load_kvar = (m["kvar"] - (m.get("kvar_loss") or 0)) if m.get("kvar") is not None else None
        load_kva = _sva(load_kw, load_kvar) if load_kw is not None else None
        for row in (49, 50, 54):
            ws["O%d" % row] = round(load_kw, 2) if load_kw is not None else None
            ws["P%d" % row] = round(load_kvar, 2) if load_kvar is not None else None
            ws["Q%d" % row] = round(load_kva, 2) if load_kva is not None else None
            ws["R%d" % row] = round(_fp_pct(load_kw, load_kva), 2) if load_kva else None
        ws["L49"] = round(m["vpu_a"], 4) if m.get("vpu_a") is not None else None
        ws["L50"] = round(m["vpu_b"], 4) if m.get("vpu_b") is not None else None
        ws["L51"] = round(m["vpu_c"], 4) if m.get("vpu_c") is not None else None
        for row in (58, 62):
            ws["O%d" % row] = round(m.get("kw_loss") or 0.0, 2)
            ws["P%d" % row] = round(m.get("kvar_loss") or 0.0, 2)
            ws["Q%d" % row] = round(m.get("kva_loss") or 0.0, 2)
            ws["R%d" % row] = round(m.get("fp_loss_pct") or 0.0, 2)
        ws["C46"] = round(m.get("kw_loss") or 0.0, 2)
        ws["C50"] = round(m.get("kw_loss") or 0.0, 2)
        notes.append("proyectado: kW=%s kvar=%s" % (m.get("kw"), m.get("kvar")))
    return notes


def fill_excel(xlsx_path, scenarios, meta):
    wb = load_workbook(xlsx_path)
    notes = []
    if "Resultados de escenarios" in wb.sheetnames:
        ws = wb["Resultados de escenarios"]
        notes += _write_escenario_block(ws, scenarios.get("situacional"), "situacional")
        notes += _write_escenario_block(ws, scenarios.get("proyectado"), "proyectado")
    if "Informe" in wb.sheetnames:
        wi = wb["Informe"]
        wi["C4"] = meta.get("cliente")
        wi["C5"] = meta.get("ubicacion")
        wi["C6"] = meta.get("solicitud")
        if meta.get("potencia_txt"):
            wi["H6"] = meta["potencia_txt"]
        if meta.get("potencia_kw") is not None:
            wi["C7"] = meta["potencia_kw"]
        wi["H7"] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        wi["C8"] = meta.get("alimentador")
        if meta.get("set"):
            wi["H8"] = meta["set"]
        if meta.get("tension_kv") is not None:
            wi["C9"] = meta["tension_kv"]
        if meta.get("transformador"):
            wi["H9"] = meta["transformador"]
        wi["C10"] = meta.get("expediente")
        notes.append("cabecera Informe actualizada (%s)" % meta.get("alimentador"))
    wb.save(xlsx_path)
    return notes


def _merge_w_t(root):
    """Une w:t adyacentes del mismo parrafo para facilitar replace (in-place XML)."""
    for p in root.iter("{%s}p" % W_NS):
        texts = list(p.iter("{%s}t" % W_NS))
        if len(texts) < 2:
            continue
        # Concatenar todo el texto del parrafo en el primer w:t y vaciar el resto
        full = "".join((t.text or "") for t in texts)
        texts[0].text = full
        for t in texts[1:]:
            t.text = ""


def _replace_in_xml(root, replacements):
    """Aplica reemplazos exactos sobre w:t (tras merge)."""
    done = []
    for old, new in replacements:
        if old is None or new is None or str(old) == str(new):
            continue
        old_s, new_s = str(old), str(new)
        count = 0
        for t in root.iter("{%s}t" % W_NS):
            if t.text and old_s in t.text:
                n = t.text.count(old_s)
                t.text = t.text.replace(old_s, new_s)
                count += n
        if count:
            done.append({"old": old_s, "new": new_s, "count": count})
    return done


def _build_word_replacements(scenarios, meta):
    """Mapa plantilla EMAPICA → valores nuevos (siempre partiendo de plantilla limpia)."""
    reps = []
    # Etiquetas
    if meta.get("alimentador"):
        reps.append(("IC106", meta["alimentador"]))
    if meta.get("cliente"):
        reps.append(("MUNICIPAL DE AGUA POTABLE Y ALCANTARILLADO DE ICA S.A. - EMAPICA", meta["cliente"]))
        reps.append(("EMAPICA", meta["cliente"][:40]))
    if meta.get("potencia_kw") is not None:
        reps.append(("430 KW", "%s kW" % _fmt(meta["potencia_kw"], 0, comma=False)))
        reps.append(("430 kW", "%s kW" % _fmt(meta["potencia_kw"], 0, comma=False)))
        reps.append(("430KW", meta.get("potencia_txt") or ("%sKW" % _fmt(meta["potencia_kw"], 0, comma=False))))

    sit = scenarios.get("situacional") or {}
    proy = scenarios.get("proyectado") or {}

    # Situacional — potencia fuente (valores plantilla)
    if sit.get("kw") is not None:
        reps.append(("2791", _fmt(sit["kw"], 0, comma=False)))
    if sit.get("kvar") is not None:
        reps.append(("999", _fmt(sit["kvar"], 0, comma=False)))
    if sit.get("kva") is not None:
        reps.append(("2965", _fmt(sit["kva"], 0, comma=False)))
    if sit.get("fp_pct") is not None:
        reps.append(("94,18", _fmt(sit["fp_pct"], 2)))
        reps.append(("94.18", _fmt(sit["fp_pct"], 2, comma=False)))
    if sit.get("kw_loss") is not None:
        reps.append(("40.10", _fmt(sit["kw_loss"], 2, comma=False)))
        reps.append(("40,10", _fmt(sit["kw_loss"], 2)))
    if sit.get("kvar_loss") is not None:
        reps.append(("54.99", _fmt(sit["kvar_loss"], 2, comma=False)))
    if sit.get("kva_loss") is not None:
        reps.append(("68.06", _fmt(sit["kva_loss"], 2, comma=False)))
    if sit.get("v_pct_a") is not None:
        reps.append(("102.30%", _fmt(sit["v_pct_a"], 2, comma=False) + "%"))
        reps.append(("102.30", _fmt(sit["v_pct_a"], 2, comma=False)))
    if sit.get("v_pct_b") is not None:
        reps.append(("101.72%", _fmt(sit["v_pct_b"], 2, comma=False) + "%"))
        reps.append(("101.72", _fmt(sit["v_pct_b"], 2, comma=False)))
    if sit.get("v_pct_c") is not None:
        reps.append(("102.18%", _fmt(sit["v_pct_c"], 2, comma=False) + "%"))
        reps.append(("102.18", _fmt(sit["v_pct_c"], 2, comma=False)))

    # Proyectado
    if proy.get("kw") is not None:
        reps.append(("3182.00", _fmt(proy["kw"], 2, comma=False)))
        reps.append(("3,233.12", _fmt(proy["kw"], 2)))
        reps.append(("3233.12", _fmt(proy["kw"], 2, comma=False)))
    if proy.get("kvar") is not None:
        reps.append(("1101.38", _fmt(proy["kvar"], 2, comma=False)))
    if proy.get("kva") is not None:
        reps.append(("3367.22", _fmt(proy["kva"], 2, comma=False)))
    if proy.get("fp_pct") is not None:
        reps.append(("94.50", _fmt(proy["fp_pct"], 2, comma=False)))
        reps.append(("94,50", _fmt(proy["fp_pct"], 2)))
    if proy.get("kw_loss") is not None:
        reps.append(("49.86", _fmt(proy["kw_loss"], 2, comma=False)))
    if proy.get("v_pct_a") is not None:
        reps.append(("96.52%", _fmt(proy["v_pct_a"], 2, comma=False) + "%"))
        reps.append(("96.52", _fmt(proy["v_pct_a"], 2, comma=False)))
    if proy.get("v_pct_b") is not None:
        reps.append(("95.99%", _fmt(proy["v_pct_b"], 2, comma=False) + "%"))
        reps.append(("95.99", _fmt(proy["v_pct_b"], 2, comma=False)))
    if proy.get("v_pct_c") is not None:
        reps.append(("96.43%", _fmt(proy["v_pct_c"], 2, comma=False) + "%"))
        reps.append(("96.43", _fmt(proy["v_pct_c"], 2, comma=False)))

    # Punto de diseño proyectado (fila plantilla 0.97 / 430 kW)
    if proy:
        if proy.get("vpu") is not None:
            reps.append(("0.97", _fmt(proy["vpu"], 2, comma=False)))
        if proy.get("vll") is not None:
            reps.append(("9.7", _fmt(proy["vll"], 1, comma=False)))
        if proy.get("vln") is not None:
            reps.append(("5.6", _fmt(proy["vln"], 1, comma=False)))
        if proy.get("i_a") is not None and meta.get("potencia_kw"):
            # corriente del punto ~ demanda solicitada, no cabecera
            i_pd = _amps(_sva(meta["potencia_kw"], meta["potencia_kw"] * math.tan(math.acos(0.95))), proy.get("vll") or 22.9)
            if i_pd:
                reps.append(("27.1", _fmt(i_pd, 1, comma=False)))
        if meta.get("potencia_kw") is not None:
            pk = meta["potencia_kw"]
            qk = pk * math.tan(math.acos(min(0.999, max(0.01, 0.95))))
            kva = _sva(pk, qk)
            reps.append(("455", _fmt(kva, 0, comma=False)))
            # No reemplazar "430" suelto (aparece muchas veces en la plantilla)
            reps.append(("142", _fmt(qk, 0, comma=False)))

    return reps


def fill_word(docx_path, scenarios, meta, images_dir=None):
    tmp = docx_path + ".__fill_tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    mkdir(tmp)
    with zipfile.ZipFile(docx_path, "r") as zin:
        zin.extractall(tmp)

    xml_path = os.path.join(tmp, "word", "document.xml")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    _merge_w_t(root)
    reps = _build_word_replacements(scenarios, meta)
    done = _replace_in_xml(root, reps)
    tree.write(xml_path, encoding="UTF-8", xml_declaration=True)

    images_replaced = []
    if images_dir and os.path.isdir(images_dir):
        for src_name, dst_rel in IMAGE_MAP.items():
            src = os.path.join(images_dir, src_name)
            dst = os.path.join(tmp, dst_rel.replace("/", os.sep))
            if os.path.isfile(src) and os.path.isfile(dst):
                shutil.copy2(src, dst)
                images_replaced.append({"src": src, "dst": dst_rel})

    # Rezip
    out_tmp = docx_path + ".__new.docx"
    if os.path.isfile(out_tmp):
        os.remove(out_tmp)
    with zipfile.ZipFile(out_tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for folder, _, files in os.walk(tmp):
            for name in files:
                full = os.path.join(folder, name)
                rel = os.path.relpath(full, tmp).replace("\\", "/")
                zout.write(full, rel)
    shutil.move(out_tmp, docx_path)
    shutil.rmtree(tmp, ignore_errors=True)
    return {"replacements": done, "images_replaced": images_replaced}


def delivery_status(settings=None):
    """Estado de gates de entrega sin rellenar Word/Excel ni regenerar charts."""
    s = settings or load_settings()
    scenarios = _load_scenarios(s)
    meta = _meta_cliente(s)
    ocr = load_informe_meta(s) or {}
    img_dir = _images_dir(s)
    mkdir(img_dir)
    present = [f for f in REQUIRED_LF_IMAGES if os.path.isfile(os.path.join(img_dir, f))]
    missing_imgs = [f for f in REQUIRED_LF_IMAGES if f not in present]
    ready, missing = _check_delivery_gates(scenarios, meta, img_dir, charts_res=None, settings=s)
    return {
        "ok": True,
        "delivery_ready": ready,
        "missing": missing,
        "feeder_id": s.get("feeder_id"),
        "checks": {
            "loadflow_situacional": bool(scenarios.get("situacional")) and _lf_status_ok(scenarios.get("raw_situacional")),
            "loadflow_proyectado": bool(scenarios.get("proyectado")) and _lf_status_ok(scenarios.get("raw_proyectado")),
            "informe_meta_ocr": meta_is_complete(ocr),
            "lf_images": len(missing_imgs) == 0,
        },
        "meta": {
            "cliente": meta.get("cliente") or "",
            "potencia_kw": meta.get("potencia_kw"),
            "potencia_txt": meta.get("potencia_txt") or "",
            "alimentador": meta.get("alimentador") or "",
            "meta_source": meta.get("meta_source"),
            "complete_ocr": meta_is_complete(ocr),
        },
        "images_dir": img_dir,
        "images_present": present,
        "images_missing": missing_imgs,
        "required_lf_images": list(REQUIRED_LF_IMAGES),
        "scenarios": {
            "situacional": bool(scenarios.get("situacional")),
            "proyectado": bool(scenarios.get("proyectado")),
        },
    }


def fill_informe(settings=None, overwrite_copy=True, require_delivery=True):
    """
    Copia plantilla → doc/ y rellena Excel + Word con LoadFlow.

    require_delivery=True (default): exige ambos LF, meta OCR minima y 4 PNG LF.
    Si faltan, no toca doc/ y retorna ok=False + missing[].
    """
    s = settings or load_settings()
    scenarios = _load_scenarios(s)
    meta = _meta_cliente(s)
    paths = scenarios["paths"]
    img_dir = _images_dir(s)
    mkdir(img_dir)
    notes = []
    charts_res = None

    if scenarios.get("situacional") or scenarios.get("proyectado"):
        try:
            charts_res = generate_informe_charts(
                img_dir,
                {
                    "situacional": scenarios.get("situacional"),
                    "proyectado": scenarios.get("proyectado"),
                },
                paths=paths,
            )
            notes.append(
                "charts generated: %d skipped: %d"
                % (len(charts_res.get("generated") or []), len(charts_res.get("skipped") or []))
            )
        except Exception as ex:
            charts_res = {
                "ok": False,
                "errors": [str(ex)],
                "generated": [],
                "missing": list(REQUIRED_LF_IMAGES),
            }
            notes.append("charts error: %s" % ex)

    delivery_ready, missing = _check_delivery_gates(
        scenarios, meta, img_dir, charts_res, settings=s
    )

    metric_keys = ("kw", "kvar", "kva", "fp_pct", "kw_loss", "vpu", "v_pct_a", "v_pct_b", "v_pct_c", "i_a")
    scenarios_used = {
        "situacional": bool(scenarios["situacional"]),
        "proyectado": bool(scenarios["proyectado"]),
        "situacional_metrics": (
            {k: scenarios["situacional"].get(k) for k in metric_keys}
            if scenarios["situacional"] else None
        ),
        "proyectado_metrics": (
            {k: scenarios["proyectado"].get(k) for k in metric_keys}
            if scenarios["proyectado"] else None
        ),
    }

    if require_delivery and not delivery_ready:
        err = (
            "Informe incompleto para entrega. Falta: %s. "
            "Complete: PDF OCR en §5 (cliente+potencia), "
            "Flujo situacional, Flujo proyectado; las graficas LF se generan solas."
            % (", ".join(missing) if missing else "requisitos")
        )
        manifest = {
            "ok": False,
            "delivery_ready": False,
            "error": err,
            "missing": missing,
            "filled_at": datetime.now().isoformat(timespec="seconds"),
            "feeder_id": s.get("feeder_id"),
            "meta": meta,
            "meta_source": meta.get("meta_source"),
            "paths": paths,
            "images_dir": img_dir,
            "image_slots": IMAGE_MAP,
            "required_lf_images": list(REQUIRED_LF_IMAGES),
            "charts_generated": (charts_res or {}).get("generated") or [],
            "charts": charts_res,
            "scenarios_used": scenarios_used,
            "notes": notes,
            "aviso_imagenes": (
                "Graficas LF se generan desde loadflow_*.json. "
                "Override opcional: capturas CYMDIST en %s (mismos nombres)."
                % img_dir
            ),
        }
        man_path = os.path.join(paths["doc_dir"], "fill_manifest.json")
        mkdir(paths["doc_dir"])
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        manifest["fill_manifest"] = man_path
        print("[fill] INCOMPLETO:", err)
        return manifest

    # Solo si entrega lista: copiar plantilla y rellenar
    base = assemble_informe(s, overwrite=overwrite_copy)
    if not base.get("ok"):
        return base

    xnotes = fill_excel(paths["justificacion_doc"], scenarios, meta)
    notes.extend(xnotes)
    wres = fill_word(paths["informe_doc"], scenarios, meta, images_dir=img_dir)
    notes.append("word replacements: %d" % len(wres.get("replacements") or []))
    notes.append("images replaced: %d" % len(wres.get("images_replaced") or []))

    replaced_names = [
        os.path.basename(x.get("src") or "") for x in (wres.get("images_replaced") or [])
    ]
    lf_replaced = [n for n in REQUIRED_LF_IMAGES if n in replaced_names]

    manifest = {
        "ok": True,
        "delivery_ready": True,
        "missing": [],
        "filled_at": datetime.now().isoformat(timespec="seconds"),
        "feeder_id": s.get("feeder_id"),
        "meta": meta,
        "meta_source": meta.get("meta_source"),
        "paths": paths,
        "images_dir": img_dir,
        "image_slots": IMAGE_MAP,
        "required_lf_images": list(REQUIRED_LF_IMAGES),
        "charts_generated": (charts_res or {}).get("generated") or [],
        "charts": charts_res,
        "scenarios_used": scenarios_used,
        "excel_notes": xnotes,
        "word": wres,
        "lf_images_replaced": lf_replaced,
        "notes": notes,
        "aviso_imagenes": (
            "Graficas LF desde JSON (o override CYMDIST) en %s. "
            "topologia/trafo siguen opcionales."
            % img_dir
        ),
    }
    man_path = os.path.join(paths["doc_dir"], "fill_manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
    manifest["fill_manifest"] = man_path
    print("[fill] Excel+Word actualizados en", paths["doc_dir"])
    return manifest


def main():
    m = fill_informe()
    print(json.dumps(m, indent=2, ensure_ascii=False, default=str))
    if not m.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
