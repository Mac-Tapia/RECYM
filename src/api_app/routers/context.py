# -*- coding: utf-8 -*-
from __future__ import print_function

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api_app.security import require_loopback
from core.windows_file_picker import pick_context_file
from core.context_identity import ContextIdentityError, assert_same_context
from core.feeder_context import apply_context_selection, quick_context_catalog
from core.common import load_json


router = APIRouter()


class ContextPickRequest(BaseModel):
    kind: str
    initial_dir: Optional[str] = None


class ContextApplyRequest(BaseModel):
    database_mdb: str
    study_path: str
    feeder_id: str
    network_id: str
    allowed_networks: List[Dict[str, Any]]


@router.get("/contexto/archivos")
def context_files(database_mdb: Optional[str] = None, study_path: Optional[str] = None):
    settings = load_json("config/settings.json")
    return quick_context_catalog(
        settings,
        selected_database=database_mdb,
        selected_study=study_path,
    )


@router.post("/contexto/aplicar")
def context_apply(body: ContextApplyRequest):
    try:
        result = apply_context_selection(
            database_mdb=body.database_mdb,
            study_path=body.study_path,
            feeder_id=body.feeder_id,
            network_id=body.network_id,
            allowed_networks=body.allowed_networks,
            strict=True,
            persist=True,
        )
        from core.cymdist_com import open_cymdist_gui
        from core.feeder_context import load_settings

        settings = load_settings(feeder_id=result["feeder_id"], synthesize=False)
        for key in (
            "database_mdb",
            "study_path",
            "ui_study_path",
            "feeder_id",
            "network_id",
            "database_connection_name",
        ):
            settings[key] = result.get(key)
        connected = open_cymdist_gui(settings, kill_existing=False, reason="contexto_aplicar_1")
        if not isinstance(connected, dict) or connected.get("ok") is False:
            payload = {
                "ok": False,
                "error_code": "CYMDIST_CONTEXT_OPEN_FAILED",
                "error": (connected or {}).get("error") if isinstance(connected, dict) else "CYMDIST sin respuesta",
                "context_fingerprint": result.get("context_fingerprint"),
            }
            return JSONResponse(payload, status_code=409)
        actual = dict(result)
        for key in ("database_mdb", "study_path", "feeder_id", "network_id"):
            if connected.get(key):
                actual[key] = connected[key]
        assert_same_context(result, actual)
        result["cymdist_sync"] = connected
        return result
    except ContextIdentityError as ex:
        return JSONResponse(ex.to_dict(), status_code=409)


@router.post("/contexto/examinar")
async def context_pick(body: ContextPickRequest, request: Request):
    require_loopback(request)
    kind = str(body.kind or "").strip().lower()
    if kind not in ("database", "study"):
        return JSONResponse(
            {
                "ok": False,
                "error_code": "INVALID_PICKER_KIND",
                "error": "Tipo de selector inválido: %s" % kind,
            },
            status_code=400,
        )
    result = await run_in_threadpool(
        pick_context_file,
        kind,
        body.initial_dir,
        600,
    )
    status = 200 if result.get("ok") else 400
    return JSONResponse(result, status_code=status)
