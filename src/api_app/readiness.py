# -*- coding: utf-8 -*-
"""Readiness checks para estación RECYM (Cyme, BD, SPA, auth)."""
from __future__ import print_function

import os

from core.common import ROOT, resolve_python


def check_ready():
    """Devuelve dict con ok global y checks individuales."""
    checks = {}
    errors = []

    # Python runtime
    py = resolve_python()
    checks["python"] = {
        "ok": os.path.isfile(py),
        "path": py,
    }
    if not checks["python"]["ok"]:
        errors.append("python_exe no encontrado")

    # Settings / rutas
    try:
        from core.common import load_json

        s = load_json("config/settings.json") or {}
    except Exception as ex:
        s = {}
        checks["settings"] = {"ok": False, "error": str(ex)}
        errors.append("settings: %s" % ex)
    else:
        checks["settings"] = {"ok": True, "active_feeder": s.get("active_feeder") or ""}

    cyme = (s.get("cyme_root") or "").strip()
    cyme_ok = bool(cyme) and os.path.isdir(cyme)
    checks["cyme_root"] = {"ok": cyme_ok, "path": cyme}
    if not cyme_ok:
        errors.append("cyme_root ausente o inválido")

    # cympy importable (sin abrir estudio)
    cympy_ok = False
    cympy_err = None
    try:
        if cyme and cyme not in __import__("sys").path:
            __import__("sys").path.insert(0, cyme)
        import cympy  # noqa: F401

        cympy_ok = True
    except Exception as ex:
        cympy_err = "%s: %s" % (type(ex).__name__, ex)
    checks["cympy"] = {"ok": cympy_ok, "error": cympy_err}
    if not cympy_ok:
        errors.append("cympy no importable")

    mdb = (s.get("database_mdb") or "").strip()
    mdb_ok = bool(mdb) and os.path.isfile(mdb)
    checks["database_mdb"] = {"ok": mdb_ok, "path": mdb}
    if not mdb_ok:
        errors.append("database_mdb no encontrado")

    projects = (s.get("projects_dir") or "").strip()
    proj_ok = bool(projects) and os.path.isdir(projects)
    checks["projects_dir"] = {"ok": proj_ok, "path": projects}
    if not proj_ok:
        errors.append("projects_dir no encontrado")

    spa_index = os.path.join(ROOT, "web", "dist", "index.html")
    spa_ok = os.path.isfile(spa_index)
    checks["spa_dist"] = {"ok": spa_ok, "path": spa_index}
    if not spa_ok:
        errors.append("web/dist no construido (npm run build)")

    try:
        from core.cympy_isolation import describe_isolation

        checks["isolation"] = describe_isolation()
    except Exception as ex:
        checks["isolation"] = {"ok": False, "error": str(ex)}

    try:
        from api_app.security import auth_enabled, environment, get_or_create_api_key

        key = get_or_create_api_key()
        checks["auth"] = {
            "ok": True,
            "enabled": auth_enabled(),
            "env": environment(),
            "api_key_configured": bool(key) and len(key) >= 16,
        }
    except Exception as ex:
        checks["auth"] = {"ok": False, "error": str(ex)}
        errors.append("auth: %s" % ex)

    # Worker CLI presente
    cli = os.path.join(ROOT, "src", "api_app", "job_worker_cli.py")
    checks["job_worker_cli"] = {"ok": os.path.isfile(cli), "path": cli}
    if not checks["job_worker_cli"]["ok"]:
        errors.append("job_worker_cli.py faltante")

    ready = len(errors) == 0
    return {
        "ok": ready,
        "status": "ready" if ready else "not_ready",
        "errors": errors,
        "checks": checks,
    }
