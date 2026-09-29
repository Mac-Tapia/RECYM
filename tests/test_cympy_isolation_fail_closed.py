import os
import inspect
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core import cympy_isolation
from core.cympy_isolation import _can_soft_accept_crash, is_cympy_exit_crash


def test_access_violation_constant_is_recognized():
    assert is_cympy_exit_crash(0xC0000005)


def test_native_failure_contract_has_precedence():
    # Regression contract exercised at integration level by run_1_7: a useful
    # diagnostic summary may coexist with a failed native evidence gate.
    result = {
        "ok": False,
        "summary": {"n_problems": 0},
        "error_code": "NATIVE_DIAGNOSTIC_CAPTURE_FAILED",
    }
    assert _can_soft_accept_crash(result) is False


def test_clean_success_can_survive_teardown_access_violation():
    assert _can_soft_accept_crash({"ok": True, "summary": {"n": 1}}) is True


def test_worker_suppresses_only_windows_native_error_dialogs():
    configure = getattr(cympy_isolation, "configure_worker_error_mode", None)
    assert callable(configure)

    parameters = inspect.signature(configure).parameters
    assert "set_wer_flags" in parameters

    error_mode_calls = []
    wer_calls = []
    result = configure(
        platform="nt",
        set_error_mode=lambda flags: error_mode_calls.append(flags) or 0,
        set_wer_flags=lambda flags: wer_calls.append(flags) or 0,
    )

    assert error_mode_calls == [0x0001 | 0x0002 | 0x8000]
    assert wer_calls == [32]
    assert result == {
        "applied": True,
        "flags": 0x0001 | 0x0002 | 0x8000,
        "previous": 0,
        "wer_no_ui": True,
        "wer_hresult": 0,
    }


def test_worker_configures_error_mode_before_running_cympy_action():
    worker_path = os.path.join(SRC, "api_app", "job_worker_cli.py")
    with open(worker_path, "r", encoding="utf-8") as stream:
        source = stream.read()

    configure_at = source.find("configure_worker_error_mode()")
    action_at = source.find("from api_app.jobs import run_action_inprocess")
    assert configure_at >= 0
    assert action_at >= 0
    assert configure_at < action_at
