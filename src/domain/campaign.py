# -*- coding: utf-8 -*-
"""
Dominio Campaign RECYM v7 — máquina de estados §§1–7.

Sin dependencias de FastAPI/Dramatiq: usable desde API, CLI y workers.
"""
from __future__ import print_function

from typing import Any, Dict, List, Optional, Tuple

# Estados de un paso
STEP_PENDING = "pending"
STEP_READY = "ready"
STEP_RUNNING = "running"
STEP_OK = "ok"
STEP_SKIPPED = "skipped"
STEP_BLOCKED = "blocked"
STEP_ERROR = "error"

# Colas lógicas
QUEUE_CYME = "cyme"
QUEUE_CPU = "cpu"

# Catálogo StepId → metadatos
STEPS = (
    ("1.1", "ApplyContext", QUEUE_CYME, "Aplicar BD+estudio"),
    ("1.2", "SetCabecera", QUEUE_CPU, "Guardar cabecera P/Q"),
    ("2.diag", "DiagnoseNetwork", QUEUE_CYME, "Diagnosticar red"),
    ("2.fix", "ApplyCorrections", QUEUE_CYME, "Aplicar correcciones"),
    ("2.gate", "EvaluateQualityGate", QUEUE_CPU, "Gate calidad"),
    ("3.1", "BuildClientesTable", QUEUE_CPU, "Armar tabla clientes"),
    ("3.2", "ApplyEaPot", QUEUE_CYME, "EA/Pot + Incluir"),
    ("3.3", "RunLoadAllocation", QUEUE_CYME, "LoadAllocation kWh"),
    ("4.2", "AddSpotLoad", QUEUE_CYME, "SpotLoad una"),
    ("4.3", "AddSpotLoadBulk", QUEUE_CYME, "SpotLoad lote"),
    ("5.1", "RunLoadFlow", QUEUE_CYME, "LF situacional"),
    ("5.2", "RunLoadFlow", QUEUE_CYME, "LF proyectado"),
    ("5.3", "RunLoadFlow", QUEUE_CYME, "LF general"),
    ("6.meta", "SetInformeMeta", QUEUE_CPU, "Meta informe"),
    ("6.capture", "CaptureColorViews", QUEUE_CYME, "Capturas color Cyme"),
    ("6.fill", "FillInformeDoc", QUEUE_CPU, "Rellenar docx (sin Cyme)"),
    ("7.opt", "OptimizeEquipment", QUEUE_CYME, "Optimización equipos"),
    ("7.suite", "SuiteTools", QUEUE_CPU, "Suite / batch tools"),
)

STEP_IDS = [s[0] for s in STEPS]

# action legacy jobs.py → step_id
LEGACY_ACTION_TO_STEP = {
    "calidad_diagnosticar": "2.diag",
    "calidad_proponer": "2.diag",
    "calidad_aplicar": "2.fix",
    "calidad_convergencia": "2.gate",
    "calidad_hasta_limpio": "2.fix",
    "calidad_sistema": "2.diag",
    "calidad_eld": "2.diag",
    "distribucion": "3.3",
    "flujo": "5.1",  # refinado por scenario en resolve_step_for_action
    "build_tablero": "2.gate",
}

# command name → step (params pueden refinar)
COMMAND_TO_STEP = {
    "ApplyContext": "1.1",
    "SetCabecera": "1.2",
    "DiagnoseNetwork": "2.diag",
    "ApplyCorrections": "2.fix",
    "EvaluateQualityGate": "2.gate",
    "BuildClientesTable": "3.1",
    "ApplyEaPot": "3.2",
    "RunLoadAllocation": "3.3",
    "AddSpotLoad": "4.2",
    "AddSpotLoadBulk": "4.3",
    "RunLoadFlow": "5.3",
    "SetInformeMeta": "6.meta",
    "CaptureColorViews": "6.capture",
    "FillInformeDoc": "6.fill",
    "OptimizeEquipment": "7.opt",
    "SuiteTools": "7.suite",
}


def resolve_step_for_action(action, payload=None):
    """Mapea action legacy (+ payload) a step_id."""
    action = (action or "").strip()
    payload = payload or {}
    if action == "flujo":
        scen = (payload.get("scenario") or "").strip().lower()
        if scen == "situacional":
            return "5.1"
        if scen == "proyectado":
            return "5.2"
        return "5.3"
    return LEGACY_ACTION_TO_STEP.get(action) or ""


def resolve_step_for_command(command, params=None):
    command = (command or "").strip()
    params = params or {}
    if command == "RunLoadFlow":
        scen = (params.get("scenario") or "").strip().lower()
        if scen == "situacional":
            return "5.1"
        if scen == "proyectado":
            return "5.2"
        return "5.3"
    return COMMAND_TO_STEP.get(command) or ""


def step_meta(step_id):
    for sid, cmd, queue, title in STEPS:
        if sid == step_id:
            return {
                "step_id": sid,
                "command": cmd,
                "queue": queue,
                "title": title,
            }
    return None


def empty_steps():
    """Mapa inicial step_id → StepState."""
    out = {}
    for sid, cmd, queue, title in STEPS:
        state = STEP_READY if sid == "1.1" else STEP_PENDING
        out[sid] = {
            "step_id": sid,
            "command": cmd,
            "queue": queue,
            "title": title,
            "state": state,
            "job_id": None,
            "error": None,
            "message": None,
            "updated_at": None,
        }
    return out


def new_campaign(feeder_id, binding=None, campaign_id=None):
    import time
    import uuid

    fid = (feeder_id or "").strip() or "UNKNOWN"
    return {
        "campaign_id": campaign_id or uuid.uuid4().hex[:12],
        "feeder_id": fid,
        "binding": dict(binding or {}),
        "status": "idle",
        "steps": empty_steps(),
        "created_at": time.time(),
        "updated_at": time.time(),
    }


# --- Gates: prerequisitos para que un step pase a ready/running ---

def _session_flags(session):
    session = session or {}
    return {
        "has_cabecera": session.get("P_kW") is not None,
        "gate_ok": bool(
            (session.get("model_quality_gate") or {}).get("ready")
            or (session.get("model_quality_gate") or {}).get("converge") == "SI"
        ),
        "alloc_ok": bool(session.get("loadallocation_com_ok")),
        "has_spot": False,  # se rellena con artifact check
        "lf_sit_ok": False,
        "lf_proj_ok": False,
    }


def evaluate_gates(campaign, session=None, artifacts=None):
    """
    Recalcula estados ready/blocked/skipped según dependencias §§1–7.

    artifacts: dict opcional con booleans:
      has_spot_loads, lf_situacional_ok, lf_proyectado_ok, tabla_ok, ea_pot_ok
    """
    artifacts = artifacts or {}
    session = session or {}
    flags = _session_flags(session)
    flags["has_spot"] = bool(artifacts.get("has_spot_loads"))
    flags["lf_sit_ok"] = bool(artifacts.get("lf_situacional_ok"))
    flags["lf_proj_ok"] = bool(artifacts.get("lf_proyectado_ok"))
    flags["tabla_ok"] = bool(artifacts.get("tabla_ok"))
    flags["ea_pot_ok"] = bool(artifacts.get("ea_pot_ok"))

    steps = campaign.get("steps") or empty_steps()

    def st(sid):
        return (steps.get(sid) or {}).get("state")

    def set_state(sid, state, message=None):
        row = steps.setdefault(sid, {})
        # No pisar running/ok/error/skipped manual salvo blocked/ready/pending
        cur = row.get("state")
        if cur in (STEP_RUNNING, STEP_OK, STEP_ERROR) and state in (
            STEP_READY, STEP_BLOCKED, STEP_PENDING
        ):
            # ok/error se mantienen hasta reset; running no tocar
            if cur == STEP_RUNNING:
                return
            if cur == STEP_OK and state == STEP_READY:
                return
            if cur == STEP_ERROR:
                return
        if cur == STEP_SKIPPED and state != STEP_READY:
            return
        row["state"] = state
        if message is not None:
            row["message"] = message

    # 1.1 siempre ready si no ok
    if st("1.1") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        set_state("1.1", STEP_READY)

    # 1.2 necesita 1.1 ok
    if st("1.1") == STEP_OK:
        if st("1.2") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
            set_state("1.2", STEP_READY)
    else:
        set_state("1.2", STEP_BLOCKED, "Requiere 1.1 Aplicar contexto")

    # 2.* necesita cabecera (1.2 ok o flags)
    cab_ok = st("1.2") == STEP_OK or flags["has_cabecera"]
    for sid in ("2.diag", "2.fix", "2.gate"):
        if st(sid) in (STEP_OK, STEP_RUNNING, STEP_ERROR):
            continue
        if cab_ok:
            set_state(sid, STEP_READY)
        else:
            set_state(sid, STEP_BLOCKED, "Requiere cabecera §1.2")

    # 3.1 necesita gate
    gate_ok = st("2.gate") == STEP_OK or flags["gate_ok"]
    if st("3.1") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        if gate_ok:
            set_state("3.1", STEP_READY)
        else:
            set_state("3.1", STEP_BLOCKED, "Requiere gate calidad §2")

    # 3.2 necesita 3.1
    if st("3.2") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        if st("3.1") == STEP_OK or flags["tabla_ok"]:
            set_state("3.2", STEP_READY)
        else:
            set_state("3.2", STEP_BLOCKED, "Requiere tabla clientes §3.1")

    # 3.3 necesita 3.2
    if st("3.3") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        if st("3.2") == STEP_OK or flags["ea_pot_ok"]:
            set_state("3.3", STEP_READY)
        else:
            set_state("3.3", STEP_BLOCKED, "Requiere EA/Pot §3.2")

    # 4.* opcionales tras 3.3 — ready o skipped
    alloc_ok = st("3.3") == STEP_OK or flags["alloc_ok"]
    for sid in ("4.2", "4.3"):
        if st(sid) in (STEP_OK, STEP_RUNNING, STEP_ERROR, STEP_SKIPPED):
            continue
        if alloc_ok:
            set_state(sid, STEP_READY, "Opcional: SpotLoad §4")
        else:
            set_state(sid, STEP_BLOCKED, "Requiere distribución §3.3")

    # Tras SpotLoad OK, 3.3 no se re-ofrece como ready (queda ok)
    # 5.* tras 3.3; §4 no es requisito
    for sid, need_msg in (
        ("5.1", None),
        ("5.2", None),
        ("5.3", None),
    ):
        if st(sid) in (STEP_OK, STEP_RUNNING, STEP_ERROR):
            continue
        if alloc_ok:
            set_state(sid, STEP_READY, "§4 opcional: sin SpotLoad corre LF del modelo")
        else:
            set_state(sid, STEP_BLOCKED, "Requiere distribución §3.3")

    # 6.meta tras ambos LF (o al menos uno ready path)
    both_lf = (
        st("5.1") == STEP_OK or flags["lf_sit_ok"]
    ) and (
        st("5.2") == STEP_OK or flags["lf_proj_ok"]
    )
    for sid in ("6.meta", "6.capture", "6.fill"):
        if st(sid) in (STEP_OK, STEP_RUNNING, STEP_ERROR):
            continue
        if both_lf:
            set_state(sid, STEP_READY)
        else:
            set_state(sid, STEP_BLOCKED, "Requiere LF situacional y proyectado §5")

    # 7 tras 6.fill (o allow suite always for tools)
    if st("7.suite") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        set_state("7.suite", STEP_READY, "Suite disponible (herramientas)")
    if st("7.opt") not in (STEP_OK, STEP_RUNNING, STEP_ERROR):
        if st("6.fill") == STEP_OK or both_lf:
            set_state("7.opt", STEP_READY)
        else:
            set_state("7.opt", STEP_BLOCKED, "Requiere flujos §5 (recomendado tras §6)")

    campaign["steps"] = steps
    return campaign


def can_run_step(campaign, step_id):
    """
    True si el step puede ejecutarse ahora.
    4.* y 5.*: 5 no exige 4; 4 es opcional.
    Tras 4 OK, 3.3 no debe re-ejecutarse (política).
    """
    steps = campaign.get("steps") or {}
    row = steps.get(step_id) or {}
    state = row.get("state")
    if state in (STEP_BLOCKED, STEP_PENDING, STEP_RUNNING):
        if state == STEP_BLOCKED:
            return False, row.get("message") or "Paso bloqueado"
        if state == STEP_PENDING:
            return False, "Paso aún no listo"
        if state == STEP_RUNNING:
            return False, "Paso en ejecución"
    if step_id == "3.3":
        # Prohibido redistribuir si ya hay SpotLoad aplicada en campaña
        if (steps.get("4.2") or {}).get("state") == STEP_OK or (
            steps.get("4.3") or {}
        ).get("state") == STEP_OK:
            return False, "Tras SpotLoad §4 no redistribuir (§3.3 prohibido)"
    if state in (STEP_READY, STEP_OK, STEP_ERROR, STEP_SKIPPED):
        # permitir reintento de ok/error
        return True, None
    return False, "Estado no ejecutable: %s" % state


def mark_step(campaign, step_id, state, job_id=None, error=None, message=None):
    import time

    steps = campaign.setdefault("steps", empty_steps())
    row = steps.setdefault(step_id, {"step_id": step_id})
    row["state"] = state
    if job_id is not None:
        row["job_id"] = job_id
    if error is not None:
        row["error"] = error
    if message is not None:
        row["message"] = message
    row["updated_at"] = time.time()
    campaign["updated_at"] = time.time()
    if state == STEP_RUNNING:
        campaign["status"] = "running"
    elif state == STEP_ERROR:
        campaign["status"] = "failed"
    return campaign


def campaign_summary(campaign):
    steps = campaign.get("steps") or {}
    counts = {}
    for row in steps.values():
        s = row.get("state") or "?"
        counts[s] = counts.get(s, 0) + 1
    return {
        "campaign_id": campaign.get("campaign_id"),
        "feeder_id": campaign.get("feeder_id"),
        "status": campaign.get("status"),
        "binding": campaign.get("binding") or {},
        "counts": counts,
        "steps": steps,
    }
