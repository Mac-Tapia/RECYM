# -*- coding: utf-8 -*-
"""
Ledger SQLite durable para Campaign + Jobs (RECYM v7).

Ruta: data/system/campaigns.db
Compatible Python 3.7 (sin Dramatiq obligatorio).
"""
from __future__ import print_function

import json
import os
import sqlite3
import threading
import time
import uuid

from core.common import ROOT, mkdir

_LOCK = threading.Lock()
_DB_PATH = None


def db_path():
    global _DB_PATH
    if _DB_PATH:
        return _DB_PATH
    path = os.environ.get("RECYM_CAMPAIGN_DB") or os.path.join(
        ROOT, "data", "system", "campaigns.db"
    )
    mkdir(os.path.dirname(path))
    _DB_PATH = path
    return path


def _conn():
    path = db_path()
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _LOCK:
        conn = _conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    feeder_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    binding_json TEXT,
                    steps_json TEXT NOT NULL,
                    created_at REAL,
                    updated_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_campaigns_feeder
                    ON campaigns(feeder_id);

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    campaign_id TEXT,
                    feeder_id TEXT,
                    step_id TEXT,
                    action TEXT,
                    command TEXT,
                    queue TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT,
                    result_json TEXT,
                    message TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_feeder ON jobs(feeder_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                """
            )
            conn.commit()
        finally:
            conn.close()


def _ensure():
    init_db()


def save_campaign(campaign):
    _ensure()
    with _LOCK:
        conn = _conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO campaigns
                (campaign_id, feeder_id, status, binding_json, steps_json,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campaign["campaign_id"],
                    campaign["feeder_id"],
                    campaign.get("status") or "idle",
                    json.dumps(campaign.get("binding") or {}, ensure_ascii=False),
                    json.dumps(campaign.get("steps") or {}, ensure_ascii=False),
                    campaign.get("created_at") or time.time(),
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return campaign


def load_campaign(campaign_id):
    _ensure()
    with _LOCK:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return _row_to_campaign(row)


def load_campaign_by_feeder(feeder_id):
    """Última campaña del alimentador."""
    _ensure()
    fid = (feeder_id or "").strip()
    with _LOCK:
        conn = _conn()
        try:
            row = conn.execute(
                """
                SELECT * FROM campaigns WHERE feeder_id=?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (fid,),
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return _row_to_campaign(row)


def _row_to_campaign(row):
    return {
        "campaign_id": row["campaign_id"],
        "feeder_id": row["feeder_id"],
        "status": row["status"],
        "binding": json.loads(row["binding_json"] or "{}"),
        "steps": json.loads(row["steps_json"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_or_create_campaign(feeder_id, binding=None):
    from domain.campaign import evaluate_gates, new_campaign

    existing = load_campaign_by_feeder(feeder_id)
    if existing:
        if binding:
            existing["binding"] = dict(binding)
        existing = evaluate_gates(existing)
        save_campaign(existing)
        return existing
    camp = new_campaign(feeder_id, binding=binding)
    camp = evaluate_gates(camp)
    save_campaign(camp)
    return camp


def save_job(job):
    _ensure()
    with _LOCK:
        conn = _conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                (job_id, campaign_id, feeder_id, step_id, action, command,
                 queue, status, payload_json, result_json, message, error,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["job_id"],
                    job.get("campaign_id"),
                    job.get("feeder_id"),
                    job.get("step_id"),
                    job.get("action"),
                    job.get("command"),
                    job.get("queue"),
                    job.get("status") or "queued",
                    json.dumps(job.get("payload") or {}, ensure_ascii=False, default=str),
                    json.dumps(job.get("result"), ensure_ascii=False, default=str)
                    if job.get("result") is not None
                    else None,
                    job.get("message"),
                    job.get("error"),
                    job.get("created_at") or time.time(),
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return job


def load_job(job_id):
    _ensure()
    with _LOCK:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        finally:
            conn.close()
    if not row:
        return None
    return {
        "job_id": row["job_id"],
        "id": row["job_id"],
        "campaign_id": row["campaign_id"],
        "feeder_id": row["feeder_id"],
        "step_id": row["step_id"],
        "action": row["action"],
        "command": row["command"],
        "queue": row["queue"],
        "status": row["status"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "message": row["message"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def new_job_id():
    return uuid.uuid4().hex[:12]


def update_job(job_id, **kwargs):
    job = load_job(job_id)
    if not job:
        return None
    job.update(kwargs)
    job["updated_at"] = time.time()
    save_job(job)
    return job
