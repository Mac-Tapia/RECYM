# -*- coding: utf-8 -*-
"""
Arma copias de entrega del informe (Word + Excel) SIN alterar los modelos.

Fuente MODELO (solo lectura):
  data/input/InformeModelo/InformeModelo.docx
  data/input/InformeModelo/informeModelo.xlsx

Destino entrega (copias rellenables):
  doc/informe.docx
  doc/justificacion.xlsx

Nunca escribe en data/input/InformeModelo/.
"""
from __future__ import print_function
import json
import os
import shutil
from datetime import datetime

from core.common import mkdir, p
from core.feeder_context import load_settings, output_path
from core.report_provenance import (
    assert_report_context,
    copy_audit_artifacts,
    context_metadata,
    tag_context,
)

# Modelos oficiales (inmutables)
MODELO_DIR = p("data", "input", "InformeModelo")
MODELO_WORD = "InformeModelo.docx"
MODELO_EXCEL = "informeModelo.xlsx"

# Compat: plantilla legacy en data/output/informe (fallback)
LEGACY_TEMPLATE_DIR = p("data", "output", "informe")
DOC_DIR = p("doc")

# Nombres de entrega (UI / API)
DELIVERY_WORD = "informe.docx"
DELIVERY_EXCEL = "justificacion.xlsx"

# Alias públicos usados por fill_informe
TEMPLATE_DIR = MODELO_DIR
TEMPLATE_FILES = (DELIVERY_WORD, DELIVERY_EXCEL)


def _modelo_sources():
    """Rutas absolutas de los modelos de entrada (nunca se sobrescriben)."""
    word = os.path.join(MODELO_DIR, MODELO_WORD)
    excel = os.path.join(MODELO_DIR, MODELO_EXCEL)
    # Fallback legacy si falta el modelo nuevo
    if not os.path.isfile(word):
        word = os.path.join(LEGACY_TEMPLATE_DIR, "informe.docx")
    if not os.path.isfile(excel):
        excel = os.path.join(LEGACY_TEMPLATE_DIR, "justificacion.xlsx")
    return {"word": word, "excel": excel}


def _paths():
    src = _modelo_sources()
    return {
        "plantilla_dir": MODELO_DIR,
        "modelo_dir": MODELO_DIR,
        "doc_dir": DOC_DIR,
        "informe_plantilla": src["word"],
        "justificacion_plantilla": src["excel"],
        "informe_doc": os.path.join(DOC_DIR, DELIVERY_WORD),
        "justificacion_doc": os.path.join(DOC_DIR, DELIVERY_EXCEL),
    }


def informe_paths(settings=None):
    """Rutas absolutas visibles en la UI."""
    s = settings or load_settings()
    base = _paths()
    feeder = s.get("feeder_id") or "?"
    feeder_out = output_path(s, "informe")
    _identity, fingerprint = context_metadata(s)
    audit_dir = os.path.join(feeder_out, fingerprint)
    return {
        "feeder_id": feeder,
        "plantilla_dir": base["plantilla_dir"],
        "modelo_dir": base["modelo_dir"],
        "doc_dir": base["doc_dir"],
        "informe_plantilla": base["informe_plantilla"],
        "justificacion_plantilla": base["justificacion_plantilla"],
        "informe_doc": base["informe_doc"],
        "justificacion_doc": base["justificacion_doc"],
        # Copia por alimentador (auditoría; no sustituye doc/)
        "informe_feeder_doc": os.path.join(feeder_out, DELIVERY_WORD),
        "justificacion_feeder_doc": os.path.join(feeder_out, DELIVERY_EXCEL),
        "loadflow_situacional": output_path(s, "demand", "loadflow_situacional.json"),
        "loadflow_proyectado": output_path(s, "demand", "loadflow_proyectado.json"),
        "loadflow_result": output_path(s, "demand", "loadflow_result.json"),
        "assemble_manifest": os.path.join(base["doc_dir"], "assemble_manifest.json"),
        "audit_dir": audit_dir,
        "audit_assemble_manifest": os.path.join(audit_dir, "assemble_manifest.json"),
        "audit_fill_manifest": os.path.join(audit_dir, "fill_manifest.json"),
    }


def assemble_informe(settings=None, overwrite=True):
    """
    Copia byte-a-byte MODELO → doc/ (y espejo por feeder), preservando
    formato, numerales, formulas e imagenes. Nunca toca data/input/InformeModelo.
    """
    s = settings or load_settings()
    paths = informe_paths(s)
    mkdir(paths["doc_dir"])
    feeder_dir = os.path.dirname(paths["informe_feeder_doc"])
    mkdir(feeder_dir)

    src_map = [
        (paths["informe_plantilla"], paths["informe_doc"], paths["informe_feeder_doc"]),
        (paths["justificacion_plantilla"], paths["justificacion_doc"], paths["justificacion_feeder_doc"]),
    ]

    copied = []
    missing = []
    for src, dst_doc, dst_feeder in src_map:
        name = os.path.basename(dst_doc)
        if not os.path.isfile(src):
            missing.append(src)
            continue
        if (not overwrite) and os.path.isfile(dst_doc):
            copied.append({"name": name, "src": src, "dst": dst_doc, "action": "skipped_exists"})
            continue
        shutil.copy2(src, dst_doc)
        try:
            shutil.copy2(src, dst_feeder)
        except Exception:
            pass
        copied.append({
            "name": name,
            "src": src,
            "dst": dst_doc,
            "feeder_copy": dst_feeder,
            "bytes": os.path.getsize(dst_doc),
            "action": "copied_from_modelo",
        })

    if missing:
        return {
            "ok": False,
            "error": "Faltan modelos en data/input/InformeModelo: %s" % "; ".join(missing),
            "paths": paths,
            "copied": copied,
        }

    audit = copy_audit_artifacts(
        s,
        paths["audit_dir"],
        [paths["informe_doc"], paths["justificacion_doc"]],
    )
    manifest = tag_context(s, {
        "ok": True,
        "feeder_id": s.get("feeder_id"),
        "assembled_at": datetime.now().isoformat(timespec="seconds"),
        "note": (
            "Copia desde InformeModelo (input). Modelos originales intactos. "
            "Rellenar solo entradas LF situacional/proyectado; formulas se mantienen."
        ),
        "modelo_dir": MODELO_DIR,
        "paths": paths,
        "copied": copied,
        "audit": audit,
    })
    with open(paths["assemble_manifest"], "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    mkdir(paths["audit_dir"])
    with open(paths["audit_assemble_manifest"], "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


def main():
    import json as _json
    r = assemble_informe(overwrite=True)
    print(_json.dumps(r, indent=2, ensure_ascii=False, default=str))
    if not r.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
