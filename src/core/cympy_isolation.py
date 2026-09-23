# -*- coding: utf-8 -*-
"""Aislamiento CymPy/COM: scripts y jobs en subproceso (P0-01).

Un Access Violation (0xC0000005) en el worker no tumba la API FastAPI.
"""
from __future__ import print_function

import json
import os
import subprocess
import tempfile
import threading
import time

from core.common import ROOT, is_cympy_exit_crash, mkdir, resolve_python

# Un solo hijo CymPy a la vez (equivalente al lock in-process).
_ISOLATION_LOCK = threading.Lock()

ISOLATED_ACTIONS = frozenset(
    [
        "calidad_diagnosticar",
        "calidad_proponer",
        "calidad_aplicar",
        "calidad_convergencia",
        "calidad_hasta_limpio",
        "calidad_sistema",
        "calidad_eld",
        "distribucion",
        "flujo",
    ]
)


def isolation_enabled():
    """RECYM_ISOLATE_JOBS: 1=on (default), 0=off. Worker hijo siempre off."""
    if (os.environ.get("RECYM_JOB_WORKER") or "").strip() in ("1", "true", "yes"):
        return False
    flag = (os.environ.get("RECYM_ISOLATE_JOBS") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def should_isolate_action(action):
    return isolation_enabled() and (action or "") in ISOLATED_ACTIONS


def run_script_isolated(script_rel, args=None, timeout=900, env=None):
    """Lanza un script Python en proceso hijo con el intérprete CYME/proyecto."""
    script = script_rel
    if not os.path.isabs(script):
        script = os.path.join(ROOT, script.replace("/", os.sep))
    if not os.path.isfile(script):
        return {
            "ok": False,
            "returncode": 127,
            "crashed_com": False,
            "stdout": "",
            "stderr": "script no encontrado: %s" % script,
            "cmd": [],
        }

    py = resolve_python()
    cmd = [py, "-u", script] + list(args or [])
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    run_env.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            universal_newlines=True,
        )
        rc = proc.returncode
        crashed = is_cympy_exit_crash(rc)
        return {
            "ok": (rc == 0) and not crashed,
            "returncode": rc,
            "crashed_com": crashed,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired as ex:
        return {
            "ok": False,
            "returncode": -1,
            "crashed_com": False,
            "stdout": (ex.stdout or "") if isinstance(ex.stdout, str) else "",
            "stderr": "timeout %ss" % timeout,
            "cmd": cmd,
        }
    except Exception as ex:
        return {
            "ok": False,
            "returncode": -2,
            "crashed_com": False,
            "stdout": "",
            "stderr": "%s: %s" % (type(ex).__name__, ex),
            "cmd": cmd,
        }


def run_job_action_isolated(action, payload=None, feeder=None, timeout=900, progress_cb=None):
    """Ejecuta action de jobs.py en subproceso vía job_worker_cli.

    progress_cb(msg) opcional — solo latea mensajes de espera (sin progreso fino).
    """
    payload = dict(payload or {})
    # Quitar callbacks no serializables
    payload.pop("_job_progress", None)

    work = tempfile.mkdtemp(prefix="recym_job_")
    payload_path = os.path.join(work, "payload.json")
    out_path = os.path.join(work, "result.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)

    cli = os.path.join(ROOT, "src", "api_app", "job_worker_cli.py")
    py = resolve_python()
    cmd = [
        py,
        "-u",
        cli,
        "--action",
        str(action),
        "--payload-file",
        payload_path,
        "--out",
        out_path,
    ]
    if feeder:
        cmd.extend(["--feeder", str(feeder)])

    run_env = os.environ.copy()
    run_env["RECYM_JOB_WORKER"] = "1"
    run_env["PYTHONIOENCODING"] = "utf-8"
    run_env["PYTHONPATH"] = os.pathsep.join(
        [os.path.join(ROOT, "src"), run_env.get("PYTHONPATH", "")]
    )

    if progress_cb:
        try:
            progress_cb("worker aislado · %s…" % action)
        except Exception:
            pass

    got = _ISOLATION_LOCK.acquire(True, float(timeout))
    if not got:
        return {
            "ok": False,
            "error": "Timeout esperando lock CymPy (otro job en curso)",
            "isolated": True,
        }

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            universal_newlines=True,
        )
        rc = proc.returncode
        crashed = is_cympy_exit_crash(rc)
        result = None
        if os.path.isfile(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    result = json.load(f)
            except Exception as ex_j:
                result = {"ok": False, "error": "JSON out inválido: %s" % ex_j}

        if result is None:
            result = {
                "ok": False,
                "error": "Worker sin resultado",
                "returncode": rc,
                "stderr": (proc.stderr or "")[-2000:],
            }

        if not isinstance(result, dict):
            result = {"ok": True, "result": result}

        result["isolated"] = True
        result["worker_returncode"] = rc
        result["worker_elapsed_s"] = round(time.time() - t0, 2)
        if crashed:
            result["ok"] = False
            result["crashed_com"] = True
            result["error"] = result.get("error") or (
                "Worker CymPy Access Violation (0xC0000005); API intacta"
            )
        if proc.stderr and not result.get("ok"):
            result.setdefault("worker_stderr", (proc.stderr or "")[-1500:])
        if not result.get("msg") and result.get("ok"):
            result["msg"] = "OK · worker aislado · %.1fs" % result["worker_elapsed_s"]
        return result
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "Timeout worker %ss · action=%s" % (timeout, action),
            "isolated": True,
            "crashed_com": False,
        }
    except Exception as ex:
        return {
            "ok": False,
            "error": "%s: %s" % (type(ex).__name__, ex),
            "isolated": True,
        }
    finally:
        try:
            _ISOLATION_LOCK.release()
        except Exception:
            pass
        # Limpieza best-effort
        try:
            for name in (payload_path, out_path):
                if os.path.isfile(name):
                    os.remove(name)
            os.rmdir(work)
        except Exception:
            pass


def describe_isolation():
    return {
        "mode": "subprocess_job_cli",
        "enabled": isolation_enabled(),
        "isolated_actions": sorted(ISOLATED_ACTIONS),
        "note": "Jobs CymPy en hijo; Access Violation no tumba la API.",
        "python": resolve_python(),
        "root": ROOT,
        "cli": os.path.join(ROOT, "src", "api_app", "job_worker_cli.py"),
    }
