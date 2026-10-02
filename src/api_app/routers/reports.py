# -*- coding: utf-8 -*-
"""Descargas de reportes generados por jobs (§3 distribución de carga)."""
from __future__ import print_function

import os
from typing import Optional

from fastapi import APIRouter, Header, Query
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def distribution_report_path(feeder_id):
    from core.feeder_context import load_settings, output_path

    fid = str(feeder_id or "").strip().upper()
    settings = load_settings(feeder_id=fid, synthesize=True, persist_synth=False)
    return output_path(settings, "clientes", "distribucion_carga_%s.xlsx" % fid)


@router.get("/clientes/distribucion/archivo")
def download_distribution_report(
    feeder: Optional[str] = Query(None),
    x_feeder: Optional[str] = Header(None, alias="X-Feeder"),
):
    fid = str(feeder or x_feeder or "").strip().upper()
    if not fid:
        return JSONResponse({"ok": False, "error": "Falta alimentador"}, status_code=400)
    path = distribution_report_path(fid)
    if not os.path.isfile(path):
        return JSONResponse(
            {"ok": False, "error": "Aún no hay reporte de distribución para %s: genérelo tras 3.3" % fid},
            status_code=404,
        )
    return FileResponse(path, media_type=XLSX_MEDIA, filename=os.path.basename(path))
