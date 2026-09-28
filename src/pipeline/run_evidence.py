# -*- coding: utf-8 -*-
"""Evidencia append-only para una ejecucion universal RECYM 1..7."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone


VALID_STATUSES = frozenset(("passed", "failed", "blocked", "pending_real"))


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RunEvidence(object):
    """Diario JSONL inmutable y resumen reproducible de una corrida."""

    def __init__(self, output_dir, run_id, identity, resume=False):
        self.output_dir = os.path.realpath(os.path.abspath(output_dir))
        self.run_id = str(run_id).strip()
        self.identity = dict(identity)
        os.makedirs(self.output_dir, exist_ok=True)
        self.events_path = os.path.join(self.output_dir, "events.jsonl")
        self.summary_path = os.path.join(self.output_dir, "summary.json")
        self.manifest_path = os.path.join(self.output_dir, "manifest.json")
        self.markdown_path = os.path.join(self.output_dir, "summary.md")
        if os.path.exists(self.events_path):
            if not resume:
                raise ValueError("RUN_ALREADY_EXISTS: %s" % self.run_id)
            existing = self.events()
            first = existing[0] if existing else {}
            if first.get("run_id") != self.run_id or first.get("identity") != self.identity:
                raise ValueError("RESUME_CONTEXT_MISMATCH")
        else:
            self.append("run", "passed", "Ejecucion creada", identity=self.identity)

    def append(self, stage, status, message, **detail):
        if status not in VALID_STATUSES:
            raise ValueError("Estado de evidencia invalido: %s" % status)
        row = {
            "seq": len(self.events()) + 1,
            "timestamp_utc": _utc_now(),
            "run_id": self.run_id,
            "identity": self.identity,
            "stage": str(stage),
            "status": status,
            "message": str(message),
        }
        if detail:
            row["detail"] = detail
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def events(self):
        if not os.path.exists(self.events_path):
            return []
        rows = []
        with open(self.events_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    def completed_stages(self):
        return {row["stage"] for row in self.events() if row.get("status") == "passed"}

    def finalize(self):
        rows = self.events()
        latest = {}
        for row in rows:
            latest[row["stage"]] = row
        counts = {status: 0 for status in VALID_STATUSES}
        for row in latest.values():
            counts[row["status"]] += 1
        summary = {
            "run_id": self.run_id,
            "identity": self.identity,
            "generated_at_utc": _utc_now(),
            "counts": counts,
            "stages": list(latest.values()),
            "ok": not any(counts[state] for state in ("failed", "blocked", "pending_real")),
        }
        with open(self.summary_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        lines = [
            "# Evidencia RECYM 1-7",
            "",
            "- Run: `%s`" % self.run_id,
            "- Contexto: `%s`" % self.identity.get("context_fingerprint", ""),
            "",
            "| Etapa | Estado | Evidencia |",
            "|---|---|---|",
        ]
        for row in latest.values():
            lines.append("| %s | %s | %s |" % (
                row["stage"], row["status"], row["message"].replace("|", "/"),
            ))
        with open(self.markdown_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        manifest = {
            "run_id": self.run_id,
            "context_fingerprint": self.identity.get("context_fingerprint"),
            "artifacts": [],
        }
        for path in (self.events_path, self.summary_path, self.markdown_path):
            manifest["artifacts"].append({
                "path": os.path.realpath(path),
                "sha256": _sha256(path),
                "size": os.path.getsize(path),
            })
        for key in ("database_mdb", "study_path"):
            path = self.identity.get(key)
            if path and os.path.isfile(path):
                manifest["artifacts"].append({
                    "role": "input_" + key,
                    "path": os.path.realpath(path),
                    "sha256": _sha256(path),
                    "size": os.path.getsize(path),
                })
        with open(self.manifest_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        return summary
