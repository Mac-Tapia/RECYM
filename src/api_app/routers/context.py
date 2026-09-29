# -*- coding: utf-8 -*-
from __future__ import print_function

import os
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


class TransferLoadRequest(ContextApplyRequest):
    peer_feeder_id: str
    peer_network_id: str


class TransferPrepareRequest(TransferLoadRequest):
    medicion_file: Optional[str] = None


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
        from core.cymdist_com import ensure_feeder_study_com
        from core.feeder_context import load_settings

        settings = load_settings(
            feeder_id=body.feeder_id,
            synthesize=True,
            persist_synth=False,
        )
        settings["database_mdb"] = body.database_mdb
        settings["feeder_id"] = body.feeder_id
        settings["network_id"] = body.network_id
        ensured = ensure_feeder_study_com(
            settings,
            selected_study=body.study_path,
        )
        if not isinstance(ensured, dict) or ensured.get("ok") is False:
            payload = {
                "ok": False,
                "error_code": (ensured or {}).get("error_code")
                if isinstance(ensured, dict)
                else "STUDY_ENSURE_FAILED",
                "error": (ensured or {}).get("error")
                if isinstance(ensured, dict)
                else "CYMDIST sin respuesta al verificar/crear estudio",
            }
            return JSONResponse(payload, status_code=409)

        resolved_study = ensured.get("ui_study_path") or ensured.get("study_path")
        result = apply_context_selection(
            database_mdb=body.database_mdb,
            study_path=resolved_study,
            feeder_id=body.feeder_id,
            network_id=body.network_id,
            allowed_networks=body.allowed_networks,
            strict=True,
            persist=True,
        )
        actual = dict(result)
        for key in ("database_mdb", "study_path", "feeder_id", "network_id"):
            if ensured.get(key):
                actual[key] = ensured[key]
        assert_same_context(result, actual)
        result["study_created"] = bool(ensured.get("created"))
        result["study_reused"] = bool(ensured.get("reused"))
        result["ui_study_path"] = resolved_study
        result["study_file"] = os.path.basename(resolved_study or "")
        result["cymdist_sync"] = ensured
        try:
            from pipeline.build_manufacturer_catalog import build_catalog
            catalog = build_catalog()
            result["manufacturer_catalog"] = {
                "path": "config/manufacturer_equipment_catalog.json",
                "schema_version": catalog.get("schema_version"),
                "records": len(catalog.get("records") or []),
            }
        except Exception as ex_catalog:
            result["manufacturer_catalog"] = {
                "ok": False,
                "error": str(ex_catalog),
            }
        try:
            from pipeline.fix_default_aaac_xlpe import ensure_source_catalog_for_devices
            import shutil
            from datetime import datetime
            backup_dir = os.path.join("data", "output", "system", "diagnostics", "ELD", "context_mdb_backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(
                backup_dir,
                "%s_%s.mdb" % (
                    os.path.splitext(os.path.basename(body.database_mdb))[0],
                    datetime.now().strftime("%Y%m%d_%H%M%S"),
                ),
            )
            shutil.copy2(body.database_mdb, backup_path)
            created_sources = ensure_source_catalog_for_devices(body.database_mdb, dry_run=False)
            result["source_catalog"] = {
                "ok": True,
                "created": created_sources,
                "count": len(created_sources),
                "backup": backup_path,
                "policy": "equivalente existente por tensión; OperatingVoltageA/B/C intactos",
            }
        except Exception as ex_source:
            result["source_catalog"] = {"ok": False, "error": str(ex_source)}
        if result["study_created"]:
            result["msg"] = "1.1 OK · estudio creado con %s · %s" % (
                body.network_id,
                resolved_study,
            )
        else:
            result["msg"] = "1.1 OK · estudio verificado con %s · %s" % (
                body.network_id,
                resolved_study,
            )
        return result
    except ContextIdentityError as ex:
        return JSONResponse(ex.to_dict(), status_code=409)


@router.post("/contexto/cargar-transferencia")
def context_load_transfer(body: TransferLoadRequest):
    """Open the selected study and ensure both transfer networks are loaded."""
    try:
        from core.feeder_context import load_settings
        from core.cymdist_com import (
            _loaded_feeder_ids,
            acquire_cymdist_app,
            activate_database_com,
        )

        settings = load_settings(
            feeder_id=body.feeder_id,
            synthesize=True,
            persist_synth=False,
        )
        settings.update({
            "database_mdb": body.database_mdb,
            "study_path": body.study_path,
            "ui_study_path": body.study_path,
            "feeder_id": body.feeder_id,
            "network_id": body.network_id,
        })
        app, attach_mode = acquire_cymdist_app(settings, show_window=True)
        activate_database_com(app, body.database_mdb)
        study = app.OpenStudy(body.study_path)
        before = _loaded_feeder_ids(app)
        if body.peer_network_id not in before:
            study.LoadNetworkFromID(body.peer_network_id)
        after = _loaded_feeder_ids(app)
        ok = body.network_id in after and body.peer_network_id in after
        return {
            "ok": ok,
            "primary_feeder_id": body.feeder_id,
            "primary_network_id": body.network_id,
            "peer_feeder_id": body.peer_feeder_id,
            "peer_network_id": body.peer_network_id,
            "study_path": body.study_path,
            "database_mdb": body.database_mdb,
            "loaded_networks_before": before,
            "loaded_networks": after,
            "attach_mode": attach_mode,
            "msg": "Par de transferencia cargado en CYMDIST" if ok else "No se pudieron cargar ambas redes",
        }
    except Exception as ex:
        return JSONResponse({"ok": False, "error": str(ex)}, status_code=409)


@router.post("/contexto/preparar-transferencia")
def context_prepare_transfer(body: TransferPrepareRequest):
    """Load both networks and write maximum demand before module 5."""
    loaded = context_load_transfer(body)
    if isinstance(loaded, JSONResponse):
        return loaded
    if not loaded.get("ok"):
        return JSONResponse(loaded, status_code=409)
    try:
        from core.feeder_context import load_settings
        from pipeline.apply_max_demand_multi import apply_max_demand_multi

        settings = load_settings(
            feeder_id=body.feeder_id,
            synthesize=True,
            persist_synth=False,
        )
        settings.update({
            "database_mdb": body.database_mdb,
            "study_path": body.study_path,
            "ui_study_path": body.study_path,
            "feeder_id": body.feeder_id,
            "network_id": body.network_id,
            "network_ids": [body.network_id, body.peer_network_id],
            "transfer_pair": [body.feeder_id, body.peer_feeder_id],
        })
        result = apply_max_demand_multi(
            settings,
            network_ids=settings["network_ids"],
            medicion_file=body.medicion_file,
            write_cymdist=True,
            save=True,
            run_allocation=True,
        )
        return {
            **loaded,
            "prepared": bool(result.get("ok")),
            "max_demand": result,
            "network_ids": settings["network_ids"],
            "transfer_pair": settings["transfer_pair"],
            "msg": (
                "Par cargado y máxima demanda actualizada en ambos alimentadores"
                if result.get("ok")
                else result.get("error") or "No se pudo preparar la transferencia"
            ),
        }
    except Exception as ex:
        return JSONResponse(
            {"ok": False, "prepared": False, "error": str(ex)},
            status_code=409,
        )


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
