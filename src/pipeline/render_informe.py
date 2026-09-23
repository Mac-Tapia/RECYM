# -*- coding: utf-8 -*-
"""
Render final del informe.docx con Microsoft Word (COM).

Tras rellenar XML a mano, Word debe abrir el documento para:
  - actualizar campos (paginas, TOC, fechas)
  - repaginar
  - guardar layout limpio
  - exportar PDF de entrega (opcional)

Uso:
  render_informe_docx(r"doc/informe.docx", export_pdf=True)
"""
from __future__ import print_function
import os
import time
from datetime import datetime


def _abs(path):
    return os.path.abspath(path)


def render_informe_docx(docx_path, export_pdf=True, pdf_path=None, visible=False, timeout_s=120):
    """
    Abre el .docx en Word, actualiza campos, repagina, guarda y opcionalmente PDF.

    Returns dict: ok, docx, pdf, pages, notes, error
    """
    notes = []
    result = {
        "ok": False,
        "docx": docx_path,
        "pdf": None,
        "pages": None,
        "rendered_at": datetime.now().isoformat(timespec="seconds"),
        "notes": notes,
        "error": None,
    }
    if not docx_path or not os.path.isfile(docx_path):
        result["error"] = "informe.docx no encontrado: %s" % docx_path
        return result

    docx_abs = _abs(docx_path)
    if export_pdf:
        pdf_path = pdf_path or (os.path.splitext(docx_abs)[0] + ".pdf")
        pdf_abs = _abs(pdf_path)
    else:
        pdf_abs = None

    word = None
    doc = None
    try:
        import comtypes.client
    except Exception as ex:
        result["error"] = "comtypes no disponible: %s" % ex
        return result

    try:
        word = comtypes.client.CreateObject("Word.Application")
        word.Visible = bool(visible)
        try:
            word.DisplayAlerts = 0  # wdAlertsNone
        except Exception:
            pass

        # ConfirmConversions=False, ReadOnly=False, AddToRecentFiles=False
        doc = word.Documents.Open(docx_abs, False, False, False)
        notes.append("Word abrio %s" % os.path.basename(docx_abs))

        try:
            doc.Fields.Update()
            notes.append("Fields.Update")
        except Exception as ex:
            notes.append("aviso Fields.Update: %s" % ex)

        try:
            for i in range(1, int(doc.TablesOfContents.Count) + 1):
                doc.TablesOfContents(i).Update()
            if int(doc.TablesOfContents.Count) > 0:
                notes.append("TOC actualizado (%d)" % int(doc.TablesOfContents.Count))
        except Exception as ex:
            notes.append("aviso TOC: %s" % ex)

        try:
            doc.Repaginate()
            pages = int(doc.ComputeStatistics(2))  # wdStatisticPages = 2
            result["pages"] = pages
            notes.append("paginas=%d" % pages)
        except Exception as ex:
            notes.append("aviso Repaginate: %s" % ex)

        # No hacer doc.Save() sobre el .docx de entrega: Word reescribe drawings
        # y puede eliminar image9/image10 (mapa proyectado / trafo). El PDF se
        # exporta desde la vista en memoria; el .docx XML-filled se preserva.
        if pdf_abs:
            try:
                # wdExportFormatPDF = 17
                doc.ExportAsFixedFormat(
                    pdf_abs,
                    17,  # ExportFormat
                    False,  # OpenAfterExport
                    0,  # OptimizeFor = wdExportOptimizeForPrint
                    0,  # Range = wdExportAllDocument
                    1,  # From
                    1,  # To
                    0,  # Item = wdExportDocumentContent
                    True,  # IncludeDocProps
                    True,  # KeepIRM
                    0,  # CreateBookmarks = wdExportCreateNoBookmarks
                    True,  # DocStructureTags
                    True,  # BitmapMissingFonts
                    False,  # UseISO19005_1
                )
                if os.path.isfile(pdf_abs):
                    result["pdf"] = pdf_abs
                    notes.append("pdf exportado (%d bytes)" % os.path.getsize(pdf_abs))
                else:
                    notes.append("aviso: ExportAsFixedFormat sin archivo")
            except Exception as ex:
                # Fallback SaveAs2 wdFormatPDF=17 (solo escribe el PDF)
                try:
                    doc.SaveAs2(pdf_abs, FileFormat=17)
                    if os.path.isfile(pdf_abs):
                        result["pdf"] = pdf_abs
                        notes.append("pdf via SaveAs2 (%d bytes)" % os.path.getsize(pdf_abs))
                    else:
                        notes.append("aviso SaveAs2 PDF fallo: %s" % ex)
                except Exception as ex2:
                    notes.append("aviso PDF: %s | %s" % (ex, ex2))

        notes.append("docx preservado (sin Word.Save)")
        result["ok"] = True
        result["docx"] = docx_abs
        return result
    except Exception as ex:
        result["error"] = str(ex)
        notes.append("error: %s" % ex)
        return result
    finally:
        try:
            if doc is not None:
                doc.Close(False)  # wdDoNotSaveChanges — no pisar layout XML
        except Exception:
            pass
        try:
            if word is not None:
                word.Quit()
        except Exception:
            pass
        # Liberar COM
        try:
            import gc
            doc = None
            word = None
            gc.collect()
            time.sleep(0.3)
        except Exception:
            pass


def render_pages_preview(pdf_path, out_dir, dpi=110, max_pages=12):
    """
    Rasteriza paginas del PDF a JPEG para vista preliminar / QA visual.
    Requiere pdf2image + Poppler. Si no hay Poppler, retorna ok=False sin romper.
    """
    out = {
        "ok": False,
        "pages": [],
        "out_dir": out_dir,
        "error": None,
    }
    if not pdf_path or not os.path.isfile(pdf_path):
        out["error"] = "PDF no encontrado"
        return out
    try:
        from pdf2image import convert_from_path
    except Exception as ex:
        out["error"] = "pdf2image no disponible: %s" % ex
        return out

    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    try:
        images = convert_from_path(pdf_path, dpi=dpi, first_page=1, last_page=max_pages)
    except Exception as ex:
        out["error"] = "rasterize fallo (¿Poppler?): %s" % ex
        return out

    pages = []
    for i, img in enumerate(images, start=1):
        name = "informe_p%02d.jpg" % i
        path = os.path.join(out_dir, name)
        img.convert("RGB").save(path, "JPEG", quality=85)
        pages.append({"page": i, "name": name, "path": path, "bytes": os.path.getsize(path)})
    out["ok"] = True
    out["pages"] = pages
    return out


def render_informe(settings=None, export_pdf=True, preview_pages=True):
    """Render completo: Word → PDF → JPEGs (si Poppler disponible)."""
    from pipeline.assemble_informe import informe_paths
    from core.common import mkdir

    paths = informe_paths(settings)
    docx = paths["informe_doc"]
    pdf = os.path.join(paths["doc_dir"], "informe.pdf")
    prev_dir = os.path.join(paths["doc_dir"], "informe_preview")

    res = render_informe_docx(docx, export_pdf=export_pdf, pdf_path=pdf)
    if res.get("ok") and preview_pages and res.get("pdf"):
        mkdir(prev_dir)
        prev = render_pages_preview(res["pdf"], prev_dir)
        res["preview"] = prev
        if prev.get("ok"):
            res["notes"].append("preview pages: %d" % len(prev.get("pages") or []))
        elif prev.get("error"):
            res["notes"].append("aviso preview: %s" % prev["error"])
    return res


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    r = render_informe()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    if not r.get("ok"):
        raise SystemExit(1)
