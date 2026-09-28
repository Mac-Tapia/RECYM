# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import json
import subprocess
import sys
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ.setdefault("RECYM_SPA", "1")
os.environ.setdefault("RECYM_AUTH", "1")
os.environ.setdefault("RECYM_ENV", "development")
os.environ.setdefault("RECYM_ISOLATE_JOBS", "1")


class TestLaunchAndVersionContract(unittest.TestCase):
    def test_production_launcher_resolves_existing_target(self):
        env = os.environ.copy()
        env["RECYM_LAUNCHER_VALIDATE_ONLY"] = "1"
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", os.path.join(ROOT, "scripts", "20_demand_ui_production.bat")],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("LAUNCHER OK", proc.stdout)

    def test_fastapi_and_flask_report_same_ui_version(self):
        from fastapi.testclient import TestClient
        from api_app.main import app
        from api_app.security import get_or_create_api_key

        client = TestClient(app)
        headers = {"X-Api-Key": get_or_create_api_key()}
        fastapi_version = client.get("/health").json()["ui_version"]
        flask_version = client.get("/api/ui/ping", headers=headers).json()["ui_version"]
        self.assertEqual(flask_version, fastapi_version)


class TestFeederInputContract(unittest.TestCase):
    def test_positional_feeder_parser_rejects_test_selectors(self):
        from core.feeder_context import _parse_feeder_arg

        self.assertEqual(_parse_feeder_arg(["PA217"]), "PA217")
        self.assertIsNone(_parse_feeder_arg(["TestFeederInputContract"]))

    def test_ca101_network_mismatch_is_blocking(self):
        from pipeline.validate_inputs import inspect_feeder_inputs

        settings = {
            "feeder_id": "CA101",
            "network_id": "NET_2030_131_CA101",
        }
        control = {
            "NetworkID": "NET_2030_179_PA217",
            "Tension_MT_LL": 10,
            "Demanda_Max_Cabecera_kW": 100,
            "Escenario_Base": "BASE",
        }
        with mock.patch("pipeline.validate_inputs.control_path", return_value="control.xlsx"), \
                mock.patch("pipeline.validate_inputs.catalog_path", return_value="catalog.xlsx"), \
                mock.patch("pipeline.validate_inputs.os.path.isfile", return_value=True), \
                mock.patch("pipeline.validate_inputs.read_kv", return_value=control), \
                mock.patch("pipeline.validate_inputs.read_rows", return_value=[]):
            result = inspect_feeder_inputs(settings)
        self.assertFalse(result["ok"])
        self.assertFalse(result["inputs_ready"])
        self.assertIn("NETWORK_ID_MISMATCH", [x["code"] for x in result["errors"]])
        self.assertEqual(result["network_id_config"], "NET_2030_131_CA101")
        self.assertEqual(result["network_id_excel"], "NET_2030_179_PA217")

    def test_missing_feeder_files_are_structured_errors(self):
        from core.feeder_context import load_settings
        from pipeline.validate_inputs import inspect_feeder_inputs

        result = inspect_feeder_inputs(load_settings(feeder_id="AL104"))
        self.assertFalse(result["ok"])
        codes = [x["code"] for x in result["errors"]]
        self.assertIn("CONTROL_WORKBOOK_MISSING", codes)
        self.assertIn("CATALOG_WORKBOOK_MISSING", codes)

    def test_context_catalog_reports_capability(self):
        from fastapi.testclient import TestClient
        from api_app.main import app
        from api_app.security import get_or_create_api_key

        client = TestClient(app)
        response = client.get(
            "/api/contexto/archivos",
            headers={"X-Api-Key": get_or_create_api_key()},
        )
        self.assertEqual(response.status_code, 200)
        rows = response.json()["feeders"]
        ca101 = next(x for x in rows if x["feeder_id"] == "CA101")
        self.assertIn("operational", ca101)
        self.assertIn("inputs_ready", ca101)
        self.assertIn("input_errors", ca101)
        self.assertTrue(ca101["operational"])
        self.assertFalse(ca101["inputs_ready"])

    def test_http_validation_rejects_network_mismatch(self):
        from fastapi.testclient import TestClient
        from api_app.main import app
        from api_app.security import get_or_create_api_key

        client = TestClient(app)
        response = client.post(
            "/api/suite/validar_entradas",
            headers={"X-Api-Key": get_or_create_api_key(), "X-Feeder": "CA101"},
            json={"feeder": "CA101"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])


class TestSuiteWorkerIsolation(unittest.TestCase):
    ACTIONS = {
        "optimizacion_reclosers": "/api/optimizacion/reclosers",
        "optimizacion_regulators": "/api/optimizacion/regulators",
        "optimizacion_capacitors": "/api/optimizacion/capacitors",
        "suite_conexion": "/api/suite/conexion",
        "suite_inventario_cargas": "/api/suite/inventario_cargas",
        "suite_sync_equipos": "/api/suite/sync_equipos",
        "suite_fix_default": "/api/suite/fix_default",
        "suite_export_ascii": "/api/suite/export_ascii",
        "suite_pipeline": "/api/suite/pipeline",
        "clientes_activo_cymdist": "/api/clientes/activo",
    }

    def test_all_cymdist_suite_actions_are_isolated(self):
        from core.cympy_isolation import should_isolate_action

        for action in self.ACTIONS:
            self.assertTrue(should_isolate_action(action), action)

    def test_react_has_no_direct_optimization_launch(self):
        pages = os.path.join(ROOT, "web", "src", "pages")
        for name in os.listdir(pages):
            if not name.endswith(".tsx"):
                continue
            with open(os.path.join(pages, name), "r", encoding="utf-8") as f:
                source = f.read()
            self.assertNotIn("api<Json>(`/api/optimizacion/", source, name)

    def test_react_never_calls_clientes_activo_directly_with_cymdist_true(self):
        pages = os.path.join(ROOT, "web", "src", "pages")
        for name in os.listdir(pages):
            if not name.endswith(".tsx"):
                continue
            with open(os.path.join(pages, name), "r", encoding="utf-8") as f:
                source = f.read()
            self.assertNotIn("apply_cymdist: true", source, name)

    def test_legacy_job_routes_are_exactly_allowlisted(self):
        from api_app.jobs import legacy_route_for_action

        for action, path in self.ACTIONS.items():
            self.assertEqual(legacy_route_for_action(action), path)
        with self.assertRaises(ValueError):
            legacy_route_for_action("suite_../../contexto/aplicar")
        with self.assertRaises(ValueError):
            legacy_route_for_action("unknown")

    def test_excel_dependent_worker_action_fails_closed(self):
        from api_app.jobs import run_action_inprocess

        tracked = [
            os.path.join(ROOT, "config", "settings.json"),
            os.path.join(ROOT, "config", "feeders", "CA101.json"),
        ]
        def read_bytes(path):
            with open(path, "rb") as f:
                return f.read()

        before = {path: read_bytes(path) for path in tracked}
        result = run_action_inprocess("suite_sync_equipos", {}, "CA101")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INPUTS_NOT_READY")
        self.assertTrue(result["errors"])
        after = {path: read_bytes(path) for path in tracked}
        self.assertEqual(after, before)


class TestWorkerResultHandoff(unittest.TestCase):
    def test_result_is_durable_before_immediate_worker_exit(self):
        import tempfile

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            out_path = os.path.join(work, "worker-result.json")
            code = (
                "from api_app.job_worker_cli import write_result_and_exit; "
                "write_result_and_exit(%r, {'ok': True, 'marker': 'durable'}, 0)"
                % out_path
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join([SRC, env.get("PYTHONPATH", "")])
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(out_path, "r", encoding="utf-8") as f:
                result = json.load(f)
            self.assertEqual(result, {"ok": True, "marker": "durable"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
