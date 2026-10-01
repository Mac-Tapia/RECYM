import json
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
SRC = os.path.join(ROOT, "src")
for path in (SCRIPTS, SRC):
    if path not in sys.path:
        sys.path.insert(0, path)

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
        if method == "GET" and path.startswith("/api/cabecera?"):
            return {"P_kW": 100.0, "Q_kvar": 25.0, "mode": "KW_KVAR"}
        if method == "POST" and path == "/api/cabecera":
            return {
                "ok": True,
                "study_saved": True,
                "db_updated": True,
                "project_saved": True,
            }
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


class TestUniversalRunner(unittest.TestCase):
    def test_cli_requires_four_identity_fields(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--mdb", "a.mdb", "--study", "b.zxst", "--feeder", "F"])


    def test_read_only_run_is_dynamic_and_records_pending_writes(self):
        with tempfile.TemporaryDirectory() as work:
            evidence = RunEvidence(os.path.join(work, "run-x"), "run-x", IDENTITY)
            client = FakeClient()
            with redirect_stdout(io.StringIO()):
                UniversalRunner(client, evidence, allow_write=False).run()
            rows = evidence.events()
            pending = {row["stage"] for row in rows if row["status"] == "pending_real"}
            required = {"1.1", "1.2", "2.3", "3.3", "3.4", "5.1", "6.1", "7.4"}
            self.assertTrue(required <= pending)
            wire = json.dumps(client.calls)
            self.assertIn("XX999", wire)
            self.assertNotIn("PA217", wire)
            self.assertNotIn("PE104", wire)
            self.assertNotIn("CA101", wire)
            table_call = next(call for call in client.calls if call[1] == "/api/clientes/tabla")
            self.assertEqual(table_call[2]["clientes_file"], "ci.xlsx")
            self.assertEqual(table_call[2]["suministro_file"], "fuente.xlsx")


    def test_apply_context_sends_discovered_network_objects(self):
        with tempfile.TemporaryDirectory() as work:
            evidence = RunEvidence(os.path.join(work, "run-write"), "run-write", IDENTITY)
            client = FakeClient()
            # Stop after the first later mutating job; 1.1 must already be observable.
            client.fail_action = "calidad_diagnosticar"
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "fallo real"):
                    UniversalRunner(client, evidence, allow_write=True).run()
            call = next(item for item in client.calls if item[1] == "/api/contexto/aplicar")
            self.assertEqual(
                call[2]["allowed_networks"],
                [{"feeder_id": "XX999", "network_id": "NET_DINAMICA_999"}],
            )


    def test_failed_gate_stops_downstream(self):
        with tempfile.TemporaryDirectory() as work:
            evidence = RunEvidence(os.path.join(work, "run-y"), "run-y", IDENTITY)
            client = FakeClient(fail_action="contexto_descubrir_redes")
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "fallo real"):
                    UniversalRunner(client, evidence).run()
            self.assertFalse(
                any(call[1] == "/api/clientes/archivos" for call in client.calls)
            )
            self.assertEqual(evidence.events()[-1]["stage"], "1.discovery")
            self.assertEqual(evidence.events()[-1]["status"], "failed")


    def test_error_code_is_never_accepted_as_passed(self):
        with tempfile.TemporaryDirectory() as work:
            evidence = RunEvidence(os.path.join(work, "run-soft"), "run-soft", IDENTITY)
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(Exception, "NATIVE_DIAGNOSTIC_CAPTURE_FAILED"):
                    UniversalRunner(SoftFalseClient(), evidence).run()
            self.assertEqual(evidence.events()[-1]["stage"], "2.1")
            self.assertEqual(evidence.events()[-1]["status"], "failed")


    def test_resume_rejects_crossed_context(self):
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "resume")
            RunEvidence(target, "same-run", IDENTITY)
            crossed = dict(IDENTITY, feeder_id="OTRO")
            with self.assertRaisesRegex(ValueError, "RESUME_CONTEXT_MISMATCH"):
                RunEvidence(target, "same-run", crossed, resume=True)


    def test_manifest_hashes_all_summary_artifacts(self):
        with tempfile.TemporaryDirectory() as work:
            evidence = RunEvidence(os.path.join(work, "run-z"), "run-z", IDENTITY)
            evidence.append("1.1", "passed", "ok")
            evidence.finalize()
            with open(evidence.manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(
                all(len(row["sha256"]) == 64 for row in manifest["artifacts"])
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
