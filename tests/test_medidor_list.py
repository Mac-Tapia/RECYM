# -*- coding: utf-8 -*-
"""El selector de §1 lista todos los medidores de medidoralimentador.xlsx."""
from __future__ import print_function

import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from core import cabecera_medicion_excel as cme


class TestListAllMedidores(unittest.TestCase):
    def setUp(self):
        from openpyxl import Workbook

        self.tmp = tempfile.mkdtemp(prefix="recym_medmap_")
        wb = Workbook()
        ws = wb.active
        ws.append(["codigo alimentador", "Medidor", "Nivel Tension", "siglas"])
        ws.append(["LT", "L-6605", 60, None])
        ws.append(["LT", "L-6606", 60, None])
        ws.append(["Barra", "B-PA6T1", 60, "PA"])
        ws.append(["PA217", "L-PA235", "22.9", "PA"])
        ws.append([None, "B-PA2T2", None, None])
        ws.append(["LT", "L6619 ", 60, None])
        ws.append(["LT", "L6619", 60, None])
        wb.save(os.path.join(self.tmp, "medidoralimentador.xlsx"))
        self.settings = {"medidoralimentador_dir": self.tmp}
        cme._MAP_CACHE.update({"path": None, "mtime": None, "by_feeder": {}})

    def tearDown(self):
        cme._MAP_CACHE.update({"path": None, "mtime": None, "by_feeder": {}})

    def test_every_meter_row_is_listed_once(self):
        items = cme.list_all_medidores(self.settings)
        ids = [i["feeder_id"] for i in items]
        self.assertEqual(ids, ["L-6605", "L-6606", "B-PA6T1", "PA217", "B-PA2T2", "L6619"])
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(items[3]["feeder_raw"], "PA217")
        self.assertEqual(items[0]["feeder_raw"], "LT · L-6605")

    def test_lookup_resolves_non_feeder_rows_by_meter(self):
        hit = cme.lookup_feeder_medidor("L-6606", settings=self.settings)
        self.assertEqual(hit["medidor"], "L-6606")
        self.assertEqual(hit["Vll_kV"], 60.0)
        feeder = cme.lookup_feeder_medidor("PA217", settings=self.settings)
        self.assertEqual(feeder["medidor"], "L-PA235")


if __name__ == "__main__":
    unittest.main()
