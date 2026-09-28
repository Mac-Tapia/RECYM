# -*- coding: utf-8 -*-
"""Fail-closed provenance helpers for LoadFlow and report artifacts."""
from __future__ import print_function

import hashlib
import json
import os
import shutil

from core.context_identity import (
    ContextIdentityError,
    assert_same_context,
    build_context_identity,
    context_fingerprint,
)


def context_metadata(settings):
    identity = build_context_identity(settings or {}, require_complete=True)
    display = {
        key: identity[key]
        for key in ("database_mdb", "study_path", "feeder_id", "network_id")
    }
    return display, context_fingerprint(display)


def tag_context(settings, payload=None):
    identity, fingerprint = context_metadata(settings)
    result = dict(payload or {})
    result["context_identity"] = identity
    result["context_fingerprint"] = fingerprint
    run_id = str((settings or {}).get("run_id") or result.get("run_id") or ("interactive-" + fingerprint))
    result["run_id"] = run_id
    for key, value in identity.items():
        result.setdefault(key, value)
    return result


def assert_run_provenance(settings, artifact, run_id):
    assert_report_context(settings, artifact)
    actual = str((artifact or {}).get("run_id") or "")
    expected = str(run_id or (settings or {}).get("run_id") or "")
    if not expected or actual != expected:
        raise ContextIdentityError(
            "RUN_ID_MISMATCH",
            "Artefacto de otra ejecución: esperado %s, recibido %s" % (expected, actual),
            different_fields=["run_id"],
            expected={"run_id": expected},
            actual={"run_id": actual},
        )
    return True


def validate_report_sources(
    settings,
    sources,
    run_id,
    required_stages=("1.2", "3.2", "3.3", "3.4", "4", "5.1"),
):
    accepted = {}
    failed = {}
    for stage in required_stages:
        item = (sources or {}).get(stage)
        if isinstance(item, str):
            try:
                with open(item, "r", encoding="utf-8") as handle:
                    item = json.load(handle) or {}
            except Exception as ex:
                failed[stage] = {"error_code": "SOURCE_UNREADABLE", "error": str(ex)}
                continue
        if not isinstance(item, dict):
            failed[stage] = {"error_code": "SOURCE_MISSING"}
            continue
        try:
            assert_run_provenance(settings, item, run_id)
            if item.get("ok") is False:
                raise ValueError("source not ok")
            if stage in ("1.2", "3.2", "3.3", "4") and item.get("reopen_verified") is not True:
                raise ValueError("commit not reopen_verified")
            accepted[stage] = item
        except Exception as ex:
            failed[stage] = ex.to_dict() if hasattr(ex, "to_dict") else {
                "error_code": "SOURCE_NOT_VERIFIED",
                "error": str(ex),
            }
    return {
        "ok": not failed,
        "run_id": run_id,
        "accepted_stages": sorted(accepted),
        "failed_stages": failed,
        "sources": accepted,
    }


def assert_report_context(settings, artifact):
    expected, expected_fingerprint = context_metadata(settings)
    source = dict(artifact or {})
    actual = source.get("context_identity")
    supplied = str(source.get("context_fingerprint") or "").strip().lower()
    if not isinstance(actual, dict) or not supplied:
        raise ContextIdentityError(
            "CONTEXT_IDENTITY_MISMATCH",
            "Artefacto sin identidad de contexto verificable",
            different_fields=["context_identity", "context_fingerprint"],
            expected=expected,
            actual=actual or {},
        )
    actual = build_context_identity(actual, require_complete=True)
    assert_same_context(expected, actual)
    if supplied != expected_fingerprint:
        raise ContextIdentityError(
            "CONTEXT_IDENTITY_MISMATCH",
            "Huella del artefacto distinta al contexto activo",
            different_fields=["context_fingerprint"],
            expected={"context_fingerprint": expected_fingerprint},
            actual={"context_fingerprint": supplied},
        )
    return True


def require_matching_manifest(settings, manifest_path):
    try:
        if not manifest_path or not os.path.isfile(manifest_path):
            raise ContextIdentityError(
                "CONTEXT_IDENTITY_MISMATCH",
                "No existe manifiesto verificable para el contexto activo",
                different_fields=["manifest"],
            )
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle) or {}
        assert_report_context(settings, manifest)
        return manifest
    except ContextIdentityError as ex:
        return ex.to_dict()
    except Exception as ex:
        return {
            "ok": False,
            "error_code": "MANIFEST_INVALID",
            "error": str(ex),
        }


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_audit_artifacts(settings, audit_dir, paths):
    """Copy immutable report evidence into its fingerprint-scoped directory."""
    identity, fingerprint = context_metadata(settings)
    os.makedirs(audit_dir, exist_ok=True)
    copied = []
    for source in paths or []:
        if not source or not os.path.isfile(source):
            continue
        destination = os.path.join(audit_dir, os.path.basename(source))
        source_hash = sha256_file(source)
        if os.path.isfile(destination) and sha256_file(destination) != source_hash:
            root, extension = os.path.splitext(destination)
            destination = "%s.%s%s" % (root, source_hash[:12], extension)
        if not os.path.isfile(destination):
            shutil.copy2(source, destination)
        copied.append(
            {
                "path": destination,
                "sha256": source_hash,
                "bytes": os.path.getsize(destination),
            }
        )
    return {
        "context_identity": identity,
        "context_fingerprint": fingerprint,
        "audit_dir": audit_dir,
        "artifacts": copied,
    }


__all__ = [
    "assert_report_context",
    "assert_run_provenance",
    "context_metadata",
    "copy_audit_artifacts",
    "require_matching_manifest",
    "sha256_file",
    "tag_context",
    "validate_report_sources",
]
