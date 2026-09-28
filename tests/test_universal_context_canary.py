# -*- coding: utf-8 -*-
from __future__ import print_function

import argparse
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.validate_universal_context import run_canary


class FakeHttp(object):
    def __init__(self, mismatch=False):
        self.calls = []
        self.mismatch = mismatch

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path in ("/health", "/api/health/ready"):
            return 200, {"ok": True}
        if path == "/api/jobs":
            return 200, {"ok": True, "job_id": "job-1"}
        if path == "/api/jobs/job-1":
            return 200, {
                "ok": True,
                "job": {"status": "ok", "result": {"ok": True, "feeders": [{"feeder_id": "PE104", "network_id": "NET_PE104"}]}},
            }
        if path == "/api/contexto/aplicar":
            return 200, {"ok": True, "context_fingerprint": "wrong" if self.mismatch else body.get("context_fingerprint")}
        raise AssertionError("unexpected call %s %s" % (method, path))


def args(skip_apply=True):
    return argparse.Namespace(
        mdb=r"D:\bases\redes.mdb",
        study=r"D:\studies\multi.zxst",
        feeder="PE104",
        network="NET_PE104",
        base_url="http://local",
        api_key="",
        out="",
        skip_apply=skip_apply,
    )


class TestUniversalContextCanary(unittest.TestCase):
    def test_default_safe_path_only_discovers_and_checks_health(self):
        http = FakeHttp()
        result = run_canary(args(skip_apply=True), http=http)
        self.assertTrue(result["ok"])
        paths = [call[1] for call in http.calls]
        self.assertNotIn("/api/contexto/aplicar", paths)
        self.assertFalse(any("informe" in path for path in paths))

    def test_stops_on_identity_mismatch(self):
        http = FakeHttp(mismatch=True)
        result = run_canary(args(skip_apply=False), http=http)
        self.assertFalse(result["ok"])
        self.assertIn("CONTEXT_IDENTITY_MISMATCH", result["error"])
        self.assertFalse(any("informe" in call[1] for call in http.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
