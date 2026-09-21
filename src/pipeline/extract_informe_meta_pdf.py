# -*- coding: utf-8 -*-
"""
Extrae datos generales del informe desde un PDF de solicitud / factibilidad.

Flujo:
  1) Texto nativo con pypdf
  2) Si insuficiente -> OCR (pdf2image + pytesseract, spa+eng)
  3) Heuristicas / regex -> campos Excel hoja Informe (C4-C10)

Salida tipica: demand/informe_meta.json
"""
from __future__ import print_function
import json
import os
import re
from datetime import datetime

from core.common import mkdir
from core.feeder_context import load_settings, output_path

META_FIELDS = (
    "cliente",
    "ubicacion",
    "solicitud",
    "potencia_kw",
    "potencia_txt",
    "alimentador",
    "set",
    "tension_kv",
    "transformador",
    "expediente",
)

_MIN_NATIVE_CHARS = 80


def meta_path(settings):
    return output_path(settings, "demand", "informe_meta.json")


def load_informe_meta(settings):
    path = meta_path(settings)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_informe_meta(settings, meta):
    path = meta_path(settings)
    mkdir(os.path.dirname(path))
    data = dict(meta or {})
    data["saved_at"] = datetime.now().isoformat(timespec="seconds")
    data["feeder_id"] = settings.get("feeder_id")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return path


def _num(val, default=None):
    if val is None or val == "":
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return default


def extract_text_native(pdf_path):
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader  # noqa: N812
        except Exception as ex:
            return "", "pypdf_no_disponible: %s" % ex
    try:
        reader = PdfReader(pdf_path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        return "\n".join(parts), None
    except Exception as ex:
        return "", str(ex)


def extract_text_ocr(pdf_path, lang="spa+eng"):
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception as ex:
        return "", "ocr_deps: %s" % ex
    try:
        images = convert_from_path(pdf_path, dpi=200)
    except Exception as ex:
        return "", "pdf2image: %s (verifique Poppler en PATH)" % ex
    parts = []
    try:
        for img in images:
            parts.append(pytesseract.image_to_string(img, lang=lang) or "")
    except Exception as ex:
        # reintento solo ingles
        try:
            parts = []
            for img in images:
                parts.append(pytesseract.image_to_string(img, lang="eng") or "")
        except Exception as ex2:
            return "", "tesseract: %s / %s" % (ex, ex2)
    return "\n".join(parts), None


def _find_labeled(text, labels, max_span=120):
    """Busca 'Etiqueta: valor' o 'Etiqueta valor' en las primeras lineas utiles."""
    if not text:
        return None
    for lab in labels:
        pat = re.compile(
            r"(?im)(?:^|\n)\s*%s\s*[:\-–]?\s*(.+?)(?:\n|$)" % re.escape(lab),
        )
        m = pat.search(text)
        if m:
            val = m.group(1).strip()
            val = re.split(r"\s{2,}|\t", val)[0].strip()
            if len(val) > max_span:
                val = val[:max_span].rstrip()
            if val:
                return val
    return None


def _find_kw(text):
    if not text:
        return None
    patterns = [
        r"(?i)(?:potencia(?:\s+solicitada)?|demanda(?:\s+solicitada)?|p\s*max)\s*[:\-]?\s*([\d.,]+)\s*(?:k\s*w|kw)",
        r"(?i)([\d.,]+)\s*(?:k\s*w|kw)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return _num(m.group(1))
    return None


def _find_kv(text):
    if not text:
        return None
    m = re.search(r"(?i)([\d.,]+)\s*k\s*v\b", text)
    if m:
        return _num(m.group(1))
    return None


def parse_meta_from_text(text, settings=None):
    settings = settings or {}
    feeder = settings.get("feeder_id") or ""
    cliente = _find_labeled(text, [
        "Cliente", "Solicitante", "Razon Social", "Razón Social", "Titular", "Empresa",
    ])
    ubicacion = _find_labeled(text, [
        "Ubicacion", "Ubicación", "Direccion", "Dirección", "Localidad", "Distrito",
    ])
    solicitud = _find_labeled(text, [
        "Solicitud", "Tipo de solicitud", "Asunto", "Objeto",
    ]) or "Factibilidad y Punto de Diseño"
    alimentador = _find_labeled(text, [
        "Alimentador", "Feeder", "Circuito", "Radial",
    ]) or feeder
    set_name = _find_labeled(text, [
        "SET", "Subestacion", "Subestación", "SE ",
    ])
    transformador = _find_labeled(text, [
        "Transformador", "Trafo", "Transformador SET",
    ])
    expediente = _find_labeled(text, [
        "Expediente", "Nro. expediente", "N° expediente", "Codigo", "Código", "Nro solicitud",
    ])
    potencia_kw = _find_kw(text)
    tension_kv = _find_kv(text)
    if tension_kv is None:
        tension_kv = _num(settings.get("voltage_ll_kv"), 22.9)

    potencia_txt = ""
    if potencia_kw is not None:
        potencia_txt = "%dKW" % int(round(potencia_kw))

    return {
        "cliente": cliente or "",
        "ubicacion": ubicacion or (settings.get("region") or ""),
        "solicitud": solicitud or "",
        "potencia_kw": potencia_kw,
        "potencia_txt": potencia_txt,
        "alimentador": (alimentador or feeder or "").strip().upper() if alimentador or feeder else "",
        "set": set_name or (settings.get("substation") or ""),
        "tension_kv": tension_kv,
        "transformador": transformador or (settings.get("transformer") or ""),
        "expediente": expediente or "",
    }


def meta_is_complete(meta):
    """Minimo para entrega: cliente + potencia."""
    if not meta:
        return False
    cliente = (meta.get("cliente") or "").strip()
    pk = meta.get("potencia_kw")
    pt = (meta.get("potencia_txt") or "").strip()
    if not cliente:
        return False
    if pk is None and (not pt or pt in ("—", "-", "")):
        return False
    return True


def extract_informe_meta_from_pdf(pdf_path, settings=None, save=True):
    """
    Extrae y opcionalmente guarda informe_meta.json.
    Retorna dict con meta, method, warnings, path.
    """
    s = settings or load_settings()
    if not pdf_path or not os.path.isfile(pdf_path):
        return {"ok": False, "error": "PDF no encontrado: %s" % pdf_path}

    warnings = []
    text, err = extract_text_native(pdf_path)
    method = "native"
    if err:
        warnings.append("native: %s" % err)
        text = ""
    if len((text or "").strip()) < _MIN_NATIVE_CHARS:
        ocr_text, ocr_err = extract_text_ocr(pdf_path)
        if ocr_err:
            warnings.append(ocr_err)
        if ocr_text and len(ocr_text.strip()) > len((text or "").strip()):
            text = ocr_text
            method = "ocr"
        elif not text:
            return {
                "ok": False,
                "error": "No se pudo extraer texto del PDF (nativo ni OCR).",
                "warnings": warnings,
            }

    meta = parse_meta_from_text(text, s)
    meta["source"] = "pdf_ocr" if method == "ocr" else "pdf_native"
    meta["source_pdf"] = os.path.abspath(pdf_path)
    meta["extract_method"] = method
    meta["extracted_at"] = datetime.now().isoformat(timespec="seconds")
    meta["text_chars"] = len(text or "")
    meta["text_preview"] = (text or "")[:1500]

    path = None
    if save:
        path = save_informe_meta(s, meta)

    return {
        "ok": True,
        "meta": meta,
        "complete": meta_is_complete(meta),
        "method": method,
        "warnings": warnings,
        "path": path,
    }


def main():
    import sys
    s = load_settings()
    pdf = sys.argv[1] if len(sys.argv) > 1 else None
    if not pdf:
        print("Uso: extract_informe_meta_pdf.py <archivo.pdf>")
        raise SystemExit(2)
    res = extract_informe_meta_from_pdf(pdf, s, save=True)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    if not res.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
