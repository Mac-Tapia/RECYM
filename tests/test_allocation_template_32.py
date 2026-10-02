# -*- coding: utf-8 -*-
"""§3.2 deja el diálogo de distribución como la plantilla acordada (sin CYMDIST)."""
from __future__ import print_function

import os
import sys
import types
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


class _Enum(object):
    def __init__(self, name):
        self.name = name


class _CympyObj(object):
    def __init__(self):
        self.values = {}
        self.demands = {}

    def SetValue(self, value, key):
        self.values[key] = value

    def GetValue(self, key):
        return self.values.get(key)

    def SetDemand(self, net, meter):
        self.demands[net] = meter


class _LoadAllocationProps(object):
    shared = None

    def __init__(self):
        self._cympyObject = _LoadAllocationProps.shared

    def __setattr__(self, key, value):
        if key == "_cympyObject":
            object.__setattr__(self, key, value)
            return
        stored = value.name if isinstance(value, _Enum) else value
        self._cympyObject.SetValue(stored, key)


class _Meter(object):
    pass


def _fake_cympy():
    selected = []
    study = types.SimpleNamespace(
        SelectLoadModel=selected.append,
        Meter=_Meter,
        LoadValue=lambda p, q: (p, q),
    )
    enums = types.SimpleNamespace(LoadValueType=types.SimpleNamespace(KW_KVAR="KW_KVAR"))
    return types.SimpleNamespace(study=study, enums=enums), selected


class TestAllocationTemplate32(unittest.TestCase):
    def test_template_matches_dialog_capture(self):
        from pipeline.run_demand_allocation import apply_allocation_template_32

        _LoadAllocationProps.shared = _CympyObj()
        props_mod = types.ModuleType("cympy.properties.properties")
        props_mod.LoadAllocation = _LoadAllocationProps
        enums_mod = types.ModuleType("cympy.properties.CymeEnums")
        enums_mod._CymdistDataEnum_DemandTypeEnum = types.SimpleNamespace(
            FeederDemand=_Enum("FeederDemand"))
        enums_mod._CymdistDataEnum_LoadAllocationMethodEnum = types.SimpleNamespace(
            KWHMethod=_Enum("KWHMethod"))
        pkg = types.ModuleType("cympy.properties")
        pkg.properties = props_mod
        modules = {
            "cympy": types.ModuleType("cympy"),
            "cympy.properties": pkg,
            "cympy.properties.properties": props_mod,
            "cympy.properties.CymeEnums": enums_mod,
        }
        cympy, selected = _fake_cympy()
        with mock.patch.dict(sys.modules, modules):
            out = apply_allocation_template_32(cympy, "NET_2030_155_SI213")

        obj = _LoadAllocationProps.shared
        self.assertTrue(out["ok"], out)
        self.assertEqual(selected, ["DEFAULT"])
        self.assertEqual(obj.values["Method"], "KWHMethod")
        self.assertEqual(obj.values["LoadFlowParamConfigID"], "DEFAULT")
        self.assertEqual(obj.values["DemandType"], "FeederDemand")
        meter = obj.demands["NET_2030_155_SI213"]
        self.assertFalse(meter.Connected)
        self.assertFalse(meter.IsTotalDemand)
        self.assertEqual(meter.LoadValueType, "KW_KVAR")
        for phase in (meter.DemandA, meter.DemandB, meter.DemandC):
            self.assertEqual(phase, (0.0, 0.0))

    def test_missing_network_is_rejected(self):
        from pipeline.run_demand_allocation import apply_allocation_template_32

        with self.assertRaises(RuntimeError):
            apply_allocation_template_32(object(), "")


if __name__ == "__main__":
    unittest.main()
