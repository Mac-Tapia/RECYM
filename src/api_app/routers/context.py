# -*- coding: utf-8 -*-
from __future__ import print_function

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from api_app.security import require_loopback
from core.windows_file_picker import pick_context_file


router = APIRouter()


class ContextPickRequest(BaseModel):
    kind: str
    initial_dir: Optional[str] = None


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
