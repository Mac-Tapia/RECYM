# -*- coding: utf-8 -*-
"""Tests de contrato P0: security, readiness, health/ready/401 (sin abrir estudio)."""
from __future__ import print_function

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Entorno de prueba antes de importar la app
os.environ["RECYM_SPA"] = "1"
os.environ["RECYM_AUTH"] = "1"
os.environ["RECYM_ENV"] = "development"
os.environ["RECYM_ISOLATE_JOBS"] = "1"
os.environ.pop("RECYM_API_KEY", None)


class TestSecurityUnit(unittest.TestCase):
    def test_cors_no_wildcard(self):
        from api_app.security import cors_origins

        origins = cors_origins()
        self.assertTrue(origins)
        self.assertNotIn("*", origins)

    def test_api_key_stable(self):
        from api_app.security import get_or_create_api_key

        a = get_or_create_api_key()
        b = get_or_create_api_key()
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 16)

    def test_public_paths(self):
        from api_app.security import is_public_path

        self.assertTrue(is_public_path("/health"))
        self.assertTrue(is_public_path("/api/health"))
        self.assertTrue(is_public_path("/api/health/ready"))
        self.assertTrue(is_public_path("/api/auth/bootstrap"))
        self.assertTrue(is_public_path("/"))
        self.assertFalse(is_public_path("/api/tablero"))
        self.assertFalse(is_public_path("/api/jobs"))


class TestReadinessUnit(unittest.TestCase):
    def test_check_ready_shape(self):
        from api_app.readiness import check_ready

        r = check_ready()
        self.assertIn("ok", r)
        self.assertIn("status", r)
        self.assertIn("checks", r)
        self.assertIn("python", r["checks"])
        self.assertIn("isolation", r["checks"])


class TestIsolationUnit(unittest.TestCase):
    def test_should_isolate_actions(self):
        from core.cympy_isolation import should_isolate_action

        self.assertTrue(should_isolate_action("calidad_diagnosticar"))
        self.assertTrue(should_isolate_action("distribucion"))
        self.assertTrue(should_isolate_action("flujo"))
        self.assertFalse(should_isolate_action("build_tablero"))
        self.assertFalse(should_isolate_action(""))


class TestApiContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            from api_app.main import app
            from api_app.security import get_or_create_api_key

            cls.Client = TestClient
            cls.app = app
            cls.api_key = get_or_create_api_key()
        except Exception as ex:
            cls.app = None
            cls._import_error = ex

    def setUp(self):
        if self.app is None:
            self.skipTest("No se pudo importar app: %s" % getattr(self, "_import_error", "?"))

    def test_health_live(self):
        c = self.Client(self.app)
        r = c.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("status"), "live")
        self.assertIn("isolation", body)

    def test_health_ready(self):
        c = self.Client(self.app)
        r = c.get("/api/health/ready")
        self.assertIn(r.status_code, (200, 503))
        body = r.json()
        self.assertIn("ok", body)
        self.assertIn("checks", body)
        self.assertIn("status", body)

    def test_api_requires_key(self):
        c = self.Client(self.app)
        r = c.get("/api/spa/meta")
        # spa/meta es público
        self.assertEqual(r.status_code, 200)

        r2 = c.get("/api/tablero")
        # TestClient host != loopback → 401 sin key
        self.assertEqual(r2.status_code, 401)
        body = r2.json()
        self.assertFalse(body.get("ok", True))
        self.assertTrue(body.get("auth") or "API key" in str(body.get("error") or ""))

    def test_api_with_key(self):
        c = self.Client(self.app)
        r = c.get("/api/tablero", headers={"X-Api-Key": self.api_key})
        # Puede ser 200 con datos o error de negocio; no 401
        self.assertNotEqual(r.status_code, 401)

    def test_bootstrap_non_loopback_forbidden(self):
        c = self.Client(self.app)
        r = c.get("/api/auth/bootstrap")
        # host testclient no es loopback
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
