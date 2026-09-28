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
    for key, value in identity.items():
        result.setdefault(key, value)
    return result


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
    "context_metadata",
    "copy_audit_artifacts",
    "require_matching_manifest",
    "sha256_file",
    "tag_context",
]
