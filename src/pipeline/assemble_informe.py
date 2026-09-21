# -*- coding: utf-8 -*-
"""
Arma copias de entrega del informe (Word + Excel) sin alterar formato ni numerales.

Fuente plantilla : data/output/informe/{informe.docx, justificacion.xlsx}
Destino entrega  : doc/{informe.docx, justificacion.xlsx}
Resultados flujo : data/output/feeders/<ID>/demand/loadflow_*.json
"""
from __future__ import print_function
import json
import os
import shutil
from datetime import datetime

from core.common import mkdir, p
from core.feeder_context import load_settings, output_path

TEMPLATE_DIR = p("data", "output", "informe")
DOC_DIR = p("doc")
TEMPLATE_FILES = ("informe.docx", "justificacion.xlsx")


def _paths():
    return {
        "plantilla_dir": TEMPLATE_DIR,
        "doc_dir": DOC_DIR,
        "informe_plantilla": os.path.join(TEMPLATE_DIR, "informe.docx"),
        "justificacion_plantilla": os.path.join(TEMPLATE_DIR, "justificacion.xlsx"),
        "informe_doc": os.path.join(DOC_DIR, "informe.docx"),
        "justificacion_doc": os.path.join(DOC_DIR, "justificacion.xlsx"),
    }


def informe_paths(settings=None):
    """Rutas absolutas visibles en la UI."""
    s = settings or load_settings()
    base = _paths()
    feeder = s.get("feeder_id") or "?"
    return {
        "feeder_id": feeder,
        "plantilla_dir": base["plantilla_dir"],
        "doc_dir": base["doc_dir"],
        "informe_plantilla": base["informe_plantilla"],
        "justificacion_plantilla": base["justificacion_plantilla"],
        "informe_doc": base["informe_doc"],
        "justificacion_doc": base["justificacion_doc"],
        "loadflow_situacional": output_path(s, "demand", "loadflow_situacional.json"),
        "loadflow_proyectado": output_path(s, "demand", "loadflow_proyectado.json"),
        "loadflow_result": output_path(s, "demand", "loadflow_result.json"),
        "assemble_manifest": os.path.join(base["doc_dir"], "assemble_manifest.json"),
    }


def assemble_informe(settings=None, overwrite=True):
    """
    Copia byte-a-byte plantillas → doc/, preservando formato, numerales e imagenes.
    No reescribe el contenido del Word/Excel (solo copia).
    """
    s = settings or load_settings()
    paths = informe_paths(s)
    mkdir(paths["doc_dir"])

    copied = []
    missing = []
    for name in TEMPLATE_FILES:
        src = os.path.join(paths["plantilla_dir"], name)
        dst = os.path.join(paths["doc_dir"], name)
        if not os.path.isfile(src):
            missing.append(src)
            continue
        if (not overwrite) and os.path.isfile(dst):
            copied.append({"name": name, "src": src, "dst": dst, "action": "skipped_exists"})
            continue
        shutil.copy2(src, dst)
        copied.append({
            "name": name,
            "src": src,
            "dst": dst,
            "bytes": os.path.getsize(dst),
            "action": "copied",
        })

    if missing:
        return {
            "ok": False,
            "error": "Faltan plantillas en data/output/informe: %s" % "; ".join(missing),
            "paths": paths,
            "copied": copied,
        }

    manifest = {
        "ok": True,
        "feeder_id": s.get("feeder_id"),
        "assembled_at": datetime.now().isoformat(timespec="seconds"),
        "note": (
            "Copia sin alterar formato ni numerales. "
            "Imagenes del .docx se preservan embebidas. "
            "Rellenar tablas con resultados de loadflow_situacional / loadflow_proyectado."
        ),
        "paths": paths,
        "copied": copied,
        "scenarios": {
            "situacional": _read_json_if(paths["loadflow_situacional"]),
            "proyectado": _read_json_if(paths["loadflow_proyectado"]),
        },
    }
    with open(paths["assemble_manifest"], "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("[informe] Guardado en:", paths["doc_dir"])
    for c in copied:
        print("  -", c["dst"])
    return manifest


def _read_json_if(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as ex:
        return {"error": str(ex)}


def main():
    m = assemble_informe()
    print(json.dumps(m, indent=2, ensure_ascii=False, default=str))
    if not m.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
