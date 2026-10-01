# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

CTX = {
    "database_mdb": r"D:\bases\redes.mdb",
    "study_path": r"D:\studies\multi.zxst",
    "feeder_id": "PE104",
    "network_id": "NET_PE104",
    "run_id": "run-1",
}


class TestReportRunProvenance(unittest.TestCase):
    def test_step5_guided_flow_only_exposes_projected_51(self):
        path = os.path.join(ROOT, "web", "src", "pages", "Step5Flujos.tsx")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("5.1 · Flujo proyectado", source)
        self.assertIn(
            '{studyMode === "transfer" ? <h3>5.2 · Transferencia de carga</h3> : null}',
            source,
        )
        self.assertIn("studyMode === \"transfer\" ? (", source)
        self.assertNotIn("5.3 ·", source)
        self.assertNotIn('run("situacional"', source)

    def test_report_rejects_cross_run_and_missing_stage(self):
        from core.report_provenance import tag_context, validate_report_sources

        stages = {
            name: tag_context(CTX, {"ok": True, "reopen_verified": True, "run_id": "run-1"})
            for name in ("1.2", "3.2", "3.3", "3.4", "4", "5.1")
        }
        self.assertTrue(validate_report_sources(CTX, stages, "run-1")["ok"])
        crossed = dict(stages)
        crossed["5.1"] = tag_context(dict(CTX, run_id="run-2"), {"ok": True, "run_id": "run-2"})
        self.assertFalse(validate_report_sources(CTX, crossed, "run-1")["ok"])
        missing = dict(stages)
        missing.pop("3.4")
        self.assertFalse(validate_report_sources(CTX, missing, "run-1")["ok"])

    def test_report_rejects_foreign_context_even_with_same_run(self):
        from core.report_provenance import tag_context, validate_report_sources

        stages = {
            name: tag_context(CTX, {"ok": True, "reopen_verified": True, "run_id": "run-1"})
            for name in ("1.2", "3.2", "3.3", "3.4", "4", "5.1")
        }
        stages["4"] = tag_context(dict(CTX, database_mdb=r"D:\other.mdb"), {"ok": True, "reopen_verified": True, "run_id": "run-1"})
        result = validate_report_sources(CTX, stages, "run-1")
        self.assertFalse(result["ok"])
        self.assertIn("4", result["failed_stages"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
