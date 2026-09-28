# -*- coding: utf-8 -*-
"""Single-save, backup-first coordinator for physical CYMDIST mutations."""
from __future__ import print_function

import json
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime

from core.context_identity import build_context_identity, canonical_file_path
from core.report_provenance import sha256_file, tag_context


class CommitMode(object):
    READ = "read"
    STUDY = "study"
    STUDY_AND_DATABASE = "study_and_database"
    EXTERNAL_ENGINE_SAVED = "external_engine_saved"

    ALL = frozenset([READ, STUDY, STUDY_AND_DATABASE, EXTERNAL_ENGINE_SAVED])


MUTATING_ACTION_MODES = {
    "cabecera_12": CommitMode.STUDY_AND_DATABASE,
    "calidad_aplicar_23": CommitMode.STUDY_AND_DATABASE,
    "clientes_inclusiones": CommitMode.STUDY,
    "clientes_refresh_31": CommitMode.STUDY,
    "clientes_aplicar_32": CommitMode.STUDY,
    "distribucion_33": CommitMode.EXTERNAL_ENGINE_SAVED,
    "spotload_4": CommitMode.STUDY,
}


def commit_mode_for_action(action):
    mode = MUTATING_ACTION_MODES.get(str(action or ""))
    if not mode:
        raise ValueError("Acción mutante no registrada: %s" % action)
    return mode


def require_verified_commit(result):
    commit = (result or {}).get("commit") if isinstance(result, dict) else None
    if not isinstance(commit, dict) or not commit.get("ok") or not commit.get("reopen_verified"):
        return {
            "ok": False,
            "error_code": "COMMIT_NOT_VERIFIED",
            "error": "La acción no tiene persistencia y reapertura verificadas",
            "commit": commit,
        }
    return result


@dataclass
class CommitRequest(object):
    settings: dict
    action: str
    mode: str
    adapter: object = None
    manifest_dir: str = ""
    readback: object = None
    inventory: object = None


_LOCKS_GUARD = threading.Lock()
_STUDY_LOCKS = {}


def study_lock_key(path):
    return canonical_file_path(path)


def _lock_for(path):
    key = study_lock_key(path)
    with _LOCKS_GUARD:
        lock = _STUDY_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _STUDY_LOCKS[key] = lock
        return lock


def _default_manifest_dir(settings):
    study = os.path.realpath(os.path.abspath(settings["study_path"]))
    return os.path.join(os.path.dirname(study), ".recym_commits")


def _write_manifest(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp-" + uuid.uuid4().hex
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except Exception:
            pass
    os.replace(temporary, path)


def _different_requested(requested, actual):
    requested = requested or {}
    actual = actual or {}
    return [key for key, value in requested.items() if actual.get(key) != value]


def commit_cymdist_action(request, mutate):
    if request.mode not in CommitMode.ALL:
        return {"ok": False, "error_code": "INVALID_COMMIT_MODE", "error": str(request.mode)}
    try:
        identity = build_context_identity(request.settings, require_complete=True)
    except Exception as ex:
        return ex.to_dict() if hasattr(ex, "to_dict") else {"ok": False, "error_code": "CONTEXT_INVALID", "error": str(ex)}
    if request.mode == CommitMode.READ:
        return {
            "ok": False,
            "error_code": "READ_OPERATION_CANNOT_COMMIT",
            "error": "Una operación de lectura no puede solicitar persistencia",
        }

    study_path = identity["study_path"]
    if not os.path.isfile(study_path):
        return {"ok": False, "error_code": "STUDY_NOT_FOUND", "error": study_path}
    manifest_dir = os.path.realpath(os.path.abspath(request.manifest_dir or _default_manifest_dir(request.settings)))
    os.makedirs(manifest_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    token = uuid.uuid4().hex[:12]
    safe_action = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(request.action or "commit"))
    backup_dir = os.path.join(manifest_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, "%s-%s-%s" % (stamp, token, os.path.basename(study_path)))
    manifest_path = os.path.join(manifest_dir, "%s-%s-%s.json" % (stamp, token, safe_action))

    with _lock_for(study_path):
        before_hash = sha256_file(study_path)
        shutil.copy2(study_path, backup_path)
        before_inventory = request.inventory() if callable(request.inventory) else None
        manifest = tag_context(request.settings, {
            "schema_version": 1,
            "ok": False,
            "action": request.action,
            "commit_mode": request.mode,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "study_path": study_path,
            "before_sha256": before_hash,
            "backup_path": backup_path,
            "backup_sha256": sha256_file(backup_path),
            "manifest_path": manifest_path,
            "before_inventory": before_inventory,
            "save_counts": {"study": 0, "database_update": 0, "project": 0},
        })
        stage = "mutation"
        try:
            mutation = mutate() or {}
            if not isinstance(mutation, dict):
                mutation = {"result": mutation}
            requested_values = dict(mutation.get("requested_values") or {})
            manifest["mutation"] = mutation
            manifest["requested_values"] = requested_values

            stage = "save"
            adapter = request.adapter
            if request.mode == CommitMode.EXTERNAL_ENGINE_SAVED:
                if not mutation.get("external_engine_saved"):
                    raise RuntimeError("EXTERNAL_SAVE_NOT_CONFIRMED")
            elif adapter is None:
                raise RuntimeError("ADAPTER_REQUIRED")
            else:
                adapter.save_study(study_path)
                manifest["save_counts"]["study"] += 1
                if request.mode == CommitMode.STUDY_AND_DATABASE:
                    adapter.update_database()
                    manifest["save_counts"]["database_update"] += 1
                    adapter.save_project()
                    manifest["save_counts"]["project"] += 1

            stage = "readback"
            actual_values = request.readback() if callable(request.readback) else dict(requested_values)
            manifest["readback_values"] = actual_values
            different = _different_requested(requested_values, actual_values)
            if different:
                manifest["error_code"] = "READBACK_MISMATCH"
                manifest["different_fields"] = different
                raise ValueError("READBACK_MISMATCH")

            stage = "inventory"
            after_inventory = request.inventory() if callable(request.inventory) else None
            manifest["after_inventory"] = after_inventory
            if isinstance(before_inventory, dict) and isinstance(after_inventory, dict):
                current = identity["network_id"]
                lost = [
                    key for key, value in before_inventory.items()
                    if key != current and (key not in after_inventory or after_inventory.get(key) != value)
                ]
                if lost:
                    manifest["error_code"] = "NEIGHBOR_NETWORK_CHANGED"
                    manifest["neighbor_networks_changed"] = lost
                    raise ValueError("NEIGHBOR_NETWORK_CHANGED")

            manifest["after_sha256"] = sha256_file(study_path)
            manifest["reopen_verified"] = True
            manifest["ok"] = True
        except Exception as ex:
            code = manifest.get("error_code")
            message = str(ex)
            if not code:
                if message == "EXTERNAL_SAVE_NOT_CONFIRMED":
                    code = message
                elif message == "ADAPTER_REQUIRED":
                    code = message
                elif stage == "mutation":
                    code = "CYMDIST_MUTATION_FAILED"
                elif stage == "save":
                    code = "CYMDIST_SAVE_FAILED"
                elif stage == "readback":
                    code = "READBACK_FAILED"
                else:
                    code = "CYMDIST_COMMIT_FAILED"
            manifest["ok"] = False
            manifest["reopen_verified"] = False
            manifest["error_code"] = code
            manifest["error"] = message
        manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _write_manifest(manifest_path, manifest)
        return manifest


__all__ = [
    "CommitMode", "CommitRequest", "MUTATING_ACTION_MODES",
    "commit_cymdist_action", "commit_mode_for_action", "require_verified_commit",
    "study_lock_key",
]
