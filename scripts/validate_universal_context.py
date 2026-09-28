# -*- coding: utf-8 -*-
"""Read-mostly canary for the universal RECYM/CYMDIST context contract."""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core.context_identity import build_context_identity, context_fingerprint


class JsonHttp(object):
    def __init__(self, base_url, api_key=""):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=120) as response:
                raw = response.read().decode("utf-8")
                return response.getcode(), json.loads(raw or "{}")
        except HTTPError as ex:
            raw = ex.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw or "{}")
            except Exception:
                payload = {"ok": False, "error": raw}
            return ex.code, payload


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _call(http, evidence, method, path, body=None, expected=(200,)):
    started = time.time()
    status, payload = http.request(method, path, body)
    row = {
        "method": method,
        "path": path,
        "http_status": status,
        "duration_sec": round(time.time() - started, 3),
        "ok": status in expected and bool(payload.get("ok", True)),
        "response": payload,
    }
    evidence["calls"].append(row)
    if status not in expected or payload.get("ok") is False:
        raise RuntimeError("%s %s falló: HTTP %s · %s" % (method, path, status, payload))
    return payload


def _poll_job(http, evidence, job_id, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = _call(http, evidence, "GET", "/api/jobs/%s" % job_id)
        job = payload.get("job") or payload
        status = str(job.get("status") or "")
        if status == "ok":
            return job.get("result") or job
        if status == "error":
            raise RuntimeError("Job %s falló: %s" % (job_id, job))
        time.sleep(0.5)
    raise RuntimeError("Timeout del job %s" % job_id)


def run_canary(args, http=None):
    identity = build_context_identity(
        {
            "database_mdb": args.mdb,
            "study_path": args.study,
            "feeder_id": args.feeder,
            "network_id": args.network,
        },
        require_complete=True,
    )
    expected = context_fingerprint(identity)
    client = http or JsonHttp(args.base_url, getattr(args, "api_key", ""))
    evidence = {
        "schema_version": 1,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "context_identity": {key: identity[key] for key in ("database_mdb", "study_path", "feeder_id", "network_id")},
        "context_fingerprint": expected,
        "mode": "read_only" if args.skip_apply else "context_apply_no_model_save",
        "calls": [],
        "ok": False,
    }
    try:
        _call(client, evidence, "GET", "/health")
        _call(client, evidence, "GET", "/api/health/ready")
        created = _call(
            client,
            evidence,
            "POST",
            "/api/jobs",
            {"action": "contexto_descubrir_redes", "payload": {"database_mdb": identity["database_mdb"]}},
        )
        discovery = _poll_job(client, evidence, created["job_id"])
        matching = [
            row for row in (discovery.get("feeders") or discovery.get("networks") or [])
            if str(row.get("feeder_id") or "") == identity["feeder_id"]
            and str(row.get("network_id") or "") == identity["network_id"]
        ]
        if not matching:
            raise RuntimeError("La red solicitada no fue descubierta por CYMDIST en la MDB")
        evidence["discovery"] = discovery
        if not args.skip_apply:
            applied = _call(
                client,
                evidence,
                "POST",
                "/api/contexto/aplicar",
                dict(evidence["context_identity"], allowed_networks=matching),
                expected=(200,),
            )
            if str(applied.get("context_fingerprint") or "") != expected:
                raise RuntimeError("CONTEXT_IDENTITY_MISMATCH en 1.1")
            evidence["context_apply"] = applied
        _call(client, evidence, "GET", "/health")
        evidence["ok"] = True
    except Exception as ex:
        evidence["error"] = str(ex)
    evidence["finished_at"] = datetime.now().isoformat(timespec="seconds")
    if args.out:
        out = os.path.realpath(os.path.abspath(args.out))
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, indent=2, ensure_ascii=False)
        evidence["evidence_path"] = out
        evidence["evidence_sha256"] = _sha256(out)
    return evidence


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Canario universal de contexto CYMDIST")
    parser.add_argument("--mdb", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--feeder", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--out", default=os.path.join("data", "output", "validation", "universal_context.json"))
    parser.add_argument("--skip-apply", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    result = run_canary(parse_args(argv))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
