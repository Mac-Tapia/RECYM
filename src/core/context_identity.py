# -*- coding: utf-8 -*-
"""Canonical identity for a concrete CYMDIST execution context."""
from __future__ import print_function

import hashlib
import json
import os


IDENTITY_FIELDS = ("database_mdb", "study_path", "feeder_id", "network_id")


class ContextIdentityError(ValueError):
    """Structured failure used by API, workers and report provenance gates."""

    def __init__(
        self,
        code,
        message,
        missing_fields=None,
        different_fields=None,
        expected=None,
        actual=None,
    ):
        ValueError.__init__(self, message)
        self.code = str(code)
        self.missing_fields = list(missing_fields or [])
        self.different_fields = list(different_fields or [])
        self.expected = expected
        self.actual = actual

    def to_dict(self):
        payload = {"ok": False, "error_code": self.code, "error": str(self)}
        if self.missing_fields:
            payload["missing_fields"] = list(self.missing_fields)
        if self.different_fields:
            payload["different_fields"] = list(self.different_fields)
        if self.expected is not None:
            payload["expected_context"] = self.expected
        if self.actual is not None:
            payload["actual_context"] = self.actual
        return payload


def _display_file_path(path):
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.realpath(os.path.abspath(os.path.normpath(value)))


def canonical_file_path(path):
    """Return a stable Windows comparison value without losing parent paths."""
    display = _display_file_path(path)
    return os.path.normcase(display) if display else ""


def _identifier(value):
    return str(value or "").strip()


def _comparison_identity(identity):
    return {
        "database_mdb": canonical_file_path(identity.get("database_mdb")),
        "study_path": canonical_file_path(
            identity.get("study_path") or identity.get("ui_study_path")
        ),
        "feeder_id": _identifier(identity.get("feeder_id")).upper(),
        "network_id": _identifier(identity.get("network_id")).upper(),
    }


def build_context_identity(settings_or_payload, require_complete=False):
    """Build display and normalized values from settings, headers or a job payload."""
    source = dict(settings_or_payload or {})
    display = {
        "database_mdb": _display_file_path(source.get("database_mdb")),
        "study_path": _display_file_path(
            source.get("study_path") or source.get("ui_study_path")
        ),
        "feeder_id": _identifier(source.get("feeder_id") or source.get("feeder")),
        "network_id": _identifier(source.get("network_id")),
    }
    missing = [name for name in IDENTITY_FIELDS if not display.get(name)]
    if require_complete and missing:
        raise ContextIdentityError(
            "CONTEXT_INCOMPLETE",
            "Contexto CYMDIST incompleto: faltan %s" % ", ".join(missing),
            missing_fields=missing,
            actual=display,
        )
    normalized = _comparison_identity(display)
    result = dict(display)
    result["canonical_database_mdb"] = normalized["database_mdb"]
    result["canonical_study_path"] = normalized["study_path"]
    result["canonical_feeder_id"] = normalized["feeder_id"]
    result["canonical_network_id"] = normalized["network_id"]
    return result


def context_fingerprint(identity):
    """Return a compact SHA-256 fingerprint over the four normalized fields."""
    normalized = _comparison_identity(identity or {})
    raw = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def assert_same_context(expected, actual):
    """Raise a structured error naming every identity field that differs."""
    expected_identity = build_context_identity(expected or {})
    actual_identity = build_context_identity(actual or {})
    left = _comparison_identity(expected_identity)
    right = _comparison_identity(actual_identity)
    different = [name for name in IDENTITY_FIELDS if left[name] != right[name]]
    if different:
        raise ContextIdentityError(
            "CONTEXT_IDENTITY_MISMATCH",
            "Contexto CYMDIST distinto en: %s" % ", ".join(different),
            different_fields=different,
            expected=expected_identity,
            actual=actual_identity,
        )


__all__ = [
    "ContextIdentityError",
    "IDENTITY_FIELDS",
    "assert_same_context",
    "build_context_identity",
    "canonical_file_path",
    "context_fingerprint",
]
