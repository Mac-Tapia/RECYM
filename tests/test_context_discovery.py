# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _network(feeder, suffix):
    return {
        "feeder_id": feeder,
        "network_id": "NET_%s_%s" % (suffix, feeder),
        "label": "%s · NET_%s_%s" % (feeder, suffix, feeder),
    }


class TestContextDiscovery(unittest.TestCase):
    def setUp(self):
        from pipeline.model_quality_gate import clear_networks_cache

        clear_networks_cache()

    def test_same_basename_databases_do_not_share_cache(self):
        from pipeline.model_quality_gate import list_bd_networks

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            first = os.path.join(work, "A", "redes.mdb")
            second = os.path.join(work, "B", "redes.mdb")
            os.makedirs(os.path.dirname(first))
            os.makedirs(os.path.dirname(second))
            open(first, "wb").close()
            open(second, "wb").close()

            def disk(_connection="", database_mdb=""):
                if os.path.normcase(database_mdb) == os.path.normcase(first):
                    return [_network("PE104", "184")], "redes"
                return [_network("CA101", "131")], "redes"

            with mock.patch("pipeline.model_quality_gate._load_networks_disk", side_effect=disk):
                a = list_bd_networks(
                    {"database_mdb": first, "database_connection_name": "redes"}
                )
                b = list_bd_networks(
                    {"database_mdb": second, "database_connection_name": "redes"}
                )

        self.assertEqual(a["networks"][0]["feeder_id"], "PE104")
        self.assertEqual(b["networks"][0]["feeder_id"], "CA101")
        self.assertNotEqual(a["database_key"], b["database_key"])

    def test_detached_discovery_does_not_write_settings_or_catalog(self):
        from api_app.jobs import run_action_inprocess

        settings_path = os.path.join(ROOT, "config", "settings.json")
        with open(settings_path, "rb") as handle:
            before = handle.read()
        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            result_value = {
                "ok": True,
                "source": "cympy",
                "database_mdb": mdb,
                "networks": [_network("PE104", "184")],
                "n": 1,
            }
            with mock.patch(
                "pipeline.model_quality_gate.list_bd_networks", return_value=result_value
            ) as discover, mock.patch(
                "pipeline.model_quality_gate._save_networks_disk"
            ) as save_disk:
                result = run_action_inprocess(
                    "contexto_descubrir_redes", {"database_mdb": mdb}, None
                )
            with open(settings_path, "rb") as handle:
                after = handle.read()
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cympy")
        self.assertEqual(result["feeders"], [_network("PE104", "184")])
        self.assertEqual(before, after)
        self.assertFalse(save_disk.called)
        self.assertTrue(discover.call_args[1]["force"])
        self.assertFalse(discover.call_args[1]["persist_cache"])

    def test_discovery_rejects_non_mdb(self):
        from api_app.jobs import run_action_inprocess

        with tempfile.NamedTemporaryFile(suffix=".txt", dir=ROOT, delete=False) as handle:
            path = handle.name
        try:
            result = run_action_inprocess(
                "contexto_descubrir_redes", {"database_mdb": path}, None
            )
        finally:
            os.unlink(path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "INVALID_FILE_EXTENSION")

    def test_no_networks_is_structured_error(self):
        from api_app.jobs import run_action_inprocess

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            with mock.patch(
                "pipeline.model_quality_gate.list_bd_networks",
                return_value={
                    "ok": True,
                    "source": "cympy",
                    "database_mdb": mdb,
                    "networks": [],
                    "n": 0,
                },
            ):
                result = run_action_inprocess(
                    "contexto_descubrir_redes", {"database_mdb": mdb}, None
                )
        finally:
            os.unlink(mdb)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "NO_NETWORKS_FOUND")

    def test_discovery_action_is_isolated(self):
        from core.cympy_isolation import should_isolate_action

        self.assertTrue(should_isolate_action("contexto_descubrir_redes"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
