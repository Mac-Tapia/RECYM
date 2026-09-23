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
    s = str(val).strip()
    # Unir digitos partidos por espacio: "14 20.00" / "1 420,50" → 1420.00
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)
    s = s.replace(" ", "").replace(",", ".")
    # Si quedaron dos puntos (1.420.50) dejar solo el decimal final
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
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
            val = re.split(
                r"\s+(?:Cliente|Ubicaci[oó]n|Solicitud|Alimentador|SET|Subestaci[oó]n|"
                r"Transformador|Expediente|Potencia|Tensi[oó]n|Feeder|Asunto|Presente)\b",
                val,
                maxsplit=1,
                flags=re.I,
            )[0].strip(" .;,-")
            if len(val) > max_span:
                val = val[:max_span].rstrip()
            if val and len(val) >= 2:
                return val
    return None


def _find_demanda_kw(text):
    """Prioriza 'maxima demanda' / potencia solicitada; soporta '14 20.00 kW'."""
    if not text:
        return None
    patterns = [
        r"(?i)m[aá]xima\s+demanda(?:\s+(?:de|requerida|solicitada))?\s*(?:de|:)?\s*([\d.\s,]+)\s*(?:k\s*w|kw)\b",
        r"(?i)demanda\s+m[aá]xima(?:\s+(?:de|requerida|solicitada))?\s*(?:de|:)?\s*([\d.\s,]+)\s*(?:k\s*w|kw)\b",
        r"(?i)(?:potencia(?:\s+(?:solicitada|contratada|requerida|activa|maxima|m[aá]xima))?|p\s*max|pmax)\s*[:\-]?\s*([\d.\s,]+)\s*(?:k\s*w|kw)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            v = _num(m.group(1))
            if v is not None and v >= 5:
                return v
    # Fallback: mayor kW razonable del texto (evita 20 de '14 20.00' mal partido)
    best = None
    for m in re.finditer(r"(?i)([\d.\s,]{3,})\s*(?:k\s*w|kw)\b", text):
        raw = m.group(1)
        # Preferir numeros con espacio de miles o >= 3 digitos enteros
        v = _num(raw)
        if v is None or v < 5:
            continue
        if best is None or v > best:
            best = v
    return best


def _find_kw(text):
    return _find_demanda_kw(text)


def _find_kv(text):
    if not text:
        return None
    patterns = [
        r"(?i)(?:tensi[oó]n(?:\s+(?:nominal|de\s+servicio|ll|media))?|v\s*nom(?:inal)?|media\s+tensi[oó]n)\s*[:\-]?\s*([\d.,]+)\s*k\s*v\b",
        r"(?i)([\d.,]+)\s*k\s*v(?:ll|ln)?\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            v = _num(m.group(1))
            if v is not None and 1.0 <= v <= 500.0:
                return v
    return None


def _find_feeder(text):
    if not text:
        return None
    labeled = _find_labeled(text, [
        "Alimentador", "Feeder", "Circuito", "Radial",
    ])
    if labeled:
        m = re.search(r"\b([A-Z]{1,3}\d{2,4})\b", labeled.upper())
        if m:
            return m.group(1)
        return labeled.strip().upper()
    m = re.search(r"\b(?:alimentador|feeder|circuito|radial)\s*[:\-–]?\s*([A-Z]{1,3}\d{2,4})\b", text, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-Z]{2}\d{3})\b", text.upper())
    if m:
        return m.group(1)
    return None


def _find_set(text):
    labeled = _find_labeled(text, [
        "SET", "Subestacion", "Subestación", "S.E.T.", "S.E.",
    ])
    if labeled:
        return labeled
    m = re.search(
        r"(?i)\b(?:SET|S\.?E\.?T\.?|subestaci[oó]n)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9\-\s/]{1,40})",
        text or "",
    )
    if m:
        return m.group(1).strip()
    return None


def _find_cliente(text):
    """Cliente = solicitante/propietario del proyecto (no el Presente/concesionaria)."""
    if not text:
        return None
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    flat = re.sub(r"\s+", " ", flat)
    m = re.search(
        r"(?i)propiedad\s+de\s+(.+?)\s+con\s+RUC\s*(\d{8,11})",
        flat,
    )
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip(" ,;.")
        name = re.sub(r"^(?:el|la|los|las)\s+", "", name, flags=re.I)
        if not re.search(r"electrodunas|electro\s*dunas", name, re.I):
            return "%s (RUC %s)" % (name, m.group(2))
    m = re.search(
        r"(?i)\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚáéíóúñÑ0-9 .&]{1,60}?S\.?\s*A\.?(?:A)?)\s+con\s+RUC\s*(\d{8,11})",
        flat,
    )
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        if not re.search(r"electrodunas|electro\s*dunas", name, re.I):
            return "%s (RUC %s)" % (name, m.group(2))
    labeled = _find_labeled(text, [
        "Cliente", "Solicitante", "Razon Social", "Razón Social", "Titular",
    ])
    if labeled and not re.search(r"electrodunas|electro\s*dunas", labeled, re.I):
        return labeled
    return None


def _find_ubicacion(text):
    if not text:
        return None
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    flat = re.sub(r"\s+", " ", flat)
    # Carta LARQ: "ubicado en el sector X, ... departamento de Y"
    m = re.search(
        r"(?i)ubicad[oa]\s+en\s+(?:el\s+)?(.+?)(?:,\s*proyecto\s+propiedad|\.\s|;\s)",
        flat,
    )
    if m:
        loc = m.group(1).strip(" ,;.")
        loc = re.sub(r"\s+con\s+", ", ", loc, count=1, flags=re.I)
        loc = re.sub(r",\s*,+", ", ", loc)
        loc = re.sub(r"^(?:el|la|los|las)\s+", "", loc, flags=re.I)
        if loc and not loc[0].isupper():
            loc = loc[0].upper() + loc[1:]
        if len(loc) > 20:
            if len(loc) > 180:
                loc = loc[:180].rstrip()
            return loc
    labeled = _find_labeled(text, [
        "Ubicacion", "Ubicación", "Direccion", "Dirección", "Localidad", "Distrito",
        "Provincia", "Lugar",
    ], max_span=180)
    if labeled:
        return labeled
    m = re.search(
        r"(?i)(?:distrito\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ ]+)(?:,\s*provincia\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ ]+)?"
        r"(?:\s+y\s+departamento\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ ]+)?",
        flat,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


def _find_solicitud(text):
    flat = re.sub(r"[ \t]*\n[ \t]*", " ", text or "")
    flat = re.sub(r"\s+", " ", flat)
    m = re.search(
        r"(?i)Asunto\s*[:\-–]?\s*(Solicitud\s+de\s+factibilidad[^.]{0,100}?)(?:\s+para\s+el\s+proyecto|\.|$)",
        flat,
    )
    if m:
        return m.group(1).strip()
    labeled = _find_labeled(text, [
        "Asunto", "Solicitud", "Tipo de solicitud", "Objeto", "Motivo", "Tipo de estudio",
    ], max_span=160)
    if labeled:
        labeled = re.split(r"(?i)\s+para\s+el\s+proyecto\b", labeled, maxsplit=1)[0].strip()
        return labeled
    m = re.search(r"(?i)solicitud\s+de\s+(factibilidad[^.\n]{0,80})", flat)
    if m:
        return ("Solicitud de " + m.group(1)).strip()
    return "Factibilidad y Punto de Diseño"


def parse_meta_from_text(text, settings=None):
    settings = settings or {}
    feeder = settings.get("feeder_id") or ""

    cliente = _find_cliente(text)
    ubicacion = _find_ubicacion(text)
    solicitud = _find_solicitud(text)
    alimentador = _find_feeder(text) or feeder
    set_name = _find_set(text)
    transformador = _find_labeled(text, [
        "Transformador", "Trafo", "Transformador SET", "Potencia transformador",
    ])
    expediente = _find_labeled(text, [
        "Expediente", "Nro. expediente", "N° expediente", "Nº expediente",
        "Codigo", "Código", "Nro solicitud", "N° solicitud", "Código LARQ",
    ])
    if not expediente:
        m = re.search(r"\b(LARQ[-/\s]?[A-Z0-9]+[-/\s]?\d+)\b", text or "", re.I)
        if m:
            expediente = re.sub(r"\s+", "-", m.group(1).upper())
    if not expediente:
        m = re.search(r"\b(CARTA\s*G?\s*T[-/\s]?SU[-/\s]?\d{3,4}[-/\s]?\d{4}(?:/\w+)?)\b", text or "", re.I)
        if m:
            expediente = re.sub(r"\s+", " ", m.group(1)).strip()

    potencia_kw = _find_demanda_kw(text)
    tension_kv = _find_kv(text)
    if tension_kv is None:
        # "media tension" sin numero → usar settings
        if re.search(r"(?i)media\s+tensi[oó]n", text or ""):
            tension_kv = _num(settings.get("voltage_ll_kv"), 22.9)
        else:
            tension_kv = _num(settings.get("voltage_ll_kv"), 22.9)

    potencia_txt = ""
    if potencia_kw is not None:
        potencia_txt = "%dKW" % int(round(potencia_kw))

    # Nombre de proyecto (complemento cliente)
    proyecto = ""
    m = re.search(
        r"(?is)proyecto\s+[«\"“]?\s*([^»\"”\n]{5,80}?)\s*[»\"”]?\s+ubicad",
        text or "",
    )
    if m:
        proyecto = re.sub(r"\s+", " ", m.group(1)).strip(" «»\"“”")

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
        "proyecto": proyecto,
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
