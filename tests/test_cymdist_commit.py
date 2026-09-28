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


class FakeAdapter(object):
    def __init__(self, study_path):
        self.study_path = study_path
        self.study_saves = 0
        self.db_updates = 0
        self.project_saves = 0
        self.values = {}

    def save_study(self, path=""):
        self.study_saves += 1
        with open(path or self.study_path, "ab") as handle:
            handle.write(b"|saved")

    def update_database(self):
        self.db_updates += 1

    def save_project(self):
        self.project_saves += 1


class TestCymdistCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.study = os.path.join(self.tmp.name, "multi study.zxst")
        self.mdb = os.path.join(self.tmp.name, "network.mdb")
        with open(self.study, "wb") as handle:
            handle.write(b"study-v1")
        with open(self.mdb, "wb") as handle:
            handle.write(b"mdb-v1")
        self.settings = {
            "study_path": self.study,
            "database_mdb": self.mdb,
            "feeder_id": "PE104",
            "network_id": "NET_PE104",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, mode, adapter=None, **kwargs):
        from core.cymdist_commit import CommitRequest

        return CommitRequest(
            settings=dict(self.settings),
            action=kwargs.pop("action", "test_action"),
            mode=mode,
            adapter=adapter or FakeAdapter(self.study),
            manifest_dir=os.path.join(self.tmp.name, "manifests"),
            **kwargs
        )

    def test_lock_key_uses_canonical_study_path(self):
        from core.cymdist_commit import study_lock_key

        self.assertEqual(study_lock_key(self.study), study_lock_key(os.path.join(self.tmp.name, ".", "multi study.zxst")))

    def test_read_operation_cannot_request_commit(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        result = commit_cymdist_action(self.request(CommitMode.READ), lambda: {"requested_values": {"x": 1}})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "READ_OPERATION_CANNOT_COMMIT")

    def test_study_commit_saves_once(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        adapter = FakeAdapter(self.study)
        result = commit_cymdist_action(
            self.request(CommitMode.STUDY, adapter, readback=lambda: {"x": 1}),
            lambda: {"requested_values": {"x": 1}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(adapter.study_saves, 1)
        self.assertTrue(result["reopen_verified"])

    def test_database_commit_calls_update_and_save_project_once(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        adapter = FakeAdapter(self.study)
        result = commit_cymdist_action(
            self.request(CommitMode.STUDY_AND_DATABASE, adapter, readback=lambda: {"x": 1}),
            lambda: {"requested_values": {"x": 1}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual((adapter.study_saves, adapter.db_updates, adapter.project_saves), (1, 1, 1))

    def test_external_engine_saved_does_not_save_twice(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        adapter = FakeAdapter(self.study)
        result = commit_cymdist_action(
            self.request(CommitMode.EXTERNAL_ENGINE_SAVED, adapter, readback=lambda: {"x": 1}),
            lambda: {"requested_values": {"x": 1}, "external_engine_saved": True},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(adapter.study_saves, 0)

    def test_failed_save_preserves_backup(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        adapter = FakeAdapter(self.study)
        adapter.save_study = lambda path="": (_ for _ in ()).throw(RuntimeError("save failed"))
        result = commit_cymdist_action(self.request(CommitMode.STUDY, adapter), lambda: {"requested_values": {"x": 1}})
        self.assertFalse(result["ok"])
        self.assertTrue(os.path.isfile(result["backup_path"]))
        self.assertEqual(result["error_code"], "CYMDIST_SAVE_FAILED")

    def test_readback_mismatch_fails_closed(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action

        result = commit_cymdist_action(
            self.request(CommitMode.STUDY, readback=lambda: {"x": 2}),
            lambda: {"requested_values": {"x": 1}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "READBACK_MISMATCH")

    def test_two_network_commits_preserve_a_after_b(self):
        from core.cymdist_commit import CommitMode, commit_cymdist_action
        from pipeline.verify_cymdist_commit import verify_commit

        state = {"NET_A": 0, "NET_B": 0}
        manifests = []
        for network, value in (("NET_A", 10), ("NET_B", 20)):
            settings = dict(self.settings, network_id=network, feeder_id=network)
            from core.cymdist_commit import CommitRequest
            request = CommitRequest(
                settings=settings,
                action="write_%s" % network,
                mode=CommitMode.STUDY,
                adapter=FakeAdapter(self.study),
                manifest_dir=os.path.join(self.tmp.name, "manifests"),
                readback=lambda n=network: {"value": state[n]},
                inventory=lambda: dict(state),
            )
            result = commit_cymdist_action(
                request,
                lambda n=network, v=value: (state.__setitem__(n, v) or {"requested_values": {"value": v}}),
            )
            self.assertTrue(result["ok"])
            manifests.append(result["manifest_path"])
        self.assertEqual(state, {"NET_A": 10, "NET_B": 20})
        self.assertTrue(all(verify_commit(path)["ok"] for path in manifests))


if __name__ == "__main__":
    unittest.main(verbosity=2)
