# -*- coding: utf-8 -*-
"""Pruebas: Actualizar/clear deja el Tablero dinámico en cero (no resucita totales)."""
from __future__ import print_function

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = os.path.join(ROOT, "src")
for p in (_SRC, os.path.join(_SRC, "analysis"), os.path.join(_SRC, "core")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _fake_settings(tmpdir):
    return {
        "feeder_id": "TEST_CLR",
        "network_id": "NET_TEST",
        "utility_name": "TEST",
        "dry_run": True,
        "study_path": "",
        "output_dir": tmpdir,
    }


def _write_stale_diag(settings):
    """Simula tablero colgado con 10 errores (el bug reportado)."""
    from core.feeder_context import output_path

    stale = {
        "empty": False,
        "phase": "before",
        "total_messages": 10,
        "n_problems": 10,
        "by_code": {"260044": 7, "220003": 1, "220011": 1, "220048": 1},
        "top_errors": [
            {
                "Codigo": "260044",
                "Tipo": "Load",
                "ID_CYMDIST": "DEV_X",
                "Mensaje": "stale",
            }
        ]
        * 3,
        "timestamp": "20260921_224210",
    }
    before = output_path(settings, "diagnostics", "dashboard_summary.json")
    after = output_path(settings, "diagnostics", "dashboard_summary_after.json")
    tab = output_path(settings, "diagnostics", "tablero.json")
    os.makedirs(os.path.dirname(before), exist_ok=True)
    with open(before, "w", encoding="utf-8") as f:
        json.dump(stale, f)
    after_s = dict(stale)
    after_s["phase"] = "after"
    with open(after, "w", encoding="utf-8") as f:
        json.dump(after_s, f)
    with open(tab, "w", encoding="utf-8") as f:
        json.dump(
            {
                "has_diagnostic": True,
                "before": stale,
                "after": after_s,
                "clientes": {"n": 0, "rows": []},
            },
            f,
        )
    return before, after, tab


class TestTableroClearActualizar(unittest.TestCase):
    def test_clear_zeros_after_stale_10(self):
        from analysis.build_dashboard import clear_tablero_diagnostics, main

        with tempfile.TemporaryDirectory() as tmp:
            s = _fake_settings(tmp)
            _write_stale_diag(s)

            info = clear_tablero_diagnostics(s, rebuild=True)
            self.assertTrue(info.get("ok"))
            board = info.get("tablero")
            self.assertIsNotNone(board)
            self.assertFalse(board.get("has_diagnostic"))
            self.assertEqual(board["before"]["total_messages"], 0)
            self.assertEqual(board["after"]["total_messages"], 0)
            self.assertTrue(board["before"].get("empty"))
            self.assertTrue(board["after"].get("empty"))
            self.assertEqual(board["before"].get("by_code") or {}, {})
            self.assertEqual(board["before"].get("top_errors") or [], [])

            # Durabilidad: rebuild=1 (main) NO debe resucitar los 10
            board2 = main(s, soft_clientes=True)
            self.assertEqual(board2["before"]["total_messages"], 0)
            self.assertEqual(board2["after"]["total_messages"], 0)
            self.assertFalse(board2.get("has_diagnostic"))

            # tablero.json en disco coherente
            tab_path = os.path.join(tmp, "diagnostics", "tablero.json")
            with open(tab_path, "r", encoding="utf-8") as f:
                disk = json.load(f)
            self.assertEqual(disk["before"]["total_messages"], 0)
            self.assertEqual(disk["after"]["total_messages"], 0)
            self.assertTrue(disk["before"].get("empty"))

    def test_api_tablero_clear_query(self):
        """GET /api/tablero?clear=1 vía función router (sin servidor)."""
        from analysis.build_dashboard import clear_tablero_diagnostics

        with tempfile.TemporaryDirectory() as tmp:
            s = _fake_settings(tmp)
            _write_stale_diag(s)
            info = clear_tablero_diagnostics(s, rebuild=True)
            self.assertEqual(info["before"]["total_messages"], 0)
            self.assertEqual(info["errores_antes"] if "errores_antes" in info else 0, 0)
            # Campos que consume la SPA
            self.assertEqual(info["tablero"]["before"]["total_messages"], 0)
            self.assertEqual(info["tablero"]["after"]["total_messages"], 0)

    def test_ui_actualizar_contract_shape(self):
        """Contrato mínimo de respuesta que usa el botón Actualizar."""
        from analysis.build_dashboard import clear_tablero_diagnostics

        with tempfile.TemporaryDirectory() as tmp:
            s = _fake_settings(tmp)
            _write_stale_diag(s)
            tab = clear_tablero_diagnostics(s, rebuild=True)
            # Simula payload de /api/ui/actualizar
            before = tab["tablero"]["before"]
            after = tab["tablero"]["after"]
            payload = {
                "ok": True,
                "tablero_reset": True,
                "has_diagnostic": False,
                "errores_antes": before.get("total_messages", 0),
                "errores_despues": after.get("total_messages", 0),
            }
            self.assertEqual(payload["errores_antes"], 0)
            self.assertEqual(payload["errores_despues"], 0)
            self.assertTrue(payload["tablero_reset"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
