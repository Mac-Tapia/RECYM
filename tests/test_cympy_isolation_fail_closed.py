import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

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
