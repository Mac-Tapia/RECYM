# -*- coding: utf-8 -*-
"""API v2 Campaign §§1–7 (RECYM arquitectura v7)."""
from __future__ import print_function

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import ledger, orchestrator
from domain.campaign import STEPS, campaign_summary

router = APIRouter(prefix="/api/v2", tags=["campaign-v7"])


class CommandBody(BaseModel):
    command: str
    params: Optional[Dict[str, Any]] = None
    binding: Optional[Dict[str, Any]] = None
    # Si true, dispara el job legacy automáticamente
    dispatch: bool = True

    class Config:
        extra = "allow"


@router.get("/campaigns/{feeder}")
def get_campaign(feeder: str):
    camp = orchestrator.get_campaign(feeder)
    return {"ok": True, "campaign": campaign_summary(camp), "catalog": [
        {"step_id": a, "command": b, "queue": c, "title": d}
        for a, b, c, d in STEPS
    ]}


@router.post("/campaigns/{feeder}/skip-spot")
def skip_spot(feeder: str):
    """Marca §4 como skipped (opcional)."""
    summary = orchestrator.skip_optional_spot(feeder)
    return {"ok": True, "campaign": summary}


@router.post("/campaigns/{feeder}/commands")
def post_command(feeder: str, body: CommandBody):
    """
    Encola un command tipado. Si dispatch=true y hay action legacy,
    crea el job vía api_app.jobs.start_job interno.
    """
    params = dict(body.params or {})
    # Scenario en RunLoadFlow
    if body.command == "RunLoadFlow" and "scenario" not in params:
        params["scenario"] = None

    prepared = orchestrator.enqueue_command(
        feeder, body.command, params=params, binding=body.binding
    )
    if not prepared.get("ok"):
        raise HTTPException(400, prepared.get("error") or "Command rechazado")

    dispatched = None
    if body.dispatch and prepared.get("action"):
        try:
            from api_app import jobs as jobs_mod

            # Reutilizar create path sin doble registro: marcar job_id conocido
            action = prepared["action"]
            payload = dict(params)
            # Inyectar job pre-creado: start via thread with fixed id
            dispatched = _dispatch_legacy(
                jobs_mod,
                prepared["job_id"],
                action,
                payload,
                feeder,
            )
        except Exception as ex:
            dispatched = {"ok": False, "error": str(ex)}

    return {
        "ok": True,
        "job_id": prepared["job_id"],
        "step_id": prepared["step_id"],
        "action": prepared.get("action"),
        "queue": prepared.get("queue"),
        "campaign_id": prepared.get("campaign_id"),
        "dispatched": dispatched,
    }


def _dispatch_legacy(jobs_mod, job_id, action, payload, feeder):
    """Arranca worker legacy usando job_id del ledger."""
    import threading

    # Sembrar job en memoria para SSE legacy
    jobs_mod._set_job(
        job_id,
        id=job_id,
        status="queued",
        action=action,
        feeder=feeder,
        message="queued",
        result=None,
    )
    # Evitar doble register_legacy_job: el worker ya tiene job_id en ledger
    t = threading.Thread(
        target=_worker_with_ledger,
        args=(jobs_mod, job_id, action, payload, feeder),
        name="job-%s" % job_id,
        daemon=True,
    )
    t.start()
    return {"ok": True, "job_id": job_id, "status": "queued"}


def _worker_with_ledger(jobs_mod, job_id, action, payload, feeder):
    from app.orchestrator import complete_legacy_job
    from app import ledger as led

    jobs_mod._set_job(job_id, status="running", message="Ejecutando %s…" % action)
    led.update_job(job_id, status="running", message="Ejecutando %s…" % action)
    try:
        payload = dict(payload or {})
        payload["_job_id"] = job_id
        use_iso = False
        try:
            from core.cympy_isolation import should_isolate_action, run_job_action_isolated
            use_iso = should_isolate_action(action)
        except Exception:
            use_iso = False

        if use_iso:
            def _prog(msg):
                try:
                    jobs_mod._set_job(job_id, message=msg)
                    led.update_job(job_id, message=msg)
                except Exception:
                    pass

            timeout = 900.0 if action in (
                "distribucion", "flujo", "calidad_hasta_limpio",
                "calidad_sistema", "calidad_eld",
            ) else 600.0
            result = run_job_action_isolated(
                action,
                payload=payload,
                feeder=feeder,
                timeout=timeout,
                progress_cb=_prog,
            )
        else:
            result = jobs_mod._run_action(action, payload, feeder, job_id=job_id)

        ok = True
        if isinstance(result, dict) and result.get("ok") is False:
            ok = False
        msg = "Listo"
        if isinstance(result, dict):
            msg = result.get("msg") or result.get("error") or ("Listo" if ok else "Error")
        jobs_mod._set_job(
            job_id,
            status="ok" if ok else "error",
            message=msg,
            result=result,
        )
        complete_legacy_job(
            job_id,
            ok=ok,
            result=result,
            error=None if ok else (result.get("error") if isinstance(result, dict) else str(result)),
            message=msg,
        )
    except Exception as ex:
        jobs_mod._set_job(
            job_id,
            status="error",
            message=str(ex),
            result={"ok": False, "error": str(ex)},
        )
        complete_legacy_job(job_id, ok=False, error=str(ex), message=str(ex))


@router.get("/jobs/{job_id}")
def get_v2_job(job_id: str):
    job = ledger.load_job(job_id)
    if not job:
        raise HTTPException(404, "job no encontrado")
    return {"ok": True, "job": job}
