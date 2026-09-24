# -*- coding: utf-8 -*-
"""
Revision rigurosa del informe PDF por OCR + verificacion de capturas CYMDIST.

Ciclo estricto (hasta 3 veces)::

  1) Revisar PDF con OCR (cuadros + imagenes CYMDIST sin/con proyecto)
  2) Si hay errores → corregir Word (fill + capturas si aplica)
  3) Convertir Word → PDF nuevo
  4) Revisar con OCR esa nueva version
  5) Repetir hasta aprobar o agotar 3 ciclos

Uso::
  python -m pipeline.review_informe_pdf --feeder AL209
"""
from __future__ import print_function

import hashlib
import json
import os
import re
import zipfile
from datetime import datetime

from core.common import mkdir
from core.feeder_context import load_settings


REQUIRED_CAPTURES = (
    ("situacional_tension.png", "situacional", "tension", "word/media/image3.png"),
    ("situacional_cargabilidad.png", "situacional", "cargabilidad", "word/media/image5.png"),
    ("proyectado_tension.png", "proyectado", "tension", "word/media/image7.png"),
    ("proyectado_cargabilidad.png", "proyectado", "cargabilidad", "word/media/image9.png"),
)


def _images_dir(settings):
    from pipeline.fill_informe import _images_dir as _id
    return _id(settings)


def _fmt_kw(val):
    if val is None:
        return None
    try:
        return "%.0f" % float(val)
    except Exception:
        return None


def _md5_file(path):
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_sidecar(png_path):
    side = png_path + ".cymdist.json"
    if not os.path.isfile(side):
        return None
    try:
        with open(side, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _extract_pdf_native(pdf_path, max_pages=12):
    """Texto nativo pypdf por pagina. Retorna (pages, error)."""
    pages = []
    try:
        from pypdf import PdfReader
    except Exception as ex:
        return [], "pypdf: %s" % ex
    try:
        reader = PdfReader(pdf_path)
    except Exception as ex:
        return [], "pdf_open: %s" % ex
    n = min(len(reader.pages), int(max_pages or 12))
    for i in range(n):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception as ex:
            text = ""
            pages.append({"page": i + 1, "text": "", "error": str(ex), "method": "native"})
            continue
        pages.append({"page": i + 1, "text": text, "method": "native"})
    return pages, None


def _ocr_pdf_pages(pdf_path, max_pages=10, dpi=120):
    """
    Extrae texto del PDF: nativo (pypdf) + OCR (tesseract) si aporta mas.
    Retorna (pages[{page,text,method}], error).
    """
    native_pages, native_err = _extract_pdf_native(pdf_path, max_pages=max_pages)
    ocr_pages = []
    ocr_err = None

    # Resolver tesseract.exe tipico en Windows
    try:
        import pytesseract
        tess_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
        candidates = [
            tess_cmd,
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                pytesseract.pytesseract.tesseract_cmd = c
                break
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=max_pages)
        for i, img in enumerate(images, 1):
            text = ""
            try:
                text = pytesseract.image_to_string(img, lang="spa+eng") or ""
            except Exception:
                try:
                    text = pytesseract.image_to_string(img, lang="eng") or ""
                except Exception as ex:
                    ocr_err = "tesseract: %s" % ex
                    break
            ocr_pages.append({"page": i, "text": text, "method": "ocr"})
    except Exception as ex:
        ocr_err = "ocr_deps: %s" % ex

    # Fusion: preferir el texto mas largo por pagina
    by_page = {}
    for p in native_pages or []:
        by_page[p["page"]] = dict(p)
    for p in ocr_pages or []:
        cur = by_page.get(p["page"])
        if cur is None or len(p.get("text") or "") > len(cur.get("text") or ""):
            by_page[p["page"]] = dict(p)
            if cur and cur.get("text"):
                by_page[p["page"]]["method"] = "ocr+native"
    pages = [by_page[k] for k in sorted(by_page.keys())]
    err = None
    if not pages:
        err = ocr_err or native_err or "sin texto PDF"
    elif sum(len(p.get("text") or "") for p in pages) < 80:
        err = ocr_err or native_err or "texto PDF insuficiente"
    return pages, err


def _normalize_ocr(text):
    t = (text or "").upper()
    t = t.replace(",", ".")
    t = re.sub(r"\s+", " ", t)
    return t


def _number_in_text(text, value, tol_pct=0.5):
    """True si el valor (o redondeos tipicos) aparece en el OCR."""
    if value is None:
        return False
    try:
        v = float(value)
    except Exception:
        return False
    candidates = set()
    for nd in (0, 1, 2):
        s = ("%%.%df" % nd) % v
        candidates.add(s)
        candidates.add(s.replace(".", ","))
    if abs(v) >= 1000:
        candidates.add("{:,.0f}".format(v))
        candidates.add("{:,.0f}".format(v).replace(",", "."))
        candidates.add("{:,.2f}".format(v))
    blob = _normalize_ocr(text)
    blob_dot = blob.replace(",", ".")
    blob_bare = blob_dot.replace(".", "")
    for c in candidates:
        if not c:
            continue
        token = c.upper().replace(",", ".")
        if token in blob_dot:
            return True
        bare = token.replace(".", "")
        if len(bare) >= 3 and bare in blob_bare:
            return True
    iv = int(round(v))
    for d in range(-2, 3):
        if str(iv + d) in blob:
            return True
    return False


def _check_captures(settings, img_dir, findings):
    """Verifica PNG locales + sidecars CYMDIST (escenario / live / distintos)."""
    from pipeline.capture_informe_color_views import is_live_cymdist_view, is_cymdist_capture

    hashes = {}
    for fname, scen, kind, _dst in REQUIRED_CAPTURES:
        path = os.path.join(img_dir, fname)
        if not os.path.isfile(path):
            findings.append({
                "code": "capture_missing",
                "severity": "error",
                "file": fname,
                "msg": "Falta captura %s" % fname,
                "fix": "recapture",
            })
            continue
        if os.path.getsize(path) < 8000:
            findings.append({
                "code": "capture_too_small",
                "severity": "error",
                "file": fname,
                "msg": "%s demasiado pequena (%d B)" % (fname, os.path.getsize(path)),
                "fix": "recapture",
            })
        meta = _read_sidecar(path)
        if not meta or not str(meta.get("source") or "").startswith("cymdist"):
            findings.append({
                "code": "capture_not_cymdist",
                "severity": "error",
                "file": fname,
                "msg": "%s no es captura CYMDIST (sidecar ausente o source!=cymdist)" % fname,
                "fix": "recapture",
            })
        else:
            meta_scen = str(meta.get("scenario") or "").lower()
            if meta_scen and meta_scen != scen:
                findings.append({
                    "code": "capture_wrong_scenario",
                    "severity": "error",
                    "file": fname,
                    "msg": "%s sidecar scenario=%s esperado=%s" % (fname, meta_scen, scen),
                    "fix": "recapture",
                })
            meta_kind = str(meta.get("kind") or "").lower()
            if meta_kind and meta_kind != kind:
                findings.append({
                    "code": "capture_wrong_kind",
                    "severity": "warning",
                    "file": fname,
                    "msg": "%s kind=%s esperado=%s" % (fname, meta_kind, kind),
                    "fix": "recapture",
                })
            expect_color = "VoltageLevel" if kind == "tension" else "LoadingLevel"
            meta_color = str(meta.get("color_type") or "")
            if meta_color != expect_color:
                findings.append({
                    "code": "capture_wrong_color_type",
                    "severity": "error",
                    "file": fname,
                    "msg": "%s color_type=%s esperado=%s (coloreo tension/cargabilidad)"
                    % (fname, meta_color or "?", expect_color),
                    "fix": "recapture",
                })
            if meta.get("lf_converged") is False:
                findings.append({
                    "code": "capture_not_converged",
                    "severity": "error",
                    "file": fname,
                    "msg": "%s sin LoadFlow convergido previo a la captura" % fname,
                    "fix": "recapture",
                })
            if meta.get("color_verified") is not True:
                findings.append({
                    "code": "capture_color_unverified",
                    "severity": "error",
                    "file": fname,
                    "msg": (
                        "%s sin verificacion de coloreo ElectroDunas "
                        "(VoltageLevel/LoadingLevel vs banda esperada)"
                        % fname
                    ),
                    "fix": "recapture",
                })
            else:
                exp = (meta.get("color_check") or {}).get("expected_band")
                dom = (meta.get("color_check") or {}).get("dominant")
                if exp and dom and exp != dom and exp != "green":
                    # dominante distinto puede ser OK si expected_ratio alto; aviso suave
                    ratio = (meta.get("color_check") or {}).get("expected_ratio")
                    if ratio is not None and float(ratio) < 0.12:
                        findings.append({
                            "code": "capture_color_band_mismatch",
                            "severity": "error",
                            "file": fname,
                            "msg": (
                                "%s banda esperada=%s dominante=%s ratio=%s "
                                "(posible 'Colorear por fase')"
                                % (fname, exp, dom, ratio)
                            ),
                            "fix": "recapture",
                        })
            if not is_live_cymdist_view(path):
                findings.append({
                    "code": "capture_not_live",
                    "severity": "error",
                    "file": fname,
                    "msg": "%s no es vista live CYMDIST coloreada (posible matplotlib/topology)" % fname,
                    "fix": "recapture",
                })
        hashes[fname] = _md5_file(path)

    # tension vs cargabilidad del mismo escenario deben diferir (histogramas)
    try:
        from pipeline.capture_informe_color_views import _map_region_histogram
        for scen in ("situacional", "proyectado"):
            ft = os.path.join(img_dir, "%s_tension.png" % scen)
            fc = os.path.join(img_dir, "%s_cargabilidad.png" % scen)
            if not (os.path.isfile(ft) and os.path.isfile(fc)):
                continue
            ht = _map_region_histogram(ft)
            hc = _map_region_histogram(fc)
            if not (ht.get("ok") and hc.get("ok")):
                continue
            if ht.get("dominant") and ht.get("dominant") == hc.get("dominant"):
                # Si ambos verdes → tipico fallo de fase en los dos
                if ht.get("dominant") == "green":
                    findings.append({
                        "code": "capture_same_phase_green",
                        "severity": "error",
                        "file": "%s_tension.png" % scen,
                        "msg": (
                            "%s tension y cargabilidad ambos verde dominante "
                            "(toolbar en 'Colorear por fase'?)"
                            % scen
                        ),
                        "fix": "recapture",
                    })
    except Exception as ex:
        findings.append({
            "code": "capture_hist_check_error",
            "severity": "warning",
            "msg": "no se pudo comparar histogramas tension/cargabilidad: %s" % ex,
        })

    # situacional vs proyectado deben diferir
    pairs = (
        ("situacional_tension.png", "proyectado_tension.png"),
        ("situacional_cargabilidad.png", "proyectado_cargabilidad.png"),
    )
    for a, b in pairs:
        ha, hb = hashes.get(a), hashes.get(b)
        if ha and hb and ha == hb:
            findings.append({
                "code": "capture_identical_scenarios",
                "severity": "error",
                "file": a,
                "msg": "%s identica a %s (sin/con proyecto deben diferir)" % (a, b),
                "fix": "recapture",
            })


def _check_docx_media(docx_path, img_dir, findings):
    """Las imagenes embebidas en Word deben coincidir con las capturas de disco."""
    if not docx_path or not os.path.isfile(docx_path):
        findings.append({
            "code": "docx_missing",
            "severity": "error",
            "msg": "informe.docx no encontrado",
            "fix": "refill",
        })
        return
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            for fname, _scen, _kind, dst in REQUIRED_CAPTURES:
                src = os.path.join(img_dir, fname)
                if not os.path.isfile(src):
                    continue
                try:
                    embedded = zf.read(dst)
                except Exception:
                    findings.append({
                        "code": "docx_media_missing",
                        "severity": "error",
                        "file": dst,
                        "msg": "Falta %s en el docx" % dst,
                        "fix": "refill",
                    })
                    continue
                src_md5 = _md5_file(src)
                emb_md5 = hashlib.md5(embedded).hexdigest()
                if src_md5 and emb_md5 and src_md5 != emb_md5:
                    findings.append({
                        "code": "docx_media_stale",
                        "severity": "error",
                        "file": fname,
                        "msg": "%s en Word no coincide con captura disco (docx desactualizado)" % fname,
                        "fix": "refill",
                    })
                if len(embedded) < 8000:
                    findings.append({
                        "code": "docx_media_tiny",
                        "severity": "error",
                        "file": dst,
                        "msg": "%s embebida muy pequena" % dst,
                        "fix": "refill",
                    })
    except Exception as ex:
        findings.append({
            "code": "docx_read_error",
            "severity": "error",
            "msg": "No se pudo leer docx: %s" % ex,
            "fix": "refill",
        })


def _check_ocr_cuadros(full_text, scenarios, findings):
    """Verifica que el PDF OCR contenga valores de cuadros situacional/proyectado."""
    blob = _normalize_ocr(full_text)
    if len(blob) < 200:
        findings.append({
            "code": "ocr_empty",
            "severity": "error",
            "msg": "OCR del PDF casi vacio (%d chars)" % len(blob),
            "fix": "rerender",
        })
        return

    sit = (scenarios or {}).get("situacional") or {}
    proy = (scenarios or {}).get("proyectado") or {}

    # Labels de escenario
    has_act = ("ESTADO ACTUAL" in blob) or ("SITUACIONAL" in blob) or ("SIN CARGA NUEVA" in blob)
    has_proy = ("ESTADO PROYECTADO" in blob) or ("CON CARGA NUEVA" in blob) or ("PROYECTADO" in blob)
    if not has_act:
        findings.append({
            "code": "ocr_missing_situacional_label",
            "severity": "warning",
            "msg": "OCR no encuentra etiqueta de estado situacional/actual",
            "fix": "refill",
        })
    if not has_proy:
        findings.append({
            "code": "ocr_missing_proyectado_label",
            "severity": "error",
            "msg": "OCR no encuentra etiqueta de estado proyectado",
            "fix": "refill",
        })

    sit_kw = sit.get("kw")
    proy_kw = proy.get("kw")
    if sit_kw is not None and not _number_in_text(blob, sit_kw):
        findings.append({
            "code": "ocr_missing_sit_kw",
            "severity": "error",
            "msg": "OCR no encuentra kW situacional (%.2f)" % float(sit_kw),
            "fix": "refill",
        })
    if proy_kw is not None and not _number_in_text(blob, proy_kw):
        findings.append({
            "code": "ocr_missing_proy_kw",
            "severity": "error",
            "msg": "OCR no encuentra kW proyectado (%.2f)" % float(proy_kw),
            "fix": "refill",
        })

    # Perdidas (si hay)
    for label, m in (("situacional", sit), ("proyectado", proy)):
        loss = m.get("kw_loss")
        if loss is not None and float(loss) > 0 and not _number_in_text(blob, loss):
            findings.append({
                "code": "ocr_missing_loss_%s" % label,
                "severity": "warning",
                "msg": "OCR no encuentra perdidas kW %s (%.2f)" % (label, float(loss)),
                "fix": "refill",
            })

    # Titulos de capturas CYMDIST en el PDF
    if "CYMDIST" in blob:
        if "SITUACIONAL" not in blob and "SIN CARGA" not in blob:
            findings.append({
                "code": "ocr_missing_cymdist_sit_title",
                "severity": "warning",
                "msg": "Hay CYMDIST en OCR pero sin titulo situacional visible",
                "fix": "recapture",
            })
        if "PROYECTADO" not in blob and "CON CARGA" not in blob:
            findings.append({
                "code": "ocr_missing_cymdist_proy_title",
                "severity": "warning",
                "msg": "Hay CYMDIST en OCR pero sin titulo proyectado visible",
                "fix": "recapture",
            })
    else:
        findings.append({
            "code": "ocr_missing_cymdist_banner",
            "severity": "error",
            "msg": "OCR no detecta banners CYMDIST en mapas de coloreo",
            "fix": "recapture",
        })

    # Cuadros vacios tipicos
    if "—" in (full_text or "") or " N/D" in blob or "SIN DATO" in blob:
        # solo warning: guiones pueden ser firmas
        if blob.count(" N/D") >= 2 or "SIN DATO" in blob:
            findings.append({
                "code": "ocr_empty_cells",
                "severity": "warning",
                "msg": "OCR sugiere celdas vacias (N/D / sin dato)",
                "fix": "refill",
            })


def review_informe_pdf(settings=None, max_pages=10):
    """
    Revision unica (sin corregir). Retorna dict con findings y passed.
    """
    from pipeline.assemble_informe import informe_paths
    from pipeline.fill_informe import _load_scenarios

    s = settings or load_settings()
    paths = informe_paths(s)
    img_dir = _images_dir(s)
    scenarios = _load_scenarios(s)
    pdf_path = os.path.join(paths.get("doc_dir") or "doc", "informe.pdf")
    docx_path = paths.get("informe_doc") or os.path.join(paths.get("doc_dir") or "doc", "informe.docx")

    findings = []
    notes = []
    ocr_pages = []
    ocr_err = None

    if not os.path.isfile(pdf_path):
        findings.append({
            "code": "pdf_missing",
            "severity": "error",
            "msg": "Falta informe.pdf",
            "fix": "rerender",
        })
    else:
        ocr_pages, ocr_err = _ocr_pdf_pages(pdf_path, max_pages=max_pages)
        nchars = sum(len(p.get("text") or "") for p in ocr_pages)
        methods = sorted(set(p.get("method") or "?" for p in ocr_pages))
        notes.append("texto PDF paginas=%d chars=%d methods=%s" % (len(ocr_pages), nchars, ",".join(methods)))
        if ocr_err and nchars < 80:
            findings.append({
                "code": "ocr_failed",
                "severity": "error",
                "msg": ocr_err,
                "fix": "rerender",
            })
            notes.append("texto error: %s" % ocr_err)
        elif ocr_err:
            notes.append("aviso OCR (se uso texto nativo): %s" % ocr_err)

    full_text = "\n".join((p.get("text") or "") for p in ocr_pages)
    _check_captures(s, img_dir, findings)
    _check_docx_media(docx_path, img_dir, findings)
    if full_text:
        _check_ocr_cuadros(full_text, scenarios, findings)

    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    passed = len(errors) == 0

    result = {
        "ok": True,
        "passed": passed,
        "feeder_id": s.get("feeder_id"),
        "pdf": pdf_path if os.path.isfile(pdf_path) else None,
        "docx": docx_path if os.path.isfile(docx_path) else None,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "n_errors": len(errors),
        "n_warnings": len(warnings),
        "findings": findings,
        "notes": notes,
        "ocr_pages": [{"page": p.get("page"), "chars": len(p.get("text") or "")} for p in ocr_pages],
        "scenarios_kw": {
            "situacional": (scenarios.get("situacional") or {}).get("kw"),
            "proyectado": (scenarios.get("proyectado") or {}).get("kw"),
        },
    }
    return result


def correct_informe_word(settings, review_result):
    """
    Corrige SOLO el Word (y assets CYMDIST si hace falta).
    No exporta PDF: eso lo hace word_to_pdf_informe en el ciclo OCR.
    """
    from pipeline.fill_informe import fill_informe
    from pipeline.capture_informe_color_views import capture_informe_color_views

    s = dict(settings or load_settings())
    findings = (review_result or {}).get("findings") or []
    fixes = set(f.get("fix") for f in findings if f.get("fix"))
    actions = []
    notes = []

    if not fixes:
        # Aun sin fix tipado, rellenar Word por seguridad si el PDF fallo
        fixes = set(["refill"])

    need_recapture = "recapture" in fixes
    need_refill = True  # toda correccion pasa por Word

    if need_recapture:
        s["informe_auto_cymdist_capture"] = True
        s["force_cymdist_captures"] = True
        s["informe_prefer_cymdist_captures"] = True
        try:
            cap = capture_informe_color_views(
                settings=s,
                open_gui=bool(s.get("informe_capture_open_gui", True)),
                force=True,
            )
            actions.append("recapture_cymdist")
            notes.append(
                "recapture: gen=%d err=%d"
                % (len(cap.get("generated") or []), len(cap.get("errors") or []))
            )
        except Exception as ex:
            notes.append("recapture fallo: %s" % ex)
            return {"ok": False, "actions": actions, "notes": notes, "error": str(ex)}

    manifest = None
    if need_refill:
        # Solo Word: el PDF lo genera word_to_pdf_informe despues
        s["informe_auto_cymdist_capture"] = False
        s["force_cymdist_captures"] = False
        s["informe_skip_render"] = True
        try:
            manifest = fill_informe(s, overwrite_copy=True, require_delivery=False)
            actions.append("correct_word")
            notes.append("Word corregido ok=%s" % manifest.get("ok"))
            if not manifest.get("ok"):
                return {
                    "ok": False,
                    "actions": actions,
                    "notes": notes,
                    "error": manifest.get("error") or "fill_informe fallo",
                    "manifest": manifest,
                    "fixes_requested": sorted(fixes),
                }
        except Exception as ex:
            notes.append("correct_word fallo: %s" % ex)
            return {"ok": False, "actions": actions, "notes": notes, "error": str(ex)}

    return {
        "ok": True,
        "actions": actions,
        "notes": notes,
        "manifest": manifest,
        "fixes_requested": sorted(fixes),
        "docx": ((manifest or {}).get("paths") or {}).get("informe_doc"),
    }


def word_to_pdf_informe(settings):
    """Convierte informe.docx → informe.pdf (+ preview) para la revision OCR."""
    from pipeline.render_informe import render_informe

    s = settings or load_settings()
    try:
        rend = render_informe(s, export_pdf=True, preview_pages=True)
    except Exception as ex:
        return {"ok": False, "error": str(ex), "actions": ["word_to_pdf"], "notes": []}
    notes = list(rend.get("notes") or [])
    ok = bool(rend.get("ok") and rend.get("pdf") and os.path.isfile(rend.get("pdf")))
    if not ok and rend.get("ok") and not rend.get("pdf"):
        notes.append("Word abrio pero no se exporto PDF")
    return {
        "ok": ok,
        "actions": ["word_to_pdf"],
        "notes": notes,
        "pdf": rend.get("pdf"),
        "pages": rend.get("pages"),
        "error": None if ok else (rend.get("error") or "PDF no generado"),
        "render": rend,
    }


def apply_informe_corrections(settings, review_result):
    """
    Compat: corrige Word y luego convierte a PDF (un paso completo).
    El ciclo preferido usa correct_informe_word + word_to_pdf_informe por separado.
    """
    word = correct_informe_word(settings, review_result)
    if not word.get("ok"):
        return word
    pdf = word_to_pdf_informe(settings)
    return {
        "ok": bool(pdf.get("ok")),
        "actions": list(word.get("actions") or []) + list(pdf.get("actions") or []),
        "notes": list(word.get("notes") or []) + list(pdf.get("notes") or []),
        "manifest": word.get("manifest"),
        "fixes_requested": word.get("fixes_requested"),
        "pdf": pdf.get("pdf"),
        "error": pdf.get("error"),
    }


def review_and_correct_informe(settings=None, max_rounds=3, max_pages=10):
    """
    Ciclo estricto (hasta 3 veces)::

      1) Revisar PDF actual con OCR
      2) Si hay errores → corregir Word
      3) Convertir Word → PDF nuevo
      4) Revisar con OCR esa nueva version
      5) Repetir hasta aprobar o agotar 3 ciclos

    Cada «ronda» = revision OCR. Tras fallo: Word → PDF → siguiente revision.
    """
    s = dict(settings or load_settings())
    max_rounds = int(s.get("informe_ocr_review_rounds") or max_rounds or 3)
    max_rounds = max(1, min(3, max_rounds))

    rounds = []
    final_review = None
    passed = False
    cycle_notes = []

    # Asegurar PDF inicial desde Word si falta (antes de la 1a revision)
    from pipeline.assemble_informe import informe_paths
    paths0 = informe_paths(s)
    pdf0 = os.path.join(paths0.get("doc_dir") or "doc", "informe.pdf")
    docx0 = paths0.get("informe_doc") or os.path.join(paths0.get("doc_dir") or "doc", "informe.docx")
    if (not os.path.isfile(pdf0)) and os.path.isfile(docx0):
        cycle_notes.append("PDF ausente → Word→PDF inicial")
        boot = word_to_pdf_informe(s)
        cycle_notes.extend(boot.get("notes") or [])
        if not boot.get("ok"):
            return {
                "ok": False,
                "passed": False,
                "feeder_id": s.get("feeder_id"),
                "max_rounds": max_rounds,
                "rounds": [],
                "error": "No se pudo generar PDF inicial: %s" % (boot.get("error") or ""),
                "notes": cycle_notes,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
            }

    for i in range(1, max_rounds + 1):
        # —— 1) Revision OCR del PDF actual ——
        review = review_informe_pdf(s, max_pages=max_pages)
        final_review = review
        round_entry = {
            "round": i,
            "phase": "ocr_review",
            "passed": review.get("passed"),
            "n_errors": review.get("n_errors"),
            "n_warnings": review.get("n_warnings"),
            "findings": review.get("findings"),
            "notes": review.get("notes"),
            "pdf": review.get("pdf"),
            "correct_word": None,
            "word_to_pdf": None,
        }

        if review.get("passed"):
            passed = True
            rounds.append(round_entry)
            break

        # —— 2) Corregir Word ——
        word = correct_informe_word(s, review)
        round_entry["correct_word"] = {
            "ok": word.get("ok"),
            "actions": word.get("actions"),
            "notes": word.get("notes"),
            "error": word.get("error"),
            "fixes_requested": word.get("fixes_requested"),
        }
        if not word.get("ok"):
            rounds.append(round_entry)
            break

        # —— 3) Word → PDF nuevo ——
        pdf = word_to_pdf_informe(s)
        round_entry["word_to_pdf"] = {
            "ok": pdf.get("ok"),
            "actions": pdf.get("actions"),
            "notes": pdf.get("notes"),
            "pdf": pdf.get("pdf"),
            "pages": pdf.get("pages"),
            "error": pdf.get("error"),
        }
        rounds.append(round_entry)
        if not pdf.get("ok"):
            break

        # —— 4) Siguiente iteracion revisa el PDF nuevo ——
        # Si esta es la ultima ronda permitida, hacer revision de cierre ahora
        if i == max_rounds:
            closing = review_informe_pdf(s, max_pages=max_pages)
            final_review = closing
            passed = bool(closing.get("passed"))
            rounds.append({
                "round": "%d-cierre" % max_rounds,
                "phase": "ocr_review_cierre",
                "passed": closing.get("passed"),
                "n_errors": closing.get("n_errors"),
                "n_warnings": closing.get("n_warnings"),
                "findings": closing.get("findings"),
                "notes": list(closing.get("notes") or []) + [
                    "revision OCR del PDF tras correccion Word ronda %d" % max_rounds
                ],
                "pdf": closing.get("pdf"),
                "correct_word": None,
                "word_to_pdf": None,
            })

    out = {
        "ok": True,
        "passed": passed,
        "feeder_id": s.get("feeder_id"),
        "max_rounds": max_rounds,
        "cycle": "ocr_review → correct_word → word_to_pdf → ocr_review (x%d)" % max_rounds,
        "rounds_done": len([r for r in rounds if isinstance(r.get("round"), int)]),
        "rounds": rounds,
        "final": final_review,
        "notes": cycle_notes,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        from pipeline.assemble_informe import informe_paths
        paths = informe_paths(s)
        out_dir = paths.get("doc_dir") or "doc"
        feeder_inf = None
        try:
            base = s.get("output_dir") or os.path.join(
                "data", "output", "feeders", str(s.get("feeder_id") or "feeder")
            )
            if not os.path.isabs(base):
                from core.common import p as _p
                base = _p(*base.replace("\\", "/").split("/"))
            feeder_inf = os.path.join(base, "informe")
            mkdir(feeder_inf)
        except Exception:
            feeder_inf = None
        payload = dict(out)
        out["saved_to"] = []
        for dest in filter(None, [out_dir, feeder_inf]):
            mkdir(dest)
            path = os.path.join(dest, "review_ocr.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
            out["saved_to"].append(path)
    except Exception as ex:
        out["save_error"] = str(ex)

    return out


def main(argv=None):
    import argparse
    import sys

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        os.chdir(root)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Revision OCR rigurosa del informe PDF")
    ap.add_argument("--feeder", default=None)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--review-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    s = load_settings(feeder_id=args.feeder) if args.feeder else load_settings()
    if args.review_only:
        res = review_informe_pdf(s)
    else:
        res = review_and_correct_informe(s, max_rounds=args.rounds)

    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        print("feeder:", res.get("feeder_id"))
        print("passed:", res.get("passed"))
        if "rounds" in res:
            for r in res.get("rounds") or []:
                print(
                    " round", r.get("round"),
                    "passed=", r.get("passed"),
                    "err=", r.get("n_errors"),
                    "warn=", r.get("n_warnings"),
                    "fix=", (r.get("correction") or {}).get("actions"),
                )
        else:
            for f in (res.get("findings") or [])[:15]:
                print("-", f.get("severity"), f.get("code"), f.get("msg"))
    raise SystemExit(0 if res.get("passed") else 1)


if __name__ == "__main__":
    main()
