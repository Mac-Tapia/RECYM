# -*- coding: utf-8 -*-
"""
Trabajos CymPy en SUBPROCESO.

Motivo: CymPy/COM puede colgarse o terminar con ACCESS_VIOLATION (0xC0000005).
Si eso corre DENTRO de waitress, la UI muere y el usuario ve «Tiempo agotado».
El subproceso aísla el crash: la UI sigue viva y responde JSON claro.
"""
from __future__ import print_function

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _python_exe(settings=None):
    try:
        from core.common import resolve_python
        return resolve_python(settings or {})
    except Exception:
        return sys.executable or "python"


def _kill_proc_tree(proc):
    """Mata el worker y procesos hijos (Cyme/COM) en Windows."""
    if proc is None:
        return
    try:
        if os.name == "nt" and proc.pid:
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_cympy_job(job, payload, settings=None, timeout_sec=75):
    """
    Ejecuta job CymPy en proceso hijo.
    Retorna dict siempre (ok True/False). Nunca propaga crash al caller.
    """
    payload = dict(payload or {})
    payload["job"] = job
    if settings:
        payload.setdefault("feeder_id", settings.get("feeder_id"))
        payload.setdefault("network_id", settings.get("network_id"))
        payload.setdefault("study_path", settings.get("study_path"))
        payload.setdefault("database_mdb", settings.get("database_mdb"))

    tmp_dir = tempfile.mkdtemp(prefix="recym_job_")
    in_path = os.path.join(tmp_dir, "in.json")
    out_path = os.path.join(tmp_dir, "out.json")
    with open(in_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    worker = os.path.join(ROOT, "src", "pipeline", "cympy_jobs.py")
    py = _python_exe(settings)
    cmd = [py, "-u", worker, "--in", in_path, "--out", out_path]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if payload.get("feeder_id"):
        env["RECYM_FEEDER"] = str(payload["feeder_id"])

    t0 = time.time()
    try:
        # Windows: proceso nuevo para poder matar árbol si se cuelga
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            creationflags=creationflags,
        )
        try:
            out, _ = proc.communicate(timeout=float(timeout_sec))
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc)
            try:
                out, _ = proc.communicate(timeout=5)
            except Exception:
                out = ""
            rc = -9
            result = {
                "ok": False,
                "error": "Timeout CymPy (%ss). Se canceló el worker; la UI sigue activa." % timeout_sec,
                "rc": rc,
                "elapsed_sec": round(time.time() - t0, 2),
                "log_tail": (out or "")[-2000:],
                "engine": "subprocess",
            }
            # Si el hijo alcanzó a escribir out.json antes del kill, úsalo
            if os.path.isfile(out_path):
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        disk = json.load(f)
                    if isinstance(disk, dict) and disk.get("ok"):
                        disk.setdefault("elapsed_sec", result["elapsed_sec"])
                        disk.setdefault("engine", "subprocess")
                        return disk
                except Exception:
                    pass
            _write_out(out_path, result)
            return result
        except Exception as ex_to:
            _kill_proc_tree(proc)
            try:
                out, _ = proc.communicate(timeout=5)
            except Exception:
                out = ""
            rc = proc.returncode if proc.returncode is not None else -9
            result = {
                "ok": False,
                "error": "Error worker CymPy: %s" % ex_to,
                "rc": rc,
                "elapsed_sec": round(time.time() - t0, 2),
                "log_tail": (out or "")[-2000:],
                "engine": "subprocess",
            }
            _write_out(out_path, result)
            return result
    except Exception as ex:
        return {
            "ok": False,
            "error": "No se pudo lanzar worker CymPy: %s" % ex,
            "elapsed_sec": round(time.time() - t0, 2),
            "engine": "subprocess",
        }

    result = None
    if os.path.isfile(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                result = json.load(f)
        except Exception as ex:
            result = {"ok": False, "error": "Salida worker ilegible: %s" % ex}

    if not isinstance(result, dict):
        # CymPy a menudo sale con 0xC0000005 tras éxito real
        crash_ok = rc in (0, None) or (isinstance(rc, int) and (rc & 0xFFFFFFFF) == 0xC0000005)
        result = {
            "ok": False,
            "error": "Worker sin JSON de salida (rc=%s). Log: %s" % (
                rc, (out or "")[-500:]
            ),
            "rc": rc,
            "possible_teardown_crash": bool(crash_ok),
            "engine": "subprocess",
        }
    result.setdefault("rc", rc)
    result.setdefault("elapsed_sec", round(time.time() - t0, 2))
    result.setdefault("engine", "subprocess")
    result.setdefault("log_tail", (out or "")[-2000:])
    return result


def _write_out(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
