# -*- coding: utf-8 -*-
"""
CampaignOrchestrator v7 — gates + enlace a jobs legacy / ledger.

Fase 1: no exige Redis. Persiste Campaign/Job en SQLite y delega la
ejecución al runner existente (aislamiento CymPy). Dramatiq queda como
evolución cuando el runtime sea ≥3.8.
"""
from __future__ import print_function

import os

from domain.campaign import (
    can_run_step,
    evaluate_gates,
    mark_step,
    resolve_step_for_action,
    resolve_step_for_command,
    step_meta,
    campaign_summary,
    STEP_OK,
    STEP_ERROR,
    STEP_RUNNING,
    STEP_SKIPPED,
)
from app import ledger


def _artifacts_for_feeder(feeder_id, settings=None):
    """Detecta artefactos en disco para gates."""
    art = {
        "has_spot_loads": False,
        "lf_situacional_ok": False,
        "lf_proyectado_ok": False,
        "tabla_ok": False,
        "ea_pot_ok": False,
    }
    try:
        from core.feeder_context import load_settings, output_path
        s = settings or load_settings(feeder_id=feeder_id, synthesize=True)
        spot = output_path(s, "loads", "new_spot_loads_report.csv")
        if os.path.isfile(spot) and os.path.getsize(spot) > 32:
            art["has_spot_loads"] = True
        for key, name in (
            ("lf_situacional_ok", "loadflow_situacional.json"),
            ("lf_proyectado_ok", "loadflow_proyectado.json"),
        ):
            p = output_path(s, "demand", name)
            if os.path.isfile(p):
                try:
                    import json
                    with open(p, "r", encoding="utf-8") as f:
                        d = json.load(f)
                    art[key] = d.get("status") == "ok"
                except Exception:
                    art[key] = True
        tabla = output_path(s, "clientes", "clientes_alimentador.json")
        if not os.path.isfile(tabla):
            tabla = output_path(s, "clientes", "clientes_alimentador.csv")
        art["tabla_ok"] = os.path.isfile(tabla)
        # EA/Pot: session flag o apply report
        try:
            from pipeline.run_demand_allocation import load_session
            sess = load_session(s) or {}
            art["ea_pot_ok"] = bool(sess.get("ea_pot_loaded_at"))
        except Exception:
            pass
    except Exception:
        pass
    return art


def _load_session(feeder_id):
    try:
        from core.feeder_context import load_settings
        from pipeline.run_demand_allocation import load_session
        s = load_settings(feeder_id=feeder_id, synthesize=True)
        return load_session(s) or {}
    except Exception:
        return {}


def get_campaign(feeder_id, binding=None, refresh_gates=True):
    ledger.init_db()
    camp = ledger.get_or_create_campaign(feeder_id, binding=binding)
    if refresh_gates:
        sess = _load_session(feeder_id)
        art = _artifacts_for_feeder(feeder_id)
        camp = evaluate_gates(camp, session=sess, artifacts=art)
        ledger.save_campaign(camp)
    return camp


def skip_optional_spot(feeder_id):
    """Marca 4.2/4.3 como skipped (campaña sin SpotLoad)."""
    camp = get_campaign(feeder_id)
    for sid in ("4.2", "4.3"):
        mark_step(camp, sid, STEP_SKIPPED, message="Omitido (opcional)")
    sess = _load_session(feeder_id)
    art = _artifacts_for_feeder(feeder_id)
    camp = evaluate_gates(camp, session=sess, artifacts=art)
    ledger.save_campaign(camp)
    return campaign_summary(camp)


def register_legacy_job(feeder_id, action, payload, job_id, binding=None):
    """
    Al crear un job legacy, actualiza Campaign + fila ledger.
    No bloquea si el gate falla (la UI legacy aún puede forzar);
    registra warning en message.
    """
    ledger.init_db()
    camp = get_campaign(feeder_id, binding=binding)
    step_id = resolve_step_for_action(action, payload)
    meta = step_meta(step_id) or {}
    ok_run, reason = (True, None)
    if step_id:
        ok_run, reason = can_run_step(camp, step_id)
        if ok_run:
            mark_step(camp, step_id, STEP_RUNNING, job_id=job_id)
        else:
            # Legacy: permitir pero anotar
            mark_step(
                camp,
                step_id,
                STEP_RUNNING,
                job_id=job_id,
                message="Gate: %s (ejecución legacy forzada)" % reason,
            )
        ledger.save_campaign(camp)

    job = {
        "job_id": job_id,
        "campaign_id": camp["campaign_id"],
        "feeder_id": feeder_id,
        "step_id": step_id or None,
        "action": action,
        "command": meta.get("command"),
        "queue": meta.get("queue") or "cyme",
        "status": "queued",
        "payload": payload or {},
        "message": reason,
    }
    ledger.save_job(job)
    return camp, job


def complete_legacy_job(job_id, ok, result=None, error=None, message=None):
    """Cierra job en ledger y actualiza step de la campaña."""
    job = ledger.load_job(job_id)
    if not job:
        return None
    job["status"] = "ok" if ok else "error"
    job["result"] = result
    job["error"] = error
    if message:
        job["message"] = message
    ledger.save_job(job)

    camp = None
    if job.get("campaign_id"):
        camp = ledger.load_campaign(job["campaign_id"])
    if not camp and job.get("feeder_id"):
        camp = ledger.load_campaign_by_feeder(job["feeder_id"])
    if camp and job.get("step_id"):
        mark_step(
            camp,
            job["step_id"],
            STEP_OK if ok else STEP_ERROR,
            job_id=job_id,
            error=error,
            message=message or ("OK" if ok else "Error"),
        )
        sess = _load_session(job.get("feeder_id"))
        art = _artifacts_for_feeder(job.get("feeder_id"))
        camp = evaluate_gates(camp, session=sess, artifacts=art)
        if ok and camp.get("status") == "failed":
            camp["status"] = "running"
        # Si todos pasos core ok → completed parcial
        ledger.save_campaign(camp)
    return job


def enqueue_command(feeder_id, command, params=None, binding=None):
    """
    API v2: valida gate y prepara job (la ejecución la dispara el caller
    vía jobs legacy o worker futuro).
    """
    params = params or {}
    camp = get_campaign(feeder_id, binding=binding)
    step_id = resolve_step_for_command(command, params)
    if not step_id:
        return {"ok": False, "error": "Command desconocido: %s" % command}
    ok_run, reason = can_run_step(camp, step_id)
    if not ok_run:
        return {
            "ok": False,
            "error": reason or "Paso bloqueado",
            "step_id": step_id,
            "campaign": campaign_summary(camp),
        }
    meta = step_meta(step_id) or {}
    job_id = ledger.new_job_id()
    mark_step(camp, step_id, STEP_RUNNING, job_id=job_id)
    ledger.save_campaign(camp)
    # Map command → legacy action when possible
    action = _command_to_legacy_action(command, params)
    job = {
        "job_id": job_id,
        "campaign_id": camp["campaign_id"],
        "feeder_id": feeder_id,
        "step_id": step_id,
        "action": action,
        "command": command,
        "queue": meta.get("queue") or "cyme",
        "status": "queued",
        "payload": params,
    }
    ledger.save_job(job)
    return {
        "ok": True,
        "job_id": job_id,
        "step_id": step_id,
        "action": action,
        "queue": job["queue"],
        "campaign_id": camp["campaign_id"],
    }


def _command_to_legacy_action(command, params):
    params = params or {}
    mapping = {
        "DiagnoseNetwork": "calidad_diagnosticar",
        "ApplyCorrections": "calidad_aplicar",
        "EvaluateQualityGate": "calidad_convergencia",
        "RunLoadAllocation": "distribucion",
        "RunLoadFlow": "flujo",
    }
    action = mapping.get(command)
    if command == "RunLoadFlow":
        # payload scenario lo pone el caller
        return "flujo"
    return action or command
