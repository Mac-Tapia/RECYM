# -*- coding: utf-8 -*-
"""§3 usa por defecto la lectura más reciente (periodo MMAA en el nombre)."""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from core.clientes_suministro import file_period_key, sort_by_period_desc


class TestPeriodFiles(unittest.TestCase):
    def test_newest_clientes_importantes_first(self):
        files = ["0126clientesImportantes.xlsb", "1225clientesImportantes.xlsb",
                 "0726clientesImportantes.xlsx", "0526clientesImportantes.xlsx"]
        self.assertEqual(sort_by_period_desc(files)[0], "0726clientesImportantes.xlsx")
        self.assertEqual(sort_by_period_desc(files)[-1], "1225clientesImportantes.xlsb")

    def test_suministro_period(self):
        self.assertEqual(file_period_key("ML_1225.xlsx"), 202512)
        self.assertEqual(sort_by_period_desc(["ML_1225.xlsx", "ML_0326.xlsx"])[0], "ML_0326.xlsx")
        self.assertEqual(file_period_key("sin_periodo.xlsx"), -1)


if __name__ == "__main__":
    unittest.main()
