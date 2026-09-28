import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from run_cierre_1_7 import UniversalRunner, parse_args
from pipeline.run_evidence import RunEvidence


IDENTITY = {
    "database_mdb": r"D:\modelos nuevos\red real.mdb",
    "study_path": r"D:\estudios varios\Caso norte.zxst",
    "feeder_id": "XX999",
    "network_id": "NET_DINAMICA_999",
    "context_fingerprint": "f" * 64,
}


class FakeClient(object):
    def __init__(self, fail_action=None):
        self.identity = dict(IDENTITY)
        self.calls = []
        self.fail_action = fail_action

    def request(self, method, path, body=None, timeout=None):
        self.calls.append((method, path, body))
        if self.fail_action == path:
            raise RuntimeError("fallo real")
        if path == "/api/clientes/archivos":
            return {"ok": True, "suministro": ["fuente.xlsx"], "clientesimportantes": ["ci.xlsx"]}
        if path == "/api/cargas/conectadas":
            return {"ok": True, "rows": [{"LoadID": "REAL-1"}]}
        return {"ok": True}

    def job(self, action, payload, timeout=900, poll=1.0):
        self.calls.append(("JOB", action, payload))
        if self.fail_action == action:
            raise RuntimeError("fallo real")
        return dict(self.identity, ok=True, run_id=payload.get("run_id"))


class SoftFalseClient(FakeClient):
    def job(self, action, payload, timeout=900, poll=1.0):
        if action == "calidad_diagnosticar":
            return dict(self.identity, ok=True, error_code="NATIVE_DIAGNOSTIC_CAPTURE_FAILED")
        return super(SoftFalseClient, self).job(action, payload, timeout, poll)


def test_cli_requires_four_identity_fields():
    with pytest.raises(SystemExit):
        parse_args(["--mdb", "a.mdb", "--study", "b.zxst", "--feeder", "F"])


def test_read_only_run_is_dynamic_and_records_pending_writes(tmp_path):
    evidence = RunEvidence(str(tmp_path / "run-x"), "run-x", IDENTITY)
    client = FakeClient()
    UniversalRunner(client, evidence, allow_write=False).run()
    rows = evidence.events()
    pending = {row["stage"] for row in rows if row["status"] == "pending_real"}
    assert {"1.1", "1.2", "2.3", "3.3", "3.4", "5.1", "6.1", "7.4"} <= pending
    wire = json.dumps(client.calls)
    assert "XX999" in wire
    assert "PA217" not in wire and "PE104" not in wire and "CA101" not in wire
    table_call = next(call for call in client.calls if call[1] == "/api/clientes/tabla")
    assert table_call[2]["clientes_file"] == "ci.xlsx"
    assert table_call[2]["suministro_file"] == "fuente.xlsx"


def test_apply_context_sends_discovered_network_objects(tmp_path):
    evidence = RunEvidence(str(tmp_path / "run-write"), "run-write", IDENTITY)
    client = FakeClient()
    # Stop after the first later mutating job; 1.1 must already be observable.
    client.fail_action = "calidad_diagnosticar"
    with pytest.raises(RuntimeError):
        UniversalRunner(client, evidence, allow_write=True).run()
    call = next(item for item in client.calls if item[1] == "/api/contexto/aplicar")
    assert call[2]["allowed_networks"] == [{
        "feeder_id": "XX999", "network_id": "NET_DINAMICA_999",
    }]


def test_failed_gate_stops_downstream(tmp_path):
    evidence = RunEvidence(str(tmp_path / "run-y"), "run-y", IDENTITY)
    client = FakeClient(fail_action="contexto_descubrir_redes")
    with pytest.raises(RuntimeError, match="fallo real"):
        UniversalRunner(client, evidence).run()
    assert not any(call[1] == "/api/clientes/archivos" for call in client.calls)
    assert evidence.events()[-1]["stage"] == "1.discovery"
    assert evidence.events()[-1]["status"] == "failed"


def test_error_code_is_never_accepted_as_passed(tmp_path):
    evidence = RunEvidence(str(tmp_path / "run-soft"), "run-soft", IDENTITY)
    with pytest.raises(Exception, match="NATIVE_DIAGNOSTIC_CAPTURE_FAILED"):
        UniversalRunner(SoftFalseClient(), evidence).run()
    assert evidence.events()[-1]["stage"] == "2.1"
    assert evidence.events()[-1]["status"] == "failed"


def test_resume_rejects_crossed_context(tmp_path):
    target = tmp_path / "resume"
    RunEvidence(str(target), "same-run", IDENTITY)
    crossed = dict(IDENTITY, feeder_id="OTRO")
    with pytest.raises(ValueError, match="RESUME_CONTEXT_MISMATCH"):
        RunEvidence(str(target), "same-run", crossed, resume=True)


def test_manifest_hashes_all_summary_artifacts(tmp_path):
    evidence = RunEvidence(str(tmp_path / "run-z"), "run-z", IDENTITY)
    evidence.append("1.1", "passed", "ok")
    evidence.finalize()
    with open(evidence.manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert len(manifest["artifacts"]) == 3
    assert all(len(row["sha256"]) == 64 for row in manifest["artifacts"])
