# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import tempfile
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
}


class TestNativeColorEvidence(unittest.TestCase):
    def valid(self, png, **changes):
        from core.report_provenance import sha256_file, tag_context

        item = tag_context(CTX, {
            "ok": True,
            "run_id": "run-1",
            "scenario": "situacional",
            "color_type": "VoltageLevel",
            "capture_method": "com_capture",
            "window_identity": {"hwnd": 123, "pid": 456, "title": "CYMDIST"},
            "png_path": png,
            "png_sha256": sha256_file(png),
            "color_verified": True,
            "loadflow_converged": True,
            "state_restored": True,
        })
        item.update(changes)
        return item

    def test_strict_native_evidence_rejects_every_unverified_boundary(self):
        from pipeline.capture_informe_color_views import validate_native_color_evidence

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            png = os.path.join(work, "capture.png")
            with open(png, "wb") as handle:
                handle.write(b"real-native-capture")
            self.assertTrue(validate_native_color_evidence(self.valid(png), CTX, "run-1")["ok"])
            cases = [
                {"capture_method": "renderer_fallback"},
                {"window_identity": {}},
                {"png_sha256": "bad"},
                {"color_verified": False},
                {"loadflow_converged": False},
                {"state_restored": False},
                {"context_fingerprint": "foreign"},
            ]
            for changes in cases:
                self.assertFalse(validate_native_color_evidence(self.valid(png, **changes), CTX, "run-1")["ok"], changes)

    def test_only_voltage_and_loading_levels_are_allowed(self):
        from pipeline.capture_informe_color_views import validate_native_color_evidence

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            png = os.path.join(work, "capture.png")
            with open(png, "wb") as handle:
                handle.write(b"capture")
            result = validate_native_color_evidence(self.valid(png, color_type="Phase"), CTX, "run-1")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "INVALID_COLOR_TYPE")

    def test_34_gate_requires_verified_12_32_33_commits(self):
        from pipeline.capture_informe_color_views import validate_situational_34_gates

        manifests = {
            "1.2": {"ok": True, "reopen_verified": True, "context_fingerprint": "same"},
            "3.2": {"ok": True, "reopen_verified": True, "context_fingerprint": "same"},
            "3.3": {"ok": True, "reopen_verified": True, "context_fingerprint": "same"},
        }
        self.assertTrue(validate_situational_34_gates(manifests, "same")["ok"])
        manifests["3.2"]["reopen_verified"] = False
        self.assertFalse(validate_situational_34_gates(manifests, "same")["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
