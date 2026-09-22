# -*- coding: utf-8 -*-
"""
Rellena automaticamente informe.docx + justificacion.xlsx con resultados LoadFlow.

Flujo:
  1) Copia plantilla limpia (data/output/informe) → doc/
  2) Exige ambos LoadFlow (situacional + proyectado) y meta OCR minima
  3) Genera graficas PNG desde JSON LF (o respeta override manual CYMDIST)
  4) Escribe metricas situacional/proyectado en Excel
  5) Sustituye valores clave en Word + reemplaza imagenes LF
  6) Render final con Microsoft Word (campos, paginas, PDF)

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
    if not s:
        return default
    if s.upper().startswith("ERR"):
        return default
    # Placeholders CYMDIST / macros: $KWLOSS$, $I$, etc.
    if "$" in s:
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
    topo = dict(lf.get("topo") or {})
    settings = settings or {}
    # Seguridad: si JSON viejo aún trae KWTOT×3, corregir aquí también
    try:
        from core.cymdist_com import normalize_lf_topo_powers
        topo = normalize_lf_topo_powers(topo, settings)
    except Exception:
        pass
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
    # Pérdidas: None si placeholder/ausente (no fingir 0.0)
    kva_loss = _sva(kw_loss, kvar_loss) if (kw_loss is not None and kvar_loss is not None) else None
    if kva_loss is None and kw_loss is not None and kvar_loss is None:
        kva_loss = abs(kw_loss)
    elif kva_loss is None and kvar_loss is not None and kw_loss is None:
        kva_loss = abs(kvar_loss)
    fp_loss = None
    if kw_loss is not None and kva_loss:
        fp_loss = _fp_pct(kw_loss, kva_loss)
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
        "kw_loss": kw_loss,
        "kvar_loss": kvar_loss,
        "kva_loss": kva_loss,
        "fp_loss_pct": fp_loss,
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
        "power_scale_reason": topo.get("power_scale_reason"),
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
    feeder = settings.get("feeder_id") or settings.get("active_feeder") or ""
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
        "expediente": settings.get("expediente") or (("RECYM-%s" % feeder) if feeder else "RECYM"),
        "meta_source": "defaults",
    }
    ocr = load_informe_meta(settings) or {}
    if ocr:
        meta["meta_source"] = ocr.get("source") or "pdf"
        for key in (
            "cliente", "ubicacion", "solicitud", "potencia_txt", "alimentador",
            "set", "transformador", "expediente", "proyecto",
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
    return _complete_meta_fields(meta, settings)


def _complete_meta_fields(meta, settings=None):
    """Completa SET/trafo/ubicacion/etc. sin romper campos OCR ya llenos."""
    import re
    settings = settings or {}
    m = dict(meta or {})
    feeder = (m.get("alimentador") or settings.get("feeder_id") or "").strip().upper()
    if feeder:
        m["alimentador"] = feeder
    if not (m.get("solicitud") or "").strip():
        m["solicitud"] = "Factibilidad y Punto de Diseño"
    if m.get("tension_kv") is None:
        m["tension_kv"] = _num(settings.get("voltage_ll_kv"), 22.9)
    if not (m.get("set") or "").strip():
        prefix = re.match(r"^([A-Z]+)", feeder or "")
        geo = {
            "PA": "SET Paracas", "PI": "SET Pisco", "IC": "SET Ica",
            "CH": "SET Chincha", "NA": "SET Nazca",
        }
        m["set"] = geo.get((prefix.group(1) if prefix else ""), "SET %s" % (feeder or "MT"))
    if not (m.get("transformador") or "").strip():
        vll = _num(m.get("tension_kv"), 22.9)
        m["transformador"] = "Transformador %s · %.1f kV (inventario CYMDIST)" % (
            m.get("set") or "SET", vll,
        )
    if not (m.get("expediente") or "").strip():
        m["expediente"] = ("RECYM-%s" % feeder) if feeder else "RECYM"
    if not (m.get("ubicacion") or "").strip():
        m["ubicacion"] = settings.get("region") or "Área de concesión Electro Dunas"
    if m.get("potencia_kw") is not None and not (m.get("potencia_txt") or "").strip():
        m["potencia_txt"] = "%dKW" % int(round(float(m["potencia_kw"])))
    if not (m.get("sistema_electrico") or "").strip():
        m["sistema_electrico"] = "Electro Dunas"
    if not (m.get("codigo_se") or "").strip():
        m["codigo_se"] = feeder or "SE-MT"
    return m


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
    has_loss = m.get("kw_loss") is not None or m.get("kvar_loss") is not None

    def _round_or_none(val, nd=2):
        if val is None:
            return None
        return round(val, nd)

    if mode == "situacional":
        ws["A2"] = "ESCENARIO ACTUAL DEL ALIMENTADOR %s" % feeder
        # Punto / cabecera
        ws["C5"] = _round_or_none(m.get("vpu"), 4)
        ws["D5"] = _round_or_none(m.get("vll"), 2)
        ws["E5"] = _round_or_none(m.get("vln"), 2)
        ws["F5"] = _round_or_none(m.get("i_a"), 1)
        ws["G5"] = _round_or_none(m.get("kva"), 2)
        ws["H5"] = _round_or_none(m.get("kw"), 2)
        ws["I5"] = _round_or_none(m.get("kvar"), 2)
        # Fuentes / produccion
        for row in (12, 14):
            ws["O%d" % row] = _round_or_none(m.get("kw"), 2)
            ws["P%d" % row] = _round_or_none(m.get("kvar"), 2)
            ws["Q%d" % row] = _round_or_none(m.get("kva"), 2)
            ws["R%d" % row] = _round_or_none(m.get("fp_pct"), 2)
        # Cargas approx = fuente - perdidas (solo si hay perdidas validas)
        if has_loss and m.get("kw") is not None:
            load_kw = m["kw"] - (m.get("kw_loss") or 0)
            load_kvar = (m["kvar"] - (m.get("kvar_loss") or 0)) if m.get("kvar") is not None else None
            load_kva = _sva(load_kw, load_kvar) if load_kvar is not None else None
            for row in (15, 16, 20):
                ws["O%d" % row] = _round_or_none(load_kw, 2)
                ws["P%d" % row] = _round_or_none(load_kvar, 2)
                ws["Q%d" % row] = _round_or_none(load_kva, 2)
                ws["R%d" % row] = _round_or_none(_fp_pct(load_kw, load_kva), 2)
        # Vpu fases (subtension peores)
        ws["L15"] = _round_or_none(m.get("vpu_a"), 4)
        ws["L16"] = _round_or_none(m.get("vpu_b"), 4)
        ws["L17"] = _round_or_none(m.get("vpu_c"), 4)
        # Perdidas: solo si validas
        if has_loss:
            for row in (24, 28):
                ws["O%d" % row] = _round_or_none(m.get("kw_loss"), 2)
                ws["P%d" % row] = _round_or_none(m.get("kvar_loss"), 2)
                ws["Q%d" % row] = _round_or_none(m.get("kva_loss"), 2)
                ws["R%d" % row] = _round_or_none(m.get("fp_loss_pct"), 2)
            ws["C12"] = _round_or_none(m.get("kw_loss"), 2)
            ws["C16"] = _round_or_none(m.get("kw_loss"), 2)
        notes.append("situacional: kW=%s kvar=%s" % (m.get("kw"), m.get("kvar")))
    else:
        ws["B34"] = "ESCENARIO PROYECTADO DEL ALIMENTADOR %s" % feeder
        ws["C39"] = _round_or_none(m.get("vpu"), 4)
        ws["D39"] = _round_or_none(m.get("vll"), 2)
        ws["E39"] = _round_or_none(m.get("vln"), 2)
        ws["F39"] = _round_or_none(m.get("i_a"), 1)
        ws["G39"] = _round_or_none(m.get("kva"), 2)
        ws["H39"] = _round_or_none(m.get("kw"), 2)
        ws["I39"] = _round_or_none(m.get("kvar"), 2)
        for row in (46, 48):
            ws["O%d" % row] = _round_or_none(m.get("kw"), 2)
            ws["P%d" % row] = _round_or_none(m.get("kvar"), 2)
            ws["Q%d" % row] = _round_or_none(m.get("kva"), 2)
            ws["R%d" % row] = _round_or_none(m.get("fp_pct"), 2)
        if has_loss and m.get("kw") is not None:
            load_kw = m["kw"] - (m.get("kw_loss") or 0)
            load_kvar = (m["kvar"] - (m.get("kvar_loss") or 0)) if m.get("kvar") is not None else None
            load_kva = _sva(load_kw, load_kvar) if load_kvar is not None else None
            for row in (49, 50, 54):
                ws["O%d" % row] = _round_or_none(load_kw, 2)
                ws["P%d" % row] = _round_or_none(load_kvar, 2)
                ws["Q%d" % row] = _round_or_none(load_kva, 2)
                ws["R%d" % row] = _round_or_none(_fp_pct(load_kw, load_kva), 2)
        ws["L49"] = _round_or_none(m.get("vpu_a"), 4)
        ws["L50"] = _round_or_none(m.get("vpu_b"), 4)
        ws["L51"] = _round_or_none(m.get("vpu_c"), 4)
        if has_loss:
            for row in (58, 62):
                ws["O%d" % row] = _round_or_none(m.get("kw_loss"), 2)
                ws["P%d" % row] = _round_or_none(m.get("kvar_loss"), 2)
                ws["Q%d" % row] = _round_or_none(m.get("kva_loss"), 2)
                ws["R%d" % row] = _round_or_none(m.get("fp_loss_pct"), 2)
            ws["C46"] = _round_or_none(m.get("kw_loss"), 2)
            ws["C50"] = _round_or_none(m.get("kw_loss"), 2)
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
        wi["C4"] = meta.get("cliente") or ""
        wi["C5"] = meta.get("ubicacion") or ""
        wi["C6"] = meta.get("solicitud") or "Factibilidad y Punto de Diseño"
        wi["H6"] = meta.get("potencia_txt") or ""
        if meta.get("potencia_kw") is not None:
            wi["C7"] = meta["potencia_kw"]
        wi["H7"] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        wi["C8"] = meta.get("alimentador") or ""
        wi["H8"] = meta.get("set") or ""
        if meta.get("tension_kv") is not None:
            wi["C9"] = meta["tension_kv"]
        wi["H9"] = meta.get("transformador") or ""
        wi["C10"] = meta.get("expediente") or ""
        notes.append("cabecera Informe completa (%s)" % meta.get("alimentador"))
    wb.save(xlsx_path)
    return notes


def _cell_texts(tc):
    return list(tc.iter("{%s}t" % W_NS))


def _cell_text(tc):
    return "".join((t.text or "") for t in _cell_texts(tc))


def _set_cell_text(tc, value):
    """Escribe texto en una celda: primer w:t recibe el valor; el resto se vacia."""
    if value is None:
        return False
    texts = _cell_texts(tc)
    if not texts:
        # Crear un parrafo/run/t minimo si la celda esta vacia
        p = ET.SubElement(tc, "{%s}p" % W_NS)
        r = ET.SubElement(p, "{%s}r" % W_NS)
        t = ET.SubElement(r, "{%s}t" % W_NS)
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(value)
        return True
    texts[0].text = str(value)
    for t in texts[1:]:
        t.text = ""
    return True


def _tbl_rows(tbl):
    rows = []
    for tr in tbl.findall("{%s}tr" % W_NS):
        cells = list(tr.findall("{%s}tc" % W_NS))
        rows.append(cells)
    return rows


def _para_text(p):
    return "".join((t.text or "") for t in p.iter("{%s}t" % W_NS))


def _set_para_text(p, value):
    texts = list(p.iter("{%s}t" % W_NS))
    if not texts:
        return False
    texts[0].text = str(value)
    for t in texts[1:]:
        t.text = ""
    return True


def _replace_in_paragraph(p, old, new):
    """Replace exact substring in a single paragraph (merged runs)."""
    if old is None or new is None or str(old) == str(new):
        return 0
    texts = list(p.iter("{%s}t" % W_NS))
    if not texts:
        return 0
    full = "".join((t.text or "") for t in texts)
    if str(old) not in full:
        return 0
    n = full.count(str(old))
    full = full.replace(str(old), str(new))
    texts[0].text = full
    for t in texts[1:]:
        t.text = ""
    return n


def _merge_w_t(root):
    """Une w:t adyacentes del mismo parrafo para facilitar replace (in-place XML)."""
    for p in root.iter("{%s}p" % W_NS):
        texts = list(p.iter("{%s}t" % W_NS))
        if len(texts) < 2:
            continue
        full = "".join((t.text or "") for t in texts)
        texts[0].text = full
        for t in texts[1:]:
            t.text = ""


def _fmt_md_kw(val):
    """Formato tipo 2,791.00 / 10156.00 para tabla MD."""
    if val is None:
        return None
    try:
        x = float(val)
    except Exception:
        return str(val)
    # miles con coma, decimales con punto (estilo plantilla US)
    int_part = int(abs(x))
    dec = abs(x) - int_part
    s_int = "{:,}".format(int_part)
    s = "%s.%02d" % (s_int, int(round(dec * 100)))
    if x < 0:
        s = "-" + s
    return s


def _punto_diseno_metrics(proy, meta):
    """Metricas del punto de diseno (nueva carga), no de cabecera alimentador."""
    pk = _num(meta.get("potencia_kw"))
    fp = 0.95
    qk = None
    kva = None
    if pk is not None:
        qk = pk * math.tan(math.acos(min(0.999, max(0.01, fp))))
        kva = _sva(pk, qk)
    vll = (proy or {}).get("vll") or _num(meta.get("tension_kv")) or 22.9
    vln = (proy or {}).get("vln")
    if vln is None and vll:
        vln = vll / math.sqrt(3.0)
    # Vp.u. del punto: preferir proy; si absurdo, 1.0 nominal
    vpu = (proy or {}).get("vpu")
    if vpu is None or vpu > 1.2 or vpu < 0.5:
        vpu = 1.0
    i_a = _amps(kva, vll) if kva else None
    return {
        "vpu": vpu,
        "vll": vll,
        "vln": vln,
        "i_a": i_a,
        "kva": kva,
        "kw": pk,
        "kvar": qk,
    }


def _fill_source_table(tbl, m, include_losses=True):
    """Tabla potencia fuente + perdidas (4 filas x 5 cols)."""
    done = []
    if not m:
        return done
    rows = _tbl_rows(tbl)
    if len(rows) < 4:
        return done
    # fila potencia (idx 2): kW, kvar, kVA, FP
    pot = rows[2]
    if len(pot) >= 5:
        if m.get("kw") is not None and _set_cell_text(pot[1], _fmt(m["kw"], 0, comma=False)):
            done.append("fuente.kw")
        if m.get("kvar") is not None and _set_cell_text(pot[2], _fmt(m["kvar"], 0, comma=False) if abs(m["kvar"] - round(m["kvar"])) < 1e-6 else _fmt(m["kvar"], 2, comma=False)):
            done.append("fuente.kvar")
        if m.get("kva") is not None and _set_cell_text(pot[3], _fmt(m["kva"], 0, comma=False) if abs(m["kva"] - round(m["kva"])) < 1e-6 else _fmt(m["kva"], 2, comma=False)):
            done.append("fuente.kva")
        if m.get("fp_pct") is not None and _set_cell_text(pot[4], _fmt(m["fp_pct"], 2)):
            done.append("fuente.fp")
    # fila perdidas (idx 3): solo si validas
    if include_losses and (m.get("kw_loss") is not None or m.get("kvar_loss") is not None):
        loss = rows[3]
        if len(loss) >= 5:
            if m.get("kw_loss") is not None and _set_cell_text(loss[1], _fmt(m["kw_loss"], 2, comma=False)):
                done.append("loss.kw")
            if m.get("kvar_loss") is not None and _set_cell_text(loss[2], _fmt(m["kvar_loss"], 2, comma=False)):
                done.append("loss.kvar")
            if m.get("kva_loss") is not None and _set_cell_text(loss[3], _fmt(m["kva_loss"], 2, comma=False)):
                done.append("loss.kva")
            if m.get("fp_loss_pct") is not None and _set_cell_text(loss[4], _fmt(m["fp_loss_pct"], 2, comma=False)):
                done.append("loss.fp")
    return done


def _fill_voltage_drop_table(tbl, m):
    """Tabla caida A/B/C %."""
    done = []
    if not m:
        return done
    rows = _tbl_rows(tbl)
    mapping = {1: "v_pct_a", 2: "v_pct_b", 3: "v_pct_c"}
    for idx, key in mapping.items():
        if idx >= len(rows):
            break
        cells = rows[idx]
        if len(cells) < 2:
            continue
        val = m.get(key)
        if val is None:
            continue
        if _set_cell_text(cells[1], _fmt(val, 2, comma=False) + "%"):
            done.append(key)
    return done


def _fill_punto_diseno_table(tbl, pd):
    """Tabla 1 fila datos: Vp.u. kVLL kVLN i KVA kW kvar."""
    done = []
    if not pd:
        return done
    rows = _tbl_rows(tbl)
    if len(rows) < 2:
        return done
    cells = rows[1]
    vals = [
        _fmt(pd.get("vpu"), 2, comma=False) if pd.get("vpu") is not None else None,
        _fmt(pd.get("vll"), 1, comma=False) if pd.get("vll") is not None else None,
        _fmt(pd.get("vln"), 1, comma=False) if pd.get("vln") is not None else None,
        _fmt(pd.get("i_a"), 1, comma=False) if pd.get("i_a") is not None else None,
        _fmt(pd.get("kva"), 0, comma=False) if pd.get("kva") is not None else None,
        _fmt(pd.get("kw"), 0, comma=False) if pd.get("kw") is not None else None,
        _fmt(pd.get("kvar"), 0, comma=False) if pd.get("kvar") is not None else None,
    ]
    keys = ["vpu", "vll", "vln", "i_a", "kva", "kw", "kvar"]
    for i, (key, val) in enumerate(zip(keys, vals)):
        if val is None or i >= len(cells):
            continue
        if _set_cell_text(cells[i], val):
            done.append("pd.%s" % key)
    return done


def _fill_osm_feeder_table(tbl, meta):
    done = []
    feeder = (meta or {}).get("alimentador")
    if not feeder:
        return done
    rows = _tbl_rows(tbl)
    if len(rows) < 2:
        return done
    cells = rows[1]
    # col1 alimentador, col2 nombre SE, col3 codigo SE
    vals = [
        None,
        feeder,
        (meta or {}).get("sistema_electrico") or "Electro Dunas",
        (meta or {}).get("codigo_se") or feeder,
    ]
    for i, val in enumerate(vals):
        if val is None or i >= len(cells):
            continue
        if _set_cell_text(cells[i], val):
            done.append("osm.col%d" % i)
    return done


def _fill_perdidas_md_table(tbl, sit, proy, meta):
    """Tabla ESTADO ACTUAL / PROYECTADO con MD kW."""
    done = []
    rows = _tbl_rows(tbl)
    if len(rows) < 3:
        return done
    feeder = (meta or {}).get("alimentador") or ""
    # fila 1: situacional
    r1 = rows[1]
    if len(r1) >= 2:
        label = ("ESTADO ACTUAL %s" % feeder).strip()
        if feeder and _set_cell_text(r1[0], label):
            done.append("md.sit.label")
        if sit and sit.get("kw") is not None and _set_cell_text(r1[1], _fmt_md_kw(sit["kw"])):
            done.append("md.sit.kw")
        # Pérdidas Tec kWh-año / % solo si hay kw_loss valido
        if sit and sit.get("kw_loss") is not None and len(r1) >= 4:
            # kWh-año ≈ kw_loss * 8760 * factor; plantilla usa valor absoluto — actualizar % si posible
            if sit.get("kw") and sit["kw"] > 0:
                pct = 100.0 * sit["kw_loss"] / sit["kw"]
                if len(r1) >= 5 and _set_cell_text(r1[4], _fmt(pct, 2, comma=False) + "%"):
                    done.append("md.sit.pct")
    # fila 2: proyectado
    r2 = rows[2]
    if len(r2) >= 2:
        label = ("ESTADO PRYECTADO %s" % feeder).strip()
        if feeder and _set_cell_text(r2[0], label):
            done.append("md.proy.label")
        if proy and proy.get("kw") is not None and _set_cell_text(r2[1], _fmt_md_kw(proy["kw"])):
            done.append("md.proy.kw")
        if proy and proy.get("kw_loss") is not None and proy.get("kw") and proy["kw"] > 0 and len(r2) >= 5:
            pct = 100.0 * proy["kw_loss"] / proy["kw"]
            if _set_cell_text(r2[4], _fmt(pct, 2, comma=False) + "%"):
                done.append("md.proy.pct")
    return done


def _fill_word_tables(root, scenarios, meta):
    """Rellena los 7 cuadros de la plantilla EMAPICA por indice."""
    tables = list(root.iter("{%s}tbl" % W_NS))
    sit = scenarios.get("situacional")
    proy = scenarios.get("proyectado")
    report = {"n_tables": len(tables), "filled": [], "cells": []}

    fillers = [
        ("situacional_fuente", lambda t: _fill_source_table(t, sit)),
        ("situacional_caida", lambda t: _fill_voltage_drop_table(t, sit)),
        ("proyectado_fuente", lambda t: _fill_source_table(t, proy)),
        ("punto_diseno", lambda t: _fill_punto_diseno_table(t, _punto_diseno_metrics(proy, meta))),
        ("proyectado_caida", lambda t: _fill_voltage_drop_table(t, proy)),
        ("osm_alimentador", lambda t: _fill_osm_feeder_table(t, meta)),
        ("perdidas_md", lambda t: _fill_perdidas_md_table(t, sit, proy, meta)),
    ]
    for i, (name, fn) in enumerate(fillers):
        if i >= len(tables):
            break
        cells = fn(tables[i])
        if cells:
            report["filled"].append(name)
            report["cells"].extend(["%s:%s" % (name, c) for c in cells])
    return report


def _build_header_replacements(meta, scenarios=None):
    """Reemplazos que respetan la estructura de la plantilla base (frases largas)."""
    reps = []
    cliente = (meta or {}).get("cliente") or ""
    alimentador = (meta or {}).get("alimentador") or ""
    ubic = (meta or {}).get("ubicacion") or ""
    pot_kw = _num((meta or {}).get("potencia_kw"))
    pot_txt = (meta or {}).get("potencia_txt") or ""
    expediente = (meta or {}).get("expediente") or ""
    set_name = (meta or {}).get("set") or ""
    trafo = (meta or {}).get("transformador") or ""
    proyecto = (meta or {}).get("proyecto") or ""
    if pot_kw is not None and not pot_txt:
        pot_txt = "%sKW" % _fmt(pot_kw, 0, comma=False)
    pot_display = ("%s kW" % _fmt(pot_kw, 0, comma=False)) if pot_kw is not None else (pot_txt or "")

    # Fecha cabecera
    meses = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    )
    now = datetime.now()
    fecha_txt = "Ica, %d de %s de %d" % (now.day, meses[now.month - 1], now.year)
    reps.append(("Ica, 14 de agosto de 2026", fecha_txt))

    # Frases LARGAS primero (antes de IC106 / 430 kW / EMAPICA sueltos)
    if cliente and pot_display:
        label = "Carga-%s-%s" % ((proyecto or cliente)[:40], pot_display)
        old_carga = "Carga-Bomba de Agua Residual-juan Santa-430 kW- Cod IGEA-580224223"
        # La plantilla a veces duplica el rótulo en el mismo párrafo
        reps.append((old_carga + old_carga, label))
        reps.append((old_carga, label))
    if proyecto:
        reps.append(("Bomba de agua residual - Juan Santa", proyecto))
        reps.append(("Bomba de Agua Residual-juan Santa", proyecto))
    if cliente and alimentador and pot_display:
        concl1 = (
            "La solicitud de factibilidad y asignación de punto de diseño presentada por el predio %s, "
            "para una demanda de %s, se encuentra dentro del área de concesión de la empresa distribuidora."
        ) % (cliente, pot_display)
        concl2 = (
            "Asimismo, se evaluó el estado actual (sin proyecto) y proyectado (con proyecto) de cargabilidad "
            "y calidad de producto del alimentador %s y de la %s, determinándose que cuentan con condiciones "
            "operativas favorables para la incorporación de la nueva carga solicitada. Los resultados del "
            "flujo de carga evidencian capacidad suficiente para atender la demanda requerida y mantienen "
            "niveles de tensión dentro de los rangos establecidos por la normativa vigente."
        ) % (alimentador, set_name or "SET asociada")
        concl3 = (
            "En consecuencia, para la atención de la demanda requerida por el predio %s, se recomienda "
            "asignar el punto de diseño en el alimentador %s%s. Asimismo, se verifica que tanto el "
            "alimentador como el transformador de potencia de la %s cuentan con capacidad disponible "
            "para el suministro solicitado, manteniéndose los niveles de tensión dentro de los límites "
            "permisibles y sin afectar la calidad de producto ni las condiciones operativas de la red eléctrica."
        ) % (
            cliente,
            alimentador,
            (" — proyecto «%s»" % proyecto) if proyecto else "",
            set_name or "SET",
        )
        # Plantilla base trae un párrafo de rechazo (IC107): puente breve (no duplicar concl2)
        reps.append((
            "De acuerdo con los análisis de cargabilidad y calidad de producto realizados, no es posible asignar el punto de diseño en el alimentador IC107, debido a que este presenta niveles de cargabilidad cercanos a su capacidad máxima de operación y condiciones de caída de tensión próximas a los límites permisibles establecidos por la normativa vigente",
            (
                "De acuerdo con los análisis de cargabilidad y calidad de producto realizados sobre el alimentador %s "
                "(estados situacional y proyectado), se verifica que la red mantiene niveles de tensión y "
                "cargabilidad dentro de los parámetros operativos permitidos para la demanda solicitada."
            ) % alimentador,
        ))
        reps.append((
            "La solicitud de factibilidad y asignación de punto de diseño presentada por el predio MUNICIPAL DE AGUA POTABLE Y ALCANTARILLADO DE ICA S.A. - EMAPICA, para una demanda de 430 kW, se encuentra dentro del área de concesión de la empresa distribuidora.",
            concl1,
        ))
        reps.append((
            "para una demanda de 430 kW, se encuentra dentro del área de concesión de la empresa distribuidora.",
            "para una demanda de %s, se encuentra dentro del área de concesión de la empresa distribuidora." % pot_display,
        ))
        reps.append((
            "Asimismo, se evaluó el estado actual de cargabilidad y calidad de producto del alimentador IC106 y del transformador de potencia de la SET Ica, determinándose que ambos cuentan con condiciones operativas favorables para la incorporación de la nueva carga solicitada. Los resultados obtenidos evidencian que el alimentador IC106 dispone de capacidad suficiente para atender la demanda requerida y mantiene niveles de tensión dentro de los rangos establecidos por la normativa vigente. De igual manera, el transformador de potencia de la SET Ica presenta disponibilidad de capacidad, garantizando una operación segura y confiable del sistema.",
            concl2,
        ))
        reps.append((
            "En consecuencia, para la atención de la demanda requerida por el predio MUNICIPAL DE AGUA POTABLE Y ALCANTARILLADO DE ICA S.A. - EMAPICA, se recomienda asignar el punto de diseño en la estructura de media tensión NMT N.° COD IGEA: 580224223. Asimismo, se verifica que tanto el alimentador IC106 como el transformador de potencia de la SET Ica cuentan con capacidad disponible para el suministro solicitado, manteniéndose los niveles de tensión dentro de los límites permisibles y sin afectar la calidad de producto ni las condiciones operativas de la red eléctrica",
            concl3,
        ))

    if alimentador:
        reps.append(("IC106", alimentador))
        reps.append(("IC107", alimentador))
    if cliente:
        reps.append((
            "MUNICIPAL DE AGUA POTABLE Y ALCANTARILLADO DE ICA S.A. - EMAPICA",
            cliente,
        ))
        reps.append((
            "PREDIO MUNICIPAL DE AGUA POTABLE Y ALCANTARILLADO DE ICA S.A. - EMAPICA",
            cliente,
        ))
        reps.append(("EMAPICA", cliente[:80]))
    if pot_display:
        reps.append(("430 KW", pot_display))
        reps.append(("430 kW", pot_display))
        if pot_txt:
            reps.append(("430KW", pot_txt))
        reps.append((
            "El interesado solicita Factibilidad y Punto de Diseño 430 KW.",
            "El interesado solicita Factibilidad y Punto de Diseño %s." % pot_display,
        ))
        reps.append((
            "El interesado solicita Factibilidad y Punto de Diseño 430 kW.",
            "El interesado solicita Factibilidad y Punto de Diseño %s." % pot_display,
        ))
    if expediente:
        reps.append(("EXP-2026-000434", expediente))
    if set_name:
        reps.append(("SET ICA", set_name))
        reps.append(("SET Ica", set_name))
    if trafo:
        reps.append((
            "El transformador de la SET ICA tiene las siguientes características 50/30/30 MVA.",
            "El transformador de la %s tiene las siguientes características: %s." % (set_name or "SET", trafo),
        ))
        reps.append(("50/30/30 MVA", trafo))
    if alimentador:
        reps.append((
            "El interesado se encuentra próximo al alimentador IC106.",
            "El interesado se encuentra próximo al alimentador %s." % alimentador,
        ))
        reps.append((
            "Se ha verificado que el interesado se encuentra dentro de área de la zona de influencia del alimentador IC106",
            "Se ha verificado que el interesado se encuentra dentro del área de influencia del alimentador %s%s." % (
                alimentador,
                (" (%s)" % ubic) if ubic else "",
            ),
        ))
    if ubic:
        reps.append((
            "distrito de Parcona, provincia ICA del departamento de ICA",
            ubic,
        ))

    return reps


def _fill_word_headers(root, meta, scenarios=None):
    """Actualiza ASUNTO / ANTECEDENTES / CONCLUSIONES con meta (estructura plantilla)."""
    _merge_w_t(root)
    reps = _build_header_replacements(meta, scenarios)
    done = []
    for old, new in reps:
        count = 0
        for p in root.iter("{%s}p" % W_NS):
            count += _replace_in_paragraph(p, old, new)
        if count:
            done.append({"old": old[:80], "new": str(new)[:80], "count": count})
    cliente = (meta or {}).get("cliente") or ""
    if cliente:
        for p in root.iter("{%s}p" % W_NS):
            txt = _para_text(p)
            if "ASUNTO" in txt.upper() and "FACTIBILIDAD" in txt.upper():
                new_txt = "ASUNTO: FACTIBILIDAD AMPLIACION DE CARGA, %s." % cliente
                if _set_para_text(p, new_txt):
                    done.append({"old": "ASUNTO…", "new": new_txt, "count": 1})
                break
    # Antecedentes ubicacion (evitar duplicar "en media tensión" si ya viene en solicitud)
    ubic = (meta or {}).get("ubicacion") or ""
    solicitud = (meta or {}).get("solicitud") or "Factibilidad y Punto de Diseño"
    if ubic:
        sol_l = solicitud.lower()
        if "media tensión" in sol_l or "media tension" in sol_l:
            mid = "evaluación de %s, predio ubicado en %s." % (solicitud, ubic)
        else:
            mid = "evaluación de %s en media tensión, predio ubicado en %s." % (solicitud, ubic)
        for p in root.iter("{%s}p" % W_NS):
            txt = _para_text(p)
            if "Unidad de Proyectos" in txt and "predio ubicado" in txt.lower():
                new_txt = "La Unidad de Proyectos y Obras distribución solicita %s" % mid
                if _set_para_text(p, new_txt):
                    done.append({"old": "antecedentes ubic…", "new": new_txt[:80], "count": 1})
                break
    return done


def _xml_escape_text(value):
    """Escape minimo para contenido de <w:t>."""
    s = "" if value is None else str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _iter_wt_texts(root):
    """Lista de textos de cada <w:t> en orden de documento."""
    out = []
    for t in root.iter("{%s}t" % W_NS):
        out.append(t.text if t.text is not None else "")
    return out


def _patch_document_xml_wt(xml_bytes, new_texts):
    """
    Reescribe solo el contenido de <w:t>…</w:t> en orden, sin reserializar el XML.
    ElementTree.tostring/write corrompe namespaces de Word; este parche los preserva.
    """
    pattern = re.compile(br"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.DOTALL)
    matches = list(pattern.finditer(xml_bytes))
    if len(matches) != len(new_texts):
        raise ValueError(
            "Conteo <w:t> distinto tras edicion: xml=%d tree=%d"
            % (len(matches), len(new_texts))
        )
    parts = []
    last = 0
    changed = 0
    for i, m in enumerate(matches):
        parts.append(xml_bytes[last:m.start()])
        old_inner = m.group(2)
        new_inner = _xml_escape_text(new_texts[i]).encode("utf-8")
        if old_inner != new_inner:
            changed += 1
        parts.append(m.group(1) + new_inner + m.group(3))
        last = m.end()
    parts.append(xml_bytes[last:])
    return b"".join(parts), changed


def fill_word(docx_path, scenarios, meta, images_dir=None):
    tmp = docx_path + ".__fill_tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    mkdir(tmp)
    with zipfile.ZipFile(docx_path, "r") as zin:
        zin.extractall(tmp)

    word_dir = os.path.join(tmp, "word")
    # document.xml + headers (REFERENCIA EMAPICA) — nunca reserializar con ET.write
    xml_targets = ["document.xml"]
    if os.path.isdir(word_dir):
        for name in sorted(os.listdir(word_dir)):
            low = name.lower()
            if low.startswith("header") and low.endswith(".xml"):
                xml_targets.append(name)

    header_done = []
    tables_report = {"n_tables": 0, "filled": [], "cells": []}
    wt_changed_total = 0

    for xml_name in xml_targets:
        xml_path = os.path.join(word_dir, xml_name)
        if not os.path.isfile(xml_path):
            continue
        with open(xml_path, "rb") as f:
            original_xml = f.read()
        tree = ET.parse(xml_path)
        root = tree.getroot()
        done = _fill_word_headers(root, meta, scenarios)
        if xml_name == "document.xml":
            tables_report = _fill_word_tables(root, scenarios, meta)
            header_done = done
        elif done:
            header_done.extend([dict(x, where=xml_name) for x in done])
        new_texts = _iter_wt_texts(root)
        patched_xml, wt_changed = _patch_document_xml_wt(original_xml, new_texts)
        with open(xml_path, "wb") as f:
            f.write(patched_xml)
        wt_changed_total += wt_changed

    images_replaced = []
    if images_dir and os.path.isdir(images_dir):
        for src_name, dst_rel in IMAGE_MAP.items():
            src = os.path.join(images_dir, src_name)
            dst = os.path.join(tmp, dst_rel.replace("/", os.sep))
            if os.path.isfile(src) and os.path.isfile(dst):
                shutil.copy2(src, dst)
                images_replaced.append({"src": src, "dst": dst_rel})

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
    return {
        "replacements": header_done,
        "tables_filled": tables_report.get("filled") or [],
        "tables_cells": tables_report.get("cells") or [],
        "n_tables": tables_report.get("n_tables"),
        "images_replaced": images_replaced,
        "wt_patched": wt_changed_total,
        "xml_targets": xml_targets,
    }


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


def _metric_snapshot(scenarios):
    metric_keys = ("kw", "kvar", "kva", "fp_pct", "kw_loss", "vpu", "v_pct_a", "v_pct_b", "v_pct_c", "i_a")
    return {
        "situacional": bool(scenarios.get("situacional")),
        "proyectado": bool(scenarios.get("proyectado")),
        "situacional_metrics": (
            {k: scenarios["situacional"].get(k) for k in metric_keys}
            if scenarios.get("situacional") else None
        ),
        "proyectado_metrics": (
            {k: scenarios["proyectado"].get(k) for k in metric_keys}
            if scenarios.get("proyectado") else None
        ),
    }


def _confirm_path(paths):
    return os.path.join(paths["doc_dir"], "entrega_confirmada.json")


def load_entrega_confirmada(settings=None):
    """Lee confirmación de entrega (cierre tras vista preliminar)."""
    s = settings or load_settings()
    paths = informe_paths(s)
    path = _confirm_path(paths)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_informe_preview(settings=None):
    """
    Vista preliminar del informe ya creado (sin regenerar).
    Usar antes de cerrar/confirmar entrega.
    """
    s = settings or load_settings()
    scenarios = _load_scenarios(s)
    meta = _meta_cliente(s)
    paths = scenarios["paths"]
    img_dir = _images_dir(s)
    mkdir(img_dir)

    images = []
    for name in list(REQUIRED_LF_IMAGES) + ["topologia.png", "trafo_cargabilidad.png"]:
        full = os.path.join(img_dir, name)
        if os.path.isfile(full):
            images.append({
                "name": name,
                "url": "/api/informe/imagen/%s" % name,
                "bytes": os.path.getsize(full),
                "mtime": datetime.fromtimestamp(os.path.getmtime(full)).isoformat(timespec="seconds"),
                "required": name in REQUIRED_LF_IMAGES,
            })

    doc_inf = paths.get("informe_doc") or ""
    doc_jus = paths.get("justificacion_doc") or ""
    doc_pdf = os.path.join(paths["doc_dir"], "informe.pdf") if paths.get("doc_dir") else ""
    docs = {
        "informe": {
            "exists": bool(doc_inf and os.path.isfile(doc_inf)),
            "path": doc_inf,
            "url": "/api/informe/archivo/informe",
            "bytes": os.path.getsize(doc_inf) if doc_inf and os.path.isfile(doc_inf) else 0,
        },
        "justificacion": {
            "exists": bool(doc_jus and os.path.isfile(doc_jus)),
            "path": doc_jus,
            "url": "/api/informe/archivo/justificacion",
            "bytes": os.path.getsize(doc_jus) if doc_jus and os.path.isfile(doc_jus) else 0,
        },
        "pdf": {
            "exists": bool(doc_pdf and os.path.isfile(doc_pdf)),
            "path": doc_pdf,
            "url": "/api/informe/archivo/pdf",
            "bytes": os.path.getsize(doc_pdf) if doc_pdf and os.path.isfile(doc_pdf) else 0,
        },
    }

    # Paginas rasterizadas del render Word (si existen)
    page_previews = []
    prev_dir = os.path.join(paths["doc_dir"], "informe_preview") if paths.get("doc_dir") else ""
    if prev_dir and os.path.isdir(prev_dir):
        for name in sorted(os.listdir(prev_dir)):
            if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            full = os.path.join(prev_dir, name)
            page_previews.append({
                "name": name,
                "url": "/api/informe/pagina/%s" % name,
                "bytes": os.path.getsize(full),
            })

    filled = docs["informe"]["exists"] and docs["justificacion"]["exists"]
    required_imgs = [i for i in images if i.get("required")]
    preview_ok = filled and len(required_imgs) >= len(REQUIRED_LF_IMAGES)
    confirm = load_entrega_confirmada(s)

    word_replacements = []
    man_path = os.path.join(paths["doc_dir"], "fill_manifest.json")
    if os.path.isfile(man_path):
        try:
            with open(man_path, "r", encoding="utf-8") as f:
                man = json.load(f)
            word_replacements = ((man.get("word") or {}).get("replacements") or [])[:40]
            if not scenarios.get("situacional") and man.get("scenarios_used"):
                # fallback metrics from last fill
                pass
        except Exception:
            man = {}
    else:
        man = {}

    scenarios_used = man.get("scenarios_used") or _metric_snapshot(scenarios)
    render_info = man.get("render") or {}

    return {
        "ok": True,
        "preview_ok": preview_ok,
        "can_close": preview_ok and not bool((confirm or {}).get("confirmed")),
        "closed": bool((confirm or {}).get("confirmed")),
        "confirm": confirm,
        "feeder_id": s.get("feeder_id"),
        "filled_at": man.get("filled_at"),
        "meta": {
            "cliente": meta.get("cliente") or "",
            "ubicacion": meta.get("ubicacion") or "",
            "solicitud": meta.get("solicitud") or "",
            "potencia_kw": meta.get("potencia_kw"),
            "potencia_txt": meta.get("potencia_txt") or "",
            "alimentador": meta.get("alimentador") or s.get("feeder_id") or "",
            "set": meta.get("set") or "",
            "tension_kv": meta.get("tension_kv"),
            "transformador": meta.get("transformador") or "",
            "expediente": meta.get("expediente") or "",
            "proyecto": meta.get("proyecto") or "",
            "meta_source": meta.get("meta_source"),
        },
        "scenarios_used": scenarios_used,
        "images": images,
        "images_dir": img_dir,
        "docs": docs,
        "page_previews": page_previews,
        "render": {
            "ok": bool(render_info.get("ok")),
            "pages": render_info.get("pages"),
            "pdf": render_info.get("pdf") or (doc_pdf if docs["pdf"]["exists"] else None),
            "rendered_at": render_info.get("rendered_at"),
        },
        "word_replacements": word_replacements,
        "msg": (
            "Vista preliminar lista — valide datos y gráficas antes de cerrar."
            if preview_ok else
            "Informe incompleto: rellene §6.2 (Word/Excel + 4 gráficas LF)."
        ),
    }


def confirm_informe_entrega(settings=None, note="", force=False):
    """
    Cierra la entrega tras validar la vista preliminar.
    Exige docs + 4 PNG; escribe doc/entrega_confirmada.json.
    """
    s = settings or load_settings()
    preview = build_informe_preview(s)
    if not preview.get("preview_ok") and not force:
        return {
            "ok": False,
            "error": "No se puede cerrar: falta vista preliminar completa (docs o gráficas).",
            "preview": preview,
        }
    paths = informe_paths(s)
    mkdir(paths["doc_dir"])
    payload = {
        "ok": True,
        "confirmed": True,
        "confirmed_at": datetime.now().isoformat(timespec="seconds"),
        "feeder_id": s.get("feeder_id"),
        "note": (note or "").strip(),
        "preview_snapshot": {
            "meta": preview.get("meta"),
            "scenarios_used": preview.get("scenarios_used"),
            "images": [i.get("name") for i in (preview.get("images") or [])],
            "docs": {
                "informe": (preview.get("docs") or {}).get("informe", {}).get("path"),
                "justificacion": (preview.get("docs") or {}).get("justificacion", {}).get("path"),
            },
            "filled_at": preview.get("filled_at"),
        },
    }
    path = _confirm_path(paths)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    payload["path"] = path
    payload["msg"] = "Entrega confirmada · informe validado en vista preliminar"
    return payload


def fill_informe(settings=None, overwrite_copy=True, require_delivery=True):
    """
    Copia plantilla → doc/ y rellena Excel + Word con LoadFlow.

    require_delivery=True (default): exige ambos LF, meta OCR minima y 4 PNG LF.
    Si faltan, no toca doc/ y retorna ok=False + missing[].
    """
    s = settings or load_settings()
    scenarios = _load_scenarios(s)
    meta = _meta_cliente(s)
    # Persistir meta completa (SET/trafo/etc.) para UI §6.1
    try:
        from pipeline.extract_informe_meta_pdf import save_informe_meta
        save_informe_meta(s, meta)
    except Exception as ex:
        notes = ["aviso save meta: %s" % ex]
    else:
        notes = []
    paths = scenarios["paths"]
    img_dir = _images_dir(s)
    mkdir(img_dir)
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
                force=True,
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

    # Mapa satelite §2.1: ubicacion de la carga nueva (nodo X/Y → WGS84)
    map_res = None
    try:
        from pipeline.generate_location_map import generate_location_map
        map_res = generate_location_map(s, out_dir=img_dir, force=True)
        if map_res.get("ok"):
            notes.append("topologia.png mapa carga nueva OK")
        else:
            notes.append("topologia.png omitido: %s" % (map_res.get("error") or "?"))
    except Exception as ex:
        map_res = {"ok": False, "error": str(ex)}
        notes.append("topologia.png error: %s" % ex)

    delivery_ready, missing = _check_delivery_gates(
        scenarios, meta, img_dir, charts_res, settings=s
    )

    scenarios_used = _metric_snapshot(scenarios)

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
            "location_map": map_res,
            "scenarios_used": scenarios_used,
            "notes": notes,
            "aviso_imagenes": (
                "Graficas LF se generan desde loadflow_*.json. "
                "topologia.png = mapa satelite carga nueva. Override en %s."
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

    # Rellenar de nuevo invalida cierre previo (hay que revalidar preliminar).
    try:
        conf = _confirm_path(paths)
        if os.path.isfile(conf):
            os.remove(conf)
            notes.append("entrega_confirmada.json invalidada (relleno nuevo)")
    except Exception as ex:
        notes.append("aviso invalidar confirm: %s" % ex)

    xnotes = fill_excel(paths["justificacion_doc"], scenarios, meta)
    notes.extend(xnotes)
    wres = fill_word(paths["informe_doc"], scenarios, meta, images_dir=img_dir)
    notes.append("word replacements: %d" % len(wres.get("replacements") or []))
    _tbl = ", ".join(wres.get("tables_filled") or []) or "(none)"
    notes.append("word tables: %s" % _tbl)
    notes.append("images replaced: %d" % len(wres.get("images_replaced") or []))

    replaced_names = [
        os.path.basename(x.get("src") or "") for x in (wres.get("images_replaced") or [])
    ]
    lf_replaced = [n for n in REQUIRED_LF_IMAGES if n in replaced_names]

    # Render final Word: campos, paginado y PDF de entrega
    render_res = None
    try:
        from pipeline.render_informe import render_informe as _render_informe
        render_res = _render_informe(s, export_pdf=True, preview_pages=True)
        if render_res.get("ok"):
            notes.append(
                "render Word ok · paginas=%s · pdf=%s"
                % (render_res.get("pages"), "si" if render_res.get("pdf") else "no")
            )
            for n in (render_res.get("notes") or [])[:8]:
                notes.append("render: %s" % n)
        else:
            notes.append("aviso render Word: %s" % (render_res.get("error") or "fallo"))
    except Exception as ex:
        render_res = {"ok": False, "error": str(ex)}
        notes.append("aviso render Word: %s" % ex)

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
        "location_map": map_res,
        "scenarios_used": scenarios_used,
        "excel_notes": xnotes,
        "word": wres,
        "render": render_res,
        "lf_images_replaced": lf_replaced,
        "notes": notes,
        "preview_url": "/api/informe/preview",
        "needs_preview_confirm": True,
        "aviso_imagenes": (
            "Graficas LF desde JSON en %s. "
            "topologia.png = mapa satelite de la carga nueva (nodo de conexion). "
            "Valide la vista preliminar (§6.3) antes de cerrar la entrega."
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
