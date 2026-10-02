# -*- coding: utf-8 -*-
"""Un Cyme colgado o caído no debe bloquear §1 hasta reiniciar la API."""
from __future__ import print_function

import os
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core import cymdist_com as com


class TestLiveComRecovery(unittest.TestCase):
    def setUp(self):
        com._abandon_live_com_worker()
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        com._abandon_live_com_worker()

    def _hanging_worker(self, requests):
        requests.get()
        self.release.wait(10)

    def _answering_worker(self, requests):
        while True:
            _op, _s, _v, response = requests.get()
            response.put({"ok": True, "feeders": ["SI213"]})

    def test_timeout_discards_stuck_worker_and_next_call_recovers(self):
        with mock.patch.object(com, "detect_cyme_crash_dialog", return_value=None), \
                mock.patch.object(com, "_live_com_worker", self._hanging_worker):
            first = com._run_live_com("list_database_feeders", {}, timeout=0.2)
        self.assertEqual(first["error_code"], "CYMDIST_COM_TIMEOUT")
        self.assertIsNone(com._LIVE_COM_THREAD)

        with mock.patch.object(com, "detect_cyme_crash_dialog", return_value=None), \
                mock.patch.object(com, "_live_com_worker", self._answering_worker):
            second = com._run_live_com("list_database_feeders", {}, timeout=2.0)
        self.assertTrue(second["ok"])

    def test_crash_dialog_fails_fast_without_queueing(self):
        crash = "Exception 0xc0000005: Access violation"
        with mock.patch.object(com, "detect_cyme_crash_dialog", return_value=crash), \
                mock.patch.object(com, "_live_com_worker", self._hanging_worker):
            result = com._run_live_com("list_database_feeders", {}, timeout=5.0)
        self.assertEqual(result["error_code"], "CYMDIST_CRASHED")
        self.assertIn("0xc0000005", result["detail"])
        self.assertIsNone(com._LIVE_COM_THREAD)

    def test_detector_is_safe_without_dialog(self):
        self.assertIsNone(com.detect_cyme_crash_dialog())


if __name__ == "__main__":
    unittest.main()
