# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import tempfile
import unittest
from unittest import mock


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

    def test_in_process_color_selection_exports_the_active_network_view(self):
        from pipeline import capture_informe_color_views as capture

        observed = {}

        def fake_run(_app, script):
            observed["script"] = script
            return True, ["RunPythonScript ret=0"], "DONE"

        with mock.patch.object(capture, "_run_python_in_cyme", side_effect=fake_run):
            capture._select_color_layer_inside_cyme(
                object(),
                capture.COLOR_VOLTAGE,
                network_id="NET_PE104",
                export_path=r"D:\evidence\pe104.png",
            )

        self.assertIn("ExportActiveView", observed["script"])
        self.assertIn(
            "EXPORT_PATH = %r" % r"D:\evidence\pe104.png",
            observed["script"],
        )
        self.assertLess(
            observed["script"].index("DisplayBestFit"),
            observed["script"].index("ExportActiveView"),
        )

    def test_thin_native_unifilar_is_not_rejected_as_empty_shell(self):
        from PIL import Image, ImageDraw
        from pipeline.capture_informe_color_views import _is_schematic_png

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            png = os.path.join(work, "thin_unifilar.png")
            image = Image.new("RGB", (707, 535), "white")
            draw = ImageDraw.Draw(image)
            draw.ellipse((310, 210, 390, 290), outline=(0, 120, 200), width=2)
            draw.line((355, 275, 706, 455), fill=(0, 125, 205), width=5)
            draw.line((355, 275, 706, 455), fill=(255, 240, 0), width=2)
            draw.text((280, 305), "NET_2030_184_PE104", fill=(0, 110, 190))
            image.save(png)

            self.assertTrue(_is_schematic_png(png))

    def test_evidence_uses_window_identity_recorded_at_capture_time(self):
        from pipeline import capture_informe_color_views as capture

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            images = os.path.join(work, "informe_images")
            os.makedirs(images)
            png = os.path.join(images, "situacional_tension.png")
            with open(png, "wb") as handle:
                handle.write(b"native-png")
            with open(png + ".cymdist.json", "w", encoding="utf-8") as handle:
                import json
                json.dump({
                    "export": "exportactiveview",
                    "color_verified": True,
                    "lf_converged": True,
                    "window_identity": {"hwnd": 123, "pid": 456, "title": "CYMDIST"},
                }, handle)
            settings = dict(CTX, output_dir=work)
            with mock.patch.object(capture, "_current_cymdist_window_identity", return_value={}):
                result = capture.native_color_evidence_from_existing(
                    settings,
                    capture.COLOR_VOLTAGE,
                    "situacional",
                    "run-window",
                    state_restored=True,
                    capture_result={"ok": True},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["window_identity"]["hwnd"], 123)


if __name__ == "__main__":
    unittest.main(verbosity=2)
