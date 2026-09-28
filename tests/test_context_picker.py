# -*- coding: utf-8 -*-
from __future__ import print_function

import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class FakeCompleted(object):
    def __init__(self, payload=None, returncode=0, stderr=""):
        self.stdout = json.dumps(payload or {})
        self.stderr = stderr
        self.returncode = returncode


class TestContextPicker(unittest.TestCase):
    def _runner(self, payload=None, returncode=0, stderr=""):
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            return FakeCompleted(payload, returncode=returncode, stderr=stderr)

        run.calls = calls
        return run

    def test_database_and_study_paths_are_validated(self):
        from core.windows_file_picker import pick_context_file

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb = os.path.join(work, "redes.mdb")
            study = os.path.join(work, "multi.zxst")
            with open(mdb, "wb") as handle:
                handle.write(b"mdb")
            with open(study, "wb") as handle:
                handle.write(b"study" * 300)

            db = pick_context_file("database", runner=self._runner({"path": mdb}))
            st = pick_context_file("study", runner=self._runner({"path": study}))

            self.assertTrue(db["ok"])
            self.assertEqual(db["kind"], "database")
            self.assertTrue(os.path.isabs(db["path"]))
            self.assertTrue(st["ok"])
            self.assertEqual(st["kind"], "study")

    def test_cancel_returns_success_without_path(self):
        from core.windows_file_picker import pick_context_file

        result = pick_context_file("database", runner=self._runner({"cancelled": True}))
        self.assertEqual(result, {"ok": True, "cancelled": True, "kind": "database"})

    def test_invalid_picker_kind(self):
        from core.windows_file_picker import pick_context_file

        result = pick_context_file("image", runner=self._runner({"cancelled": True}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_PICKER_KIND")

    def test_nonexistent_file(self):
        from core.windows_file_picker import pick_context_file

        result = pick_context_file(
            "database", runner=self._runner({"path": r"D:\missing\redes.mdb"})
        )
        self.assertEqual(result["error_code"], "FILE_NOT_FOUND")

    def test_wrong_extension(self):
        from core.windows_file_picker import pick_context_file

        with tempfile.NamedTemporaryFile(suffix=".txt", dir=ROOT, delete=False) as handle:
            path = handle.name
        try:
            result = pick_context_file("database", runner=self._runner({"path": path}))
        finally:
            os.unlink(path)
        self.assertEqual(result["error_code"], "INVALID_FILE_EXTENSION")

    def test_too_small_study_is_invalid(self):
        from core.windows_file_picker import pick_context_file

        with tempfile.NamedTemporaryFile(suffix=".zxst", dir=ROOT, delete=False) as handle:
            handle.write(b"small")
            path = handle.name
        try:
            result = pick_context_file("study", runner=self._runner({"path": path}))
        finally:
            os.unlink(path)
        self.assertEqual(result["error_code"], "STUDY_FILE_INVALID")

    def test_timeout(self):
        from core.windows_file_picker import pick_context_file

        def timeout_runner(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

        result = pick_context_file("database", timeout=1, runner=timeout_runner)
        self.assertEqual(result["error_code"], "PICKER_TIMEOUT")

    def test_powershell_failure(self):
        from core.windows_file_picker import pick_context_file

        result = pick_context_file(
            "study", runner=self._runner(returncode=1, stderr="PowerShell failed")
        )
        self.assertEqual(result["error_code"], "PICKER_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
