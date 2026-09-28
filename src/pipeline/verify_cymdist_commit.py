# -*- coding: utf-8 -*-
"""Independent structural/hash verification for a CYMDIST commit manifest."""
from __future__ import print_function

import json
import os

from core.report_provenance import sha256_file


def verify_commit(manifest_path, require_current=False):
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle) or {}
        required = (
            "context_identity", "context_fingerprint", "commit_mode", "action",
            "study_path", "backup_path", "backup_sha256", "before_sha256",
            "requested_values", "readback_values", "reopen_verified",
        )
        missing = [key for key in required if key not in manifest]
        if missing:
            return {"ok": False, "error_code": "COMMIT_MANIFEST_INCOMPLETE", "missing_fields": missing}
        if not manifest.get("ok") or not manifest.get("reopen_verified"):
            return {"ok": False, "error_code": "COMMIT_NOT_VERIFIED", "manifest": manifest}
        backup = manifest["backup_path"]
        if not os.path.isfile(backup) or sha256_file(backup) != manifest["backup_sha256"]:
            return {"ok": False, "error_code": "BACKUP_HASH_MISMATCH"}
        if require_current:
            current = manifest["study_path"]
            if not os.path.isfile(current) or sha256_file(current) != manifest.get("after_sha256"):
                return {"ok": False, "error_code": "CURRENT_STUDY_HASH_MISMATCH"}
        return {
            "ok": True,
            "manifest_path": os.path.realpath(os.path.abspath(manifest_path)),
            "context_fingerprint": manifest["context_fingerprint"],
            "commit_mode": manifest["commit_mode"],
            "action": manifest["action"],
            "reopen_verified": True,
        }
    except Exception as ex:
        return {"ok": False, "error_code": "COMMIT_MANIFEST_INVALID", "error": str(ex)}


__all__ = ["verify_commit"]
