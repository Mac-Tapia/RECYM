# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


CONTEXT = {
    "database_mdb": r"D:\bases\redes.mdb",
    "study_path": r"D:\studies\multi.zxst",
    "feeder_id": "PE104",
    "network_id": "NET_2030_184_PE104",
}


class TestContextModuleWiring(unittest.TestCase):
    def test_all_cymdist_actions_are_protected(self):
        from api_app.jobs import PROTECTED_CONTEXT_ACTIONS

        expected = {
            "calidad_diagnosticar", "calidad_proponer", "calidad_aplicar",
            "calidad_convergencia", "calidad_hasta_limpio", "calidad_sistema",
            "calidad_eld", "distribucion", "flujo", "clientes_activo_cymdist",
            "optimizacion_reclosers", "optimizacion_regulators",
            "optimizacion_capacitors", "suite_conexion", "suite_inventario_cargas",
            "suite_sync_equipos", "suite_fix_default", "suite_export_ascii",
            "suite_pipeline",
        }
        self.assertTrue(expected.issubset(PROTECTED_CONTEXT_ACTIONS))

    def test_explicit_context_wins_without_persisting_selection(self):
        from api_app.jobs import _settings_from_explicit_context

        persisted = {
            "database_mdb": r"D:\old\old.mdb",
            "study_path": r"D:\old\old.zxst",
            "feeder_id": "OLD",
            "network_id": "NET_OLD",
        }
        with mock.patch("core.feeder_context.load_settings", return_value=persisted), \
                mock.patch(
                    "core.feeder_context.apply_context_selection",
                    side_effect=AssertionError("ordinary jobs must not persist context"),
                ):
            settings = _settings_from_explicit_context(CONTEXT, "HEADER_OLD")

        for key, value in CONTEXT.items():
            self.assertEqual(settings[key], value)
        self.assertRegex(settings["context_fingerprint"], r"^[0-9a-f]{16}$")

    def test_missing_or_inconsistent_context_fails_before_pipeline(self):
        from api_app.jobs import _run_action

        missing = dict(CONTEXT)
        missing.pop("network_id")
        with mock.patch(
            "pipeline.model_quality_gate.run_network_diagnostic"
        ) as pipeline:
            result = _run_action("calidad_diagnosticar", missing, "PE104")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CONTEXT_INCOMPLETE")
        self.assertFalse(pipeline.called)

        inconsistent = dict(CONTEXT, context_fingerprint="0000000000000000")
        with mock.patch(
            "pipeline.model_quality_gate.run_network_diagnostic"
        ) as pipeline:
            result = _run_action("calidad_diagnosticar", inconsistent, "PE104")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CONTEXT_IDENTITY_MISMATCH")
        self.assertFalse(pipeline.called)

    def test_result_echoes_context_and_rejects_pipeline_mismatch(self):
        from api_app.jobs import _annotate_context_result, _settings_from_explicit_context

        with mock.patch("core.feeder_context.load_settings", return_value={}):
            settings = _settings_from_explicit_context(CONTEXT, None)
        result = _annotate_context_result(settings, {"ok": True, "value": 7})
        for key, value in CONTEXT.items():
            self.assertEqual(result[key], value)
        self.assertEqual(result["context_fingerprint"], settings["context_fingerprint"])

        mismatch = _annotate_context_result(
            settings,
            {"ok": True, "feeder_id": "CA101", "network_id": "NET_CA101"},
        )
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["error_code"], "CONTEXT_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
