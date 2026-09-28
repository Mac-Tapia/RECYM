# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class TestMutatingActionCommitContract(unittest.TestCase):
    def test_every_mutating_action_has_required_mode(self):
        from core.cymdist_commit import CommitMode, commit_mode_for_action

        expected = {
            "cabecera_12": CommitMode.STUDY_AND_DATABASE,
            "calidad_aplicar_23": CommitMode.STUDY_AND_DATABASE,
            "clientes_inclusiones": CommitMode.STUDY,
            "clientes_refresh_31": CommitMode.STUDY,
            "clientes_aplicar_32": CommitMode.STUDY,
            "distribucion_33": CommitMode.EXTERNAL_ENGINE_SAVED,
            "spotload_4": CommitMode.STUDY,
        }
        for action, mode in expected.items():
            self.assertEqual(commit_mode_for_action(action), mode)

    def test_unverified_commit_cannot_report_ok(self):
        from core.cymdist_commit import require_verified_commit

        result = require_verified_commit({"ok": True, "commit": {"ok": True, "reopen_verified": False}})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "COMMIT_NOT_VERIFIED")

    def test_verified_commit_exposes_backup_manifest_and_readback(self):
        from core.cymdist_commit import require_verified_commit

        payload = {
            "ok": True,
            "commit": {
                "ok": True,
                "reopen_verified": True,
                "backup_path": "backup.zxst",
                "manifest_path": "commit.json",
                "requested_values": {"network_id": "NET_A"},
                "readback_values": {"network_id": "NET_A"},
            },
        }
        self.assertIs(require_verified_commit(payload), payload)

    def test_job_source_wraps_33_without_second_save(self):
        path = os.path.join(ROOT, "src", "api_app", "jobs.py")
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('action="distribucion_33"', source)
        self.assertIn("CommitMode.EXTERNAL_ENGINE_SAVED", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
