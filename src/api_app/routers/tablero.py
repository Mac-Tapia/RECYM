# -*- coding: utf-8 -*-
"""GET /api/tablero — JSON vivo (reemplaza tablero.html como producto)."""
from __future__ import print_function

import json
import os
import time

from fastapi import APIRouter, Header, Query
from typing import Optional

router = APIRouter()


@router.get("/tablero")
def api_tablero(
    x_feeder: Optional[str] = Header(None, alias="X-Feeder"),
    rebuild: int = Query(0),
    refresh_diag: int = Query(0),
    clear: int = Query(0),
    seed_loads: int = Query(0),
):
    """Devuelve tablero.json del alimentador activo (X-Feeder / estudio §1).

    clear=1: borra diagnósticos y deja códigos/errores en 0 (hasta 2.1).
    rebuild=1: regenera clientes + tablero desde archivos de diagnóstico.
    seed_loads=1: fuerza tabla Incluir desde inventario SpotLoad de ESE feeder
      (universal: IN112, PA217, cualquier radial de la BD).
    refresh_diag=1: además re-ejecuta NetworkDiagnostic → columna «después».
    """
    from core.feeder_context import load_settings, output_path
    from core.common import ts

    s = load_settings(feeder_id=x_feeder, synthesize=True) if x_feeder else load_settings()
    out_json = output_path(s, "diagnostics", "tablero.json")
    do_clear = bool(clear)
    do_seed = bool(seed_loads)
    do_diag = bool(refresh_diag) and not do_clear
    do_rebuild = (
        bool(rebuild)
        or bool(refresh_diag)
        or do_clear
        or do_seed
        or not os.path.isfile(out_json)
    )

    if do_seed:
        try:
            from core.clientes_suministro import ensure_clientes_table
            if x_feeder:
                os.environ["RECYM_FEEDER"] = str(x_feeder)
            ensure_clientes_table(s, force_inventory=True, open_cymdist=True)
            do_rebuild = True
        except Exception as ex:
            return {
                "ok": False,
                "error": "No se pudo cargar SpotLoads del alimentador %s: %s"
                % (s.get("feeder_id"), ex),
            }

    diag_meta = None
    if do_clear:
        try:
            from analysis.build_dashboard import clear_tablero_diagnostics
            if x_feeder:
                os.environ["RECYM_FEEDER"] = str(x_feeder)
            clear_info = clear_tablero_diagnostics(s, rebuild=True)
            diag_meta = {"ok": True, "cleared": True, "cleared_files": clear_info.get("cleared")}
            do_rebuild = False  # ya regenerado (soft siembra inventario si falta)
        except Exception as ex:
            return {
                "ok": False,
                "error": "No se pudo vaciar tablero: %s" % ex,
            }

    if do_rebuild:
        if do_diag:
            try:
                diag_meta = _refresh_diagnostic(s)
            except Exception as ex:
                diag_meta = {"ok": False, "error": str(ex)}
        try:
            from analysis.build_dashboard import main as build_tablero
            if x_feeder:
                os.environ["RECYM_FEEDER"] = str(x_feeder)
            build_tablero(s)
        except Exception as ex:
            return {
                "ok": False,
                "error": "No se pudo generar tablero: %s" % ex,
                "diag": diag_meta,
            }

    if not os.path.isfile(out_json):
        return {"ok": False, "error": "tablero.json no encontrado", "path": out_json}

    with open(out_json, "r", encoding="utf-8") as f:
        board = json.load(f)

    # Tablero viejo vacío pero hay inventario → resembrar (cambio de estudio)
    cli = board.get("clientes") or {}
    if not do_clear and int(cli.get("n") or 0) == 0 and not (cli.get("rows") or []):
        try:
            from core.clientes_suministro import ensure_clientes_table
            from analysis.build_dashboard import main as build_tablero
            rows, _meta, _p = ensure_clientes_table(s, force_inventory=False)
            if rows:
                if x_feeder:
                    os.environ["RECYM_FEEDER"] = str(x_feeder)
                build_tablero(s)
                with open(out_json, "r", encoding="utf-8") as f:
                    board = json.load(f)
        except Exception as ex:
            board.setdefault("clientes", {})
            board["clientes"]["seed_error"] = str(ex)

    board["ok"] = True
    board["path"] = out_json
    board["refreshed_at"] = ts()
    board["server_time"] = time.time()
    if diag_meta is not None:
        board["diag_refresh"] = diag_meta
    return board


def _refresh_diagnostic(settings):
    """Re-ejecuta NetworkDiagnostic y escribe summary before/after.

    - Si no hay «antes», corre y lo guarda como before.
    - Siempre corre de nuevo y guarda como after (estado vivo del tablero).
    """
    from pipeline.model_quality_gate import run_network_diagnostic, with_cympy_lock
    from core.feeder_context import output_path
    import os

    s = settings
    before_path = output_path(s, "diagnostics", "dashboard_summary.json")
    need_before = not os.path.isfile(before_path)

    def _run():
        info = {"ok": True, "before_ran": False, "after_ran": False}
        if need_before:
            r0 = run_network_diagnostic(s, suffix="")
            info["before_ran"] = True
            info["before"] = (r0.get("summary") or {})
        r1 = run_network_diagnostic(s, suffix="after")
        info["after_ran"] = True
        info["after"] = (r1.get("summary") or {})
        info["n_problems"] = (r1.get("summary") or {}).get("n_problems")
        info["total_messages"] = (r1.get("summary") or {}).get("total_messages")
        info["by_code"] = (r1.get("summary") or {}).get("by_code")
        return info

    # Timeout amplio: NetworkDiagnostic + Save puede superar 2s
    result = with_cympy_lock("tablero_refresh_diag", _run, timeout_sec=120.0)
    return result
