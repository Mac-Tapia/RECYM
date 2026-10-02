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
        "flujo_situacional_34",
        "flujo",
        "optimizacion_reclosers",
        "optimizacion_regulators",
        "optimizacion_capacitors",
        "suite_conexion",
        "suite_inventario_cargas",
        "suite_sync_equipos",
        "suite_fix_default",
        "suite_export_ascii",
        "suite_pipeline",
        "clientes_activo_cymdist",
        "clientes_aplicar",
        "distribucion_reporte",
        "reportes_informe",
        "cargas_verificar_cymdist",
    ]
)


def configure_worker_error_mode(
    platform=None,
    set_error_mode=None,
    set_wer_flags=None,
):
    """Disable modal Win32 crash dialogs only in the isolated CymPy worker.

    The native exit code and ``crashed_com`` telemetry remain unchanged; this
    only prevents an unattended child process from blocking on a message box.
    """
    current_platform = os.name if platform is None else str(platform)
    if current_platform != "nt":
        return {"applied": False, "reason": "non-windows"}

    # WinBase.h: SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
    # SEM_NOOPENFILEERRORBOX.
    flags = 0x0001 | 0x0002 | 0x8000
    try:
        if set_error_mode is None:
            import ctypes

            set_error_mode = ctypes.windll.kernel32.SetErrorMode
            set_error_mode.argtypes = [ctypes.c_uint]
            set_error_mode.restype = ctypes.c_uint
        previous = int(set_error_mode(flags))
        if set_wer_flags is None:
            import ctypes

            # WerApi.h: WER_FAULT_REPORTING_NO_UI = 32. La API se expone en
            # wer.dll en Windows de escritorio; mantener fallback por SDK.
            try:
                set_wer_flags = ctypes.windll.wer.WerSetFlags
            except Exception:
                set_wer_flags = ctypes.windll.kernel32.WerSetFlags
            set_wer_flags.argtypes = [ctypes.c_ulong]
            set_wer_flags.restype = ctypes.c_long
        wer_hresult = int(set_wer_flags(32))
        return {
            "applied": wer_hresult == 0,
            "flags": flags,
            "previous": previous,
            "wer_no_ui": wer_hresult == 0,
            "wer_hresult": wer_hresult,
        }
    except Exception as ex:
        return {
            "applied": False,
            "flags": flags,
            "error": "%s: %s" % (type(ex).__name__, ex),
        }


def _can_soft_accept_crash(result):
    """Un AV al cerrar solo conserva un éxito de dominio ya explícito."""
    return bool(
        isinstance(result, dict)
        and result.get("ok") is True
        and not result.get("error")
        and not result.get("error_code")
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
            err = "Worker sin resultado"
            rc = proc.returncode
            if is_cympy_exit_crash(rc):
                err = (
                    "Worker CymPy Access Violation (0xC0000005) sin JSON. "
                    "En §3.3 se usa motor COM para evitarlo; reinicie API y reintente."
                )
            result = {
                "ok": False,
                "error": err,
                "returncode": rc,
                "stderr": (proc.stderr or "")[-2000:],
                "stdout": (proc.stdout or "")[-2000:],
            }

        if not isinstance(result, dict):
            result = {"ok": True, "result": result}

        result["isolated"] = True
        result["worker_returncode"] = rc
        result["worker_elapsed_s"] = round(time.time() - t0, 2)
        if crashed:
            # CymPy a menudo sale 0xC0000005 al destruir COM tras exito real.
            # Si el worker ya escribio resultado util, conservar OK.
            # Un resumen parcial no convierte una compuerta fallida en éxito.
            # Solo suavizar el AV cuando el dominio ya escribió ok:true.
            had_ok = _can_soft_accept_crash(result)
            if had_ok:
                result["ok"] = True
                result["crashed_com"] = True
                result["crash_soft"] = True
                base_msg = result.get("msg") or "OK"
                if "AV" not in str(base_msg) and "Access" not in str(base_msg):
                    result["msg"] = (
                        "%s · aviso: CymPy AV al cerrar (resultado conservado)"
                        % base_msg
                    )
                result.pop("error", None)
            else:
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
