# -*- coding: utf-8 -*-
from __future__ import print_function

import json
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
    "network_id": "NET_2030_184_PE104",
}


class TestInformeContext(unittest.TestCase):
    def test_loadflow_records_four_field_identity(self):
        from core.report_provenance import tag_context

        tagged = tag_context(CTX, {"status": "ok", "scenario": "proyectado"})
        self.assertEqual(tagged["context_identity"]["feeder_id"], "PE104")
        self.assertEqual(tagged["context_identity"]["network_id"], CTX["network_id"])
        self.assertRegex(tagged["context_fingerprint"], r"^[0-9a-f]{16}$")

    def test_report_rejects_foreign_context_artifacts(self):
        from core.context_identity import ContextIdentityError
        from core.report_provenance import assert_report_context, tag_context

        foreign = tag_context(dict(CTX, feeder_id="CA101", network_id="NET_CA101"), {})
        with self.assertRaises(ContextIdentityError) as caught:
            assert_report_context(CTX, foreign)
        self.assertEqual(caught.exception.code, "CONTEXT_IDENTITY_MISMATCH")

    def test_report_same_feeder_different_mdb_is_not_reused(self):
        from core.context_identity import ContextIdentityError
        from core.report_provenance import assert_report_context, tag_context

        old = tag_context(dict(CTX, database_mdb=r"D:\old\redes.mdb"), {})
        with self.assertRaises(ContextIdentityError):
            assert_report_context(CTX, old)

    def test_close_requires_matching_fill_manifest(self):
        from core.report_provenance import require_matching_manifest, tag_context

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            path = os.path.join(work, "fill_manifest.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(tag_context(dict(CTX, network_id="NET_OTHER"), {"ok": True}), handle)
            result = require_matching_manifest(CTX, path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "CONTEXT_IDENTITY_MISMATCH")

    def test_preview_returns_context_identity(self):
        from core.report_provenance import tag_context

        preview = tag_context(CTX, {"ok": True, "preview_ok": True})
        self.assertEqual(preview["context_identity"]["database_mdb"], CTX["database_mdb"])
        self.assertEqual(preview["context_identity"]["study_path"], CTX["study_path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
