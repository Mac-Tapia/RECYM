# -*- coding: utf-8 -*-
"""§3.2 corre como job aislado; la GUI se reabre desde la API (proceso padre)."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("RECYM_SPA", "1")
os.environ.setdefault("RECYM_ISOLATE_JOBS", "1")


class TestClientesAplicarJob(unittest.TestCase):
    def test_action_is_isolated_protected_and_routed(self):
        from api_app.jobs import PROTECTED_CONTEXT_ACTIONS, legacy_route_for_action
        from core.cympy_isolation import ISOLATED_ACTIONS

        self.assertEqual(legacy_route_for_action("clientes_aplicar"), "/api/clientes/aplicar")
        self.assertIn("clientes_aplicar", ISOLATED_ACTIONS)
        self.assertIn("clientes_aplicar", PROTECTED_CONTEXT_ACTIONS)

    def test_gui_reopens_in_parent_with_job_context(self):
        from api_app import jobs

        seen = []
        payload = {"feeder_id": "SI213", "network_id": "NET_SI213",
                   "study_path": r"C:\e\SI213.zxst", "database_mdb": r"C:\e\b.mdb"}
        with mock.patch.object(jobs, "_settings_from_explicit_context",
                               side_effect=lambda p, f: dict(p, ctx=True)):
            thread = jobs.reopen_cymdist_gui_after_job(
                "clientes_aplicar", payload, "SI213", opener=seen.append, delay_sec=0
            )
            thread.join(5)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0]["ctx"])
        self.assertEqual(seen[0]["network_id"], "NET_SI213")

    def test_default_reopen_uses_persistent_apartment_and_retries(self):
        from api_app import jobs

        calls = []

        def fake_ensure(settings, selected_study=""):
            calls.append(selected_study)
            return {"ok": len(calls) > 1, "error": "referencia COM muerta"}

        with mock.patch.object(jobs, "_settings_from_explicit_context",
                               side_effect=lambda p, f: dict(p)),                 mock.patch("core.cymdist_com.ensure_feeder_study_com", fake_ensure):
            jobs.reopen_cymdist_gui_after_job(
                "clientes_aplicar", {"study_path": r"C:\e\SI213.zxst"}, "SI213", delay_sec=0
            ).join(5)
        self.assertEqual(calls, [r"C:\e\SI213.zxst", r"C:\e\SI213.zxst"])


class TestWorkerPreload(unittest.TestCase):
    def test_worker_loads_app_modules_before_any_cympy_call(self):
        """Orden de DLLs: el worker importa ui.demand_app antes de usar CymPy."""
        import subprocess

        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "import api_app.job_worker_cli as w;"
            "print(w.APP_PRELOAD.get('ok'), 'ui.demand_app' in sys.modules)"
        ) % os.path.join(ROOT, "src", "api_app")
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, universal_newlines=True, timeout=120,
            env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src")),
        )
        self.assertIn("True True", out.stdout, out.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
