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

    def test_prepare_transfer_updates_both_networks(self):
        from api_app.routers import context

        body = context.TransferPrepareRequest(
            database_mdb=r"C:\redes\modelo.mdb",
            study_path=r"C:\proyectos\estudio.zxst",
            feeder_id="CA101",
            network_id="NET_CA101",
            allowed_networks=[],
            peer_feeder_id="CN101",
            peer_network_id="NET_CN101",
        )
        loaded = {"ok": True, "loaded_networks": ["NET_CA101", "NET_CN101"]}
        with mock.patch.object(context, "context_load_transfer", return_value=loaded), \
                mock.patch(
                    "core.feeder_context.load_settings",
                    return_value={},
                ), \
                mock.patch(
                    "pipeline.apply_max_demand_multi.apply_max_demand_multi",
                    return_value={"ok": True, "n_ok": 2},
                ) as apply_max:
            result = context.context_prepare_transfer(body)

        self.assertTrue(result["ok"])
        self.assertTrue(result["prepared"])
        self.assertEqual(result["network_ids"], ["NET_CA101", "NET_CN101"])
        self.assertEqual(result["transfer_pair"], ["CA101", "CN101"])
        self.assertEqual(apply_max.call_args[1]["network_ids"], ["NET_CA101", "NET_CN101"])

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

    def test_live_cymdist_discovery_activates_mdb_and_reads_feeders(self):
        from core.cymdist_com import list_database_feeders_com

        class Feeder(object):
            def __init__(self, network_id):
                self.ID = network_id

        class FakeApp(object):
            def __init__(self):
                self.objFeedersInNetwork = [
                    Feeder("NET_2030_184_PE104"),
                    Feeder("NET_2030_131_CA101"),
                ]
                self.selected = None
                self.shown = []

            def ShowWindow(self, value):
                self.shown.append(value)

            def SelectUniqueDatabaseAccess(self, path, database_type, version):
                self.selected = (path, database_type, version)
                return 0

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            app = FakeApp()
            result = list_database_feeders_com(
                {"database_mdb": mdb}, app=app, access_version=2000
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cymdist_com")
        self.assertTrue(result["cymdist_open"])
        self.assertEqual(app.shown, [1])
        self.assertEqual(app.selected[0], os.path.abspath(mdb))
        self.assertEqual(
            [row["feeder_id"] for row in result["networks"]],
            ["CA101", "PE104"],
        )

    def test_fresh_cymdist_selects_network_and_equipment_database_together(self):
        """Una sesión limpia no debe depender de una base de equipos anterior."""
        from core.cymdist_com import list_database_feeders_com

        class Feeder(object):
            ID = "NET_2030_184_PE104"

        class FreshApp(object):
            def __init__(self):
                self.objFeedersInNetwork = []
                self.selected = None

            def ShowWindow(self, _value):
                return None

            def SelectUniqueDatabaseAccess(self, _path, _database_type, _version):
                return 0

            def SelectDatabaseAccess(self, equipment, network, version):
                self.selected = (equipment, network, version)
                self.objFeedersInNetwork = [Feeder()]
                return 0

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            app = FreshApp()
            result = list_database_feeders_com(
                {"database_mdb": mdb, "catalog_wait_seconds": 0},
                app=app,
                access_version=2000,
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["db_activate_method"], "SelectDatabaseAccess")
        self.assertEqual(app.selected[:2], (os.path.abspath(mdb), os.path.abspath(mdb)))

    def test_live_cymdist_discovery_waits_until_catalog_is_populated(self):
        """Evita aceptar el vacío transitorio posterior a activar una MDB."""
        from core.cymdist_com import list_database_feeders_com

        class Feeder(object):
            def __init__(self, network_id):
                self.ID = network_id

        class DelayedCatalogApp(object):
            def __init__(self):
                self.reads = 0

            def ShowWindow(self, _value):
                return None

            def SelectUniqueDatabaseAccess(self, _path, _database_type, _version):
                return 0

            @property
            def objFeedersInNetwork(self):
                self.reads += 1
                if self.reads < 3:
                    return []
                return [Feeder("NET_2030_184_PE104")]

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            app = DelayedCatalogApp()
            result = list_database_feeders_com(
                {
                    "database_mdb": mdb,
                    "catalog_wait_seconds": 0.2,
                    "catalog_poll_seconds": 0.001,
                },
                app=app,
                access_version=2000,
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["networks"][0]["feeder_id"], "PE104")
        self.assertGreaterEqual(app.reads, 3)

    def test_live_discovery_recovers_a_stale_cymdist_session_once(self):
        """Una sesión sin catálogo se cierra por COM y se reemplaza una vez."""
        from core.cymdist_com import discover_database_feeders_with_recovery

        class Feeder(object):
            def __init__(self, network_id):
                self.ID = network_id

        class App(object):
            def __init__(self, feeders):
                self.objFeedersInNetwork = feeders
                self.closed = False

            def ShowWindow(self, _value):
                return None

            def SelectUniqueDatabaseAccess(self, _path, _database_type, _version):
                return 0

            def Close(self):
                self.closed = True

        stale = App([])
        fresh = App([Feeder("NET_2030_184_PE104")])
        acquired = []

        def acquire(_settings, show_window=True):
            acquired.append(show_window)
            return fresh, "create_fresh"

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            result, active, mode = discover_database_feeders_with_recovery(
                {
                    "database_mdb": mdb,
                    "catalog_wait_seconds": 0,
                    "catalog_recovery_wait_seconds": 0,
                },
                app=stale,
                mode="create_or_reuse",
                access_version=2000,
                acquire=acquire,
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 1)
        self.assertTrue(stale.closed)
        self.assertIs(active, fresh)
        self.assertEqual(mode, "create_fresh")
        self.assertEqual(acquired, [True])

    def test_live_discovery_retries_while_previous_cymdist_process_is_exiting(self):
        """La recuperación ocurre en el mismo clic aunque el primer proxy ya murió."""
        from core.cymdist_com import discover_database_feeders_with_recovery

        class Feeder(object):
            def __init__(self, network_id):
                self.ID = network_id

        class App(object):
            def __init__(self, feeders=None, broken=False):
                self.feeders = feeders or []
                self.broken = broken

            def ShowWindow(self, _value):
                return None

            def SelectUniqueDatabaseAccess(self, _path, _database_type, _version):
                if self.broken:
                    raise RuntimeError("RPC unavailable")
                return 0

            @property
            def objFeedersInNetwork(self):
                return self.feeders

            def Close(self):
                return None

        stale = App([])
        dying_proxy = App(broken=True)
        fresh = App([Feeder("NET_2030_184_PE104")])
        acquired = [dying_proxy, fresh]

        def acquire(_settings, show_window=True):
            return acquired.pop(0), "create_or_reuse"

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            result, active, _mode = discover_database_feeders_with_recovery(
                {
                    "database_mdb": mdb,
                    "catalog_wait_seconds": 0,
                    "catalog_recovery_wait_seconds": 0,
                    "catalog_recovery_attempts": 2,
                },
                app=stale,
                mode="create_or_reuse",
                access_version=2000,
                acquire=acquire,
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 1)
        self.assertIs(active, fresh)
        self.assertEqual(acquired, [])

    def test_live_discovery_recovers_initial_com_server_exception(self):
        """Una excepción del servidor COM también debe recuperarse en el mismo clic."""
        from core.cymdist_com import discover_database_feeders_with_recovery

        class Feeder(object):
            ID = "NET_2030_184_PE104"

        class BrokenApp(object):
            def ShowWindow(self, _value):
                raise RuntimeError("server exception")

            def Close(self):
                return None

        class FreshApp(object):
            objFeedersInNetwork = [Feeder()]

            def ShowWindow(self, _value):
                return None

            def SelectDatabaseAccess(self, _equipment, _network, _version):
                return 0

            def Close(self):
                return None

        fresh = FreshApp()

        with tempfile.NamedTemporaryFile(suffix=".mdb", dir=ROOT, delete=False) as handle:
            mdb = handle.name
        try:
            result, active, _mode = discover_database_feeders_with_recovery(
                {
                    "database_mdb": mdb,
                    "catalog_wait_seconds": 0,
                    "catalog_recovery_wait_seconds": 0,
                },
                app=BrokenApp(),
                mode="create_or_reuse",
                access_version=2000,
                acquire=lambda _settings, show_window=True: (fresh, "create_fresh"),
            )
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["n"], 1)
        self.assertIs(active, fresh)

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
                "source": "cymdist_com",
                "database_mdb": mdb,
                "networks": [_network("PE104", "184")],
                "n": 1,
            }
            with mock.patch(
                "core.cymdist_com.list_database_feeders_com", return_value=result_value
            ) as discover:
                result = run_action_inprocess(
                    "contexto_descubrir_redes", {"database_mdb": mdb}, None
                )
            with open(settings_path, "rb") as handle:
                after = handle.read()
        finally:
            os.unlink(mdb)

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "cymdist_com")
        self.assertEqual(result["feeders"], [_network("PE104", "184")])
        self.assertEqual(before, after)
        discover.assert_called_once()
        self.assertEqual(discover.call_args[0][0]["database_mdb"], os.path.abspath(mdb))

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
                "core.cymdist_com.list_database_feeders_com",
                return_value={
                    "ok": True,
                    "source": "cymdist_com",
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

        self.assertFalse(should_isolate_action("contexto_descubrir_redes"))


class TestEnsureFeederStudyCom(unittest.TestCase):
    class Feeder(object):
        def __init__(self, network_id):
            self.ID = network_id

    class Study(object):
        def __init__(self, app):
            self.app = app
            self.loaded = []

        def LoadFeederFromID(self, network_id):
            self.loaded.append(network_id)
            self.app.objFeedersInMemory = [TestEnsureFeederStudyCom.Feeder(network_id)]

        def SaveAs(self, path):
            with open(path, "wb") as handle:
                handle.write(b"study" * 300)

    class App(object):
        def __init__(self, existing_network=None):
            self.objFeedersInMemory = []
            self.new_calls = 0
            self.open_calls = []
            self.selected = None
            self.existing_network = existing_network

        def ShowWindow(self, value):
            return value

        def SelectUniqueDatabaseAccess(self, path, database_type, version):
            self.selected = path
            return 0

        def OpenStudy(self, path):
            self.open_calls.append(path)
            if self.existing_network:
                self.objFeedersInMemory = [
                    TestEnsureFeederStudyCom.Feeder(self.existing_network)
                ]
            return TestEnsureFeederStudyCom.Study(self)

        def NewStudy(self):
            self.new_calls += 1
            self.objFeedersInMemory = []
            return TestEnsureFeederStudyCom.Study(self)

    def test_creates_loads_verifies_and_saves_selected_feeder(self):
        from core.cymdist_com import ensure_feeder_study_com

        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb = os.path.join(work, "redes.mdb")
            with open(mdb, "wb") as handle:
                handle.write(b"mdb")
            app = self.App()
            result = ensure_feeder_study_com(
                {
                    "database_mdb": mdb,
                    "projects_dir": work,
                    "feeder_id": "AL209",
                    "network_id": "NET_2030_861579_AL209",
                },
                selected_study="",
                app=app,
                access_version=2000,
            )

            self.assertTrue(result["ok"])
            self.assertTrue(result["created"])
            self.assertEqual(os.path.basename(result["study_path"]), "AL209.zxst")
            self.assertTrue(os.path.isfile(result["study_path"]))
            self.assertEqual(result["loaded_networks"], ["NET_2030_861579_AL209"])
            self.assertEqual(app.new_calls, 1)

    def test_creation_matrix_uses_each_mdb_and_network_without_hardcoded_feeder(self):
        from core.cymdist_com import ensure_feeder_study_com

        cases = [
            ("AL209", "NET_2030_861579_AL209", "database north.mdb"),
            ("TM105", "NET_2030_174_TM105", "database south.mdb"),
            ("XX999", "NET_CUSTOM_999", "customer model.mdb"),
        ]
        with tempfile.TemporaryDirectory(dir=ROOT) as root:
            for feeder_id, network_id, database_name in cases:
                with self.subTest(feeder_id=feeder_id, database_name=database_name):
                    work = os.path.join(root, feeder_id)
                    os.makedirs(work)
                    mdb = os.path.join(work, database_name)
                    with open(mdb, "wb") as handle:
                        handle.write(b"mdb")
                    app = self.App()
                    result = ensure_feeder_study_com(
                        {
                            "database_mdb": mdb,
                            "projects_dir": work,
                            "feeder_id": feeder_id,
                            "network_id": network_id,
                        },
                        selected_study="",
                        app=app,
                        access_version=2000,
                    )

                    self.assertTrue(result["ok"], result)
                    self.assertTrue(result["created"])
                    self.assertEqual(result["database_mdb"], os.path.abspath(mdb))
                    self.assertEqual(result["loaded_networks"], [network_id])
                    self.assertEqual(
                        os.path.basename(result["study_path"]), feeder_id + ".zxst"
                    )

    def test_reuses_existing_study_only_when_it_contains_selected_network(self):
        from core.cymdist_com import ensure_feeder_study_com

        network_id = "NET_2030_861579_AL209"
        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb = os.path.join(work, "redes.mdb")
            study = os.path.join(work, "AL209.sxst")
            for path, data in ((mdb, b"mdb"), (study, b"study" * 300)):
                with open(path, "wb") as handle:
                    handle.write(data)
            app = self.App(existing_network=network_id)
            result = ensure_feeder_study_com(
                {
                    "database_mdb": mdb,
                    "projects_dir": work,
                    "feeder_id": "AL209",
                    "network_id": network_id,
                },
                selected_study=study,
                app=app,
                access_version=2000,
            )

        self.assertTrue(result["ok"])
        self.assertFalse(result["created"])
        self.assertEqual(result["study_path"], os.path.abspath(study))

    def test_retries_existing_study_when_cymdist_is_temporarily_busy(self):
        """Un RPC ocupado no autoriza crear un estudio sustituto."""
        from core.cymdist_com import ensure_feeder_study_com

        class BusyApp(self.App):
            def __init__(self, existing_network):
                super(BusyApp, self).__init__(existing_network=existing_network)
                self.attempts = 0

            def OpenStudy(self, path):
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("servidor ocupado")
                return super(BusyApp, self).OpenStudy(path)

        network = "NET_2030_861579_AL209"
        with tempfile.TemporaryDirectory(dir=ROOT) as work:
            mdb = os.path.join(work, "260924.mdb")
            study = os.path.join(work, "AL209.sxst")
            for path, data in ((mdb, b"mdb"), (study, b"study" * 300)):
                with open(path, "wb") as handle:
                    handle.write(data)
            app = BusyApp(network)
            result = ensure_feeder_study_com(
                {
                    "database_mdb": mdb,
                    "projects_dir": work,
                    "feeder_id": "AL209",
                    "network_id": network,
                    "study_open_attempts": 3,
                    "study_open_poll_seconds": 0.001,
                },
                selected_study=study,
                app=app,
                access_version=2000,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["reused"])
        self.assertFalse(result["created"])
        self.assertEqual(app.attempts, 3)
        self.assertEqual(app.new_calls, 0)
        self.assertEqual(app.new_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
