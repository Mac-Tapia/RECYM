# -*- coding: utf-8 -*-
"""Regresión del flujo de transferencia §1 → §5 (sin CYMDIST)."""
from __future__ import print_function

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ["RECYM_SPA"] = "1"
os.environ["RECYM_ENV"] = "development"
os.environ["RECYM_ISOLATE_JOBS"] = "1"

from pipeline import transfer_voltage_quality as tvq


class TestTransferNetworks(unittest.TestCase):
    def test_peer_network_is_resolved_when_spa_sends_only_primary(self):
        nets, unresolved = tvq.complete_transfer_network_ids(
            ["ELD_PA217"], ["PA217", "PA218"], resolve_network=lambda short: "ELD_" + short
        )
        self.assertEqual(nets, ["ELD_PA217", "ELD_PA218"])
        self.assertEqual(unresolved, [])

    def test_unresolvable_or_mismatched_peer_is_reported(self):
        nets, unresolved = tvq.complete_transfer_network_ids(
            ["ELD_PA217"], ["PA217", "PA218"], resolve_network=lambda short: "ELD_XX999"
        )
        self.assertEqual(nets, ["ELD_PA217"])
        self.assertEqual(unresolved, ["PA218"])

    def test_maneuver_is_recorded_from_settings(self):
        maneuver = tvq.transfer_maneuver_from_settings({
            "transfer_node_id": "N1",
            "transfer_sectionalizer_id": "SEC1",
            "transfer_tie_switch_id": "TIE1",
        })
        self.assertTrue(maneuver["complete"])
        self.assertEqual(maneuver["tie_switch_id"], "TIE1")
        self.assertFalse(tvq.transfer_maneuver_from_settings({})["complete"])


def _fake_lf(ok_by_net):
    def _run(adapter, net, settings):
        ok = ok_by_net.get(net, False)
        return {
            "ok": ok,
            "error": None if ok else "LF falló",
            "network_id": net,
            "Vmin_pu": 0.97 if ok else None,
            "Vmax_pu": 1.01 if ok else None,
        }
    return _run


class TestTransferEvaluation(unittest.TestCase):
    def _evaluate(self, ok_by_net, tmpdir_name):
        out_dir = tempfile.mkdtemp(prefix="recym_transfer_%s_" % tmpdir_name)
        settings = {
            "feeder_id": "PA217",
            "network_id": "ELD_PA217",
            "network_ids": ["ELD_PA217"],
            "transfer_pair": ["PA217", "PA218"],
            "transfer_node_id": "N1",
            "transfer_sectionalizer_id": "SEC1",
            "transfer_tie_switch_id": "TIE1",
        }
        with mock.patch.object(tvq, "_run_lf_one", side_effect=_fake_lf(ok_by_net)), \
                mock.patch.object(tvq, "_resolve_feeder_network", side_effect=lambda s: "ELD_" + s), \
                mock.patch.object(tvq, "output_path",
                                  side_effect=lambda s, *parts: os.path.join(out_dir, parts[-1])):
            return tvq.evaluate_transfer_voltage_quality(settings)

    def test_both_networks_evaluated_and_maneuver_returned(self):
        out = self._evaluate({"ELD_PA217": True, "ELD_PA218": True}, "ok")
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(out["destination_network_id"], "ELD_PA218")
        self.assertEqual(out["maneuver"]["sectionalizer_id"], "SEC1")

    def test_equipment_counts_are_voltage_evidence_without_vmin(self):
        def lf(adapter, net, settings):
            return {"ok": True, "network_id": net, "Vmin_pu": None, "Vmax_pu": None,
                    "low_voltage_count": 0, "high_voltage_count": 12 if net.endswith("PA217") else 0,
                    "voltage_flag_pct": 5.0}
        out_dir = tempfile.mkdtemp(prefix="recym_transfer_counts_")
        settings = {"feeder_id": "PA217", "network_ids": ["ELD_PA217", "ELD_PA218"],
                    "transfer_pair": ["PA217", "PA218"]}
        with mock.patch.object(tvq, "_run_lf_one", side_effect=lf), \
                mock.patch.object(tvq, "output_path",
                                  side_effect=lambda s, *parts: os.path.join(out_dir, parts[-1])):
            out = tvq.evaluate_transfer_voltage_quality(settings)
        self.assertTrue(out["ok"], out.get("error"))
        self.assertTrue(out["baseline_peak"]["source"]["has_voltage_quality_issue"])
        self.assertEqual(out["recommendation"]["action"], "transfer_load_to_destination")

    def test_lf_without_voltage_evidence_is_not_conclusive(self):
        def lf(adapter, net, settings):
            return {"ok": True, "network_id": net, "Vmin_pu": None, "Vmax_pu": None}
        out_dir = tempfile.mkdtemp(prefix="recym_transfer_noev_")
        settings = {"feeder_id": "PA217", "network_ids": ["ELD_PA217", "ELD_PA218"],
                    "transfer_pair": ["PA217", "PA218"]}
        with mock.patch.object(tvq, "_run_lf_one", side_effect=lf), \
                mock.patch.object(tvq, "output_path",
                                  side_effect=lambda s, *parts: os.path.join(out_dir, parts[-1])):
            out = tvq.evaluate_transfer_voltage_quality(settings)
        self.assertFalse(out["ok"])
        self.assertIn("sin evidencia de tensión", out["error"])

    def test_failed_destination_lf_is_not_reported_as_success(self):
        out = self._evaluate({"ELD_PA217": True, "ELD_PA218": False}, "fail")
        self.assertFalse(out["ok"])
        self.assertIn("receptor", out["error"])


class TestTransferPreparation(unittest.TestCase):
    def test_prepared_requires_both_networks_written(self):
        from api_app.routers.context import summarize_transfer_preparation

        result = {
            "ok": True,
            "extraction": {"networks": [
                {"network_id": "ELD_PA217", "ok": True},
                {"network_id": "ELD_PA218", "ok": False, "error": "sin medidor"},
            ]},
            "writes": [{"network_id": "ELD_PA217", "ok": True}],
        }
        summary = summarize_transfer_preparation(result, ["ELD_PA217", "ELD_PA218"])
        self.assertFalse(summary["prepared"])
        self.assertEqual(len(summary["networks"]), 2)
        self.assertIn("sin medidor", summary["missing"][0])

    def test_prepared_when_both_networks_written(self):
        from api_app.routers.context import summarize_transfer_preparation

        result = {
            "ok": True,
            "extraction": {"networks": [
                {"network_id": "A_1", "ok": True},
                {"network_id": "B_2", "ok": True},
            ]},
            "writes": [{"network_id": "A_1", "ok": True}, {"network_id": "B_2", "ok": True}],
        }
        self.assertTrue(summarize_transfer_preparation(result, ["A_1", "B_2"])["prepared"])

    def test_peer_uses_its_own_medicion_file(self):
        from pipeline import apply_max_demand_multi as amd

        seen = {}

        def fake_extract(short, medicion_file=None, settings=None, auto_find_file=True):
            seen[short] = medicion_file
            return {"P_kW": 1.0}

        with mock.patch("core.cabecera_medicion_excel.extract_cabecera_medicion", fake_extract):
            amd.extract_max_demanda_for_networks(
                {"feeder_id": "PA217"},
                network_ids=["ELD_PA217", "ELD_PA218"],
                medicion_files={"ELD_PA217": "pa217.xlsx"},
            )
        self.assertEqual(seen.get("PA217"), "pa217.xlsx")
        self.assertIsNone(seen.get("PA218"))

    def test_same_feeder_pair_is_rejected(self):
        from fastapi.testclient import TestClient
        from api_app.main import app
        from api_app.security import get_or_create_api_key

        client = TestClient(app)
        resp = client.post("/api/contexto/cargar-transferencia", headers={
            "X-Api-Key": get_or_create_api_key(),
        }, json={
            "database_mdb": "x.mdb",
            "study_path": "x.zxst",
            "feeder_id": "PA217",
            "network_id": "ELD_PA217",
            "allowed_networks": [],
            "peer_feeder_id": "pa217",
            "peer_network_id": "ELD_PA217",
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error_code"], "TRANSFER_PAIR_SAME_FEEDER")


class TestTransferPairLoadRouting(unittest.TestCase):
    def _files(self):
        d = tempfile.mkdtemp(prefix="recym_pair_")
        mdb, study = os.path.join(d, "b.mdb"), os.path.join(d, "e.zxst")
        for f in (mdb, study):
            open(f, "wb").close()
        return mdb, study

    def test_pair_load_uses_persistent_com_apartment(self):
        from core import cymdist_com as com

        mdb, study = self._files()
        with mock.patch.object(com, "_run_live_com", return_value={"ok": True}) as live:
            out = com.load_transfer_pair_com(
                {"database_mdb": mdb, "study_path": study, "network_id": "NET_A"},
                peer_network_id="NET_B",
            )
        self.assertTrue(out["ok"])
        self.assertEqual(live.call_args[0][0], "load_transfer_pair")
        self.assertEqual(live.call_args[0][1]["_peer_network_id"], "NET_B")

    def test_cymdist_failure_is_409_not_ok(self):
        from api_app.routers import context

        mdb, study = self._files()
        body = context.TransferLoadRequest(
            database_mdb=mdb, study_path=study, feeder_id="PA217", network_id="NET_A",
            allowed_networks=[], peer_feeder_id="PA218", peer_network_id="NET_B",
        )
        crashed = {"ok": False, "error_code": "CYMDIST_CRASHED", "error": "Cyme caído"}
        with mock.patch("core.feeder_context.load_settings", return_value={}),                 mock.patch("core.cymdist_com.load_transfer_pair_com", return_value=crashed):
            resp = context.context_load_transfer(body)
        self.assertEqual(resp.status_code, 409)
        self.assertIn(b"CYMDIST_CRASHED", resp.body)


class TestTransferScenarioJobs(unittest.TestCase):
    def test_transfer_scenario_sets_pair(self):
        from api_app.jobs import apply_transfer_scenario

        s = apply_transfer_scenario(
            {"feeder_id": "PA217"},
            {"scenario_id": "transfer_PA217_PA218", "transfer_peer": "pa218",
             "transfer_peer_network_id": "ELD_PA218"},
        )
        self.assertEqual(s["transfer_pair"], ["PA217", "PA218"])
        self.assertEqual(s["transfer_peer_network_id"], "ELD_PA218")

    def test_single_feeder_scenario_is_untouched(self):
        from api_app.jobs import apply_transfer_scenario

        s = apply_transfer_scenario(
            {"feeder_id": "PA217"},
            {"scenario_id": "single_PA217", "transfer_peer": "PA218"},
        )
        self.assertNotIn("transfer_pair", s)


class TestBridgeDoesNotBlockEventLoop(unittest.TestCase):
    def test_slow_flask_route_does_not_block_health(self):
        """Una ruta Flask lenta no debe congelar /api/health (event loop libre)."""
        import asyncio
        import httpx
        from api_app import main as main_mod

        release = threading.Event()

        def slow_app(environ, start_response):
            release.wait(5)
            start_response("200 OK", [("Content-Type", "application/json")])
            return [b'{"ok": true}']

        async def scenario():
            transport = httpx.ASGITransport(app=main_mod.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
                slow = asyncio.ensure_future(c.get("/api/_slow_probe"))
                await asyncio.sleep(0.2)
                t0 = time.time()
                health = await c.get("/api/health")
                elapsed = time.time() - t0
                release.set()
                await slow
                return health.status_code, elapsed

        with mock.patch.object(main_mod, "flask_app", slow_app):
            loop = asyncio.new_event_loop()
            try:
                status, elapsed = loop.run_until_complete(scenario())
            finally:
                loop.close()
        self.assertEqual(status, 200)
        self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
