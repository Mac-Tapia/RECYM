# -*- coding: utf-8 -*-
"""Diagnostico y prueba de reparacion 130013 (parametros de simulacion)."""
from __future__ import print_function
from core.feeder_context import load_settings
from core.common import require_cympy, load_json
from core.cympy_adapter import CymPyAdapter

def main():
    s = load_settings(feeder_id="PA217")
    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()
    net = str(s.get("network_id"))

    from cympy.properties import properties as props
    from cympy.properties.CymeEnums import (
        _CymdistDataEnum_LFCalculationMethodEnum as LFMode,
        _CymdistDataEnum_DemandTypeEnum as DT,
        _CymdistDataEnum_LoadAllocationMethodEnum as ME,
    )

    lf = props.LoadFlow()
    an = lf.AnalysisNetworks
    print("SelectedNetworks before:", an.SelectedNetworks.GetCount(), list(an.SelectedNetworks.GetValues()))
    try:
        an.SelectedNetworks.Clear()
    except Exception as ex:
        print("Clear:", ex)
    try:
        # _STR_LIST.Add inserts raw; quote network id
        lf._cympyObject.Execute("AnalysisNetworks.SelectedNetworks.Add('%s')" % net)
        print("SelectedNetworks after:", list(an.SelectedNetworks.GetValues()))
    except Exception as ex:
        print("Add fail:", ex)
        try:
            an.SelectedNetworks.Add(net)
            print("Add plain:", list(an.SelectedNetworks.GetValues()))
        except Exception as ex2:
            print("Add plain fail:", ex2)

    cfg = list(lf.ParametersConfigurations.GetValues())[0]
    print("mode before:", cfg.AnalysisMode)

    ok_mode = None
    for m in (
        LFMode.VoltageDropUnbalanced,
        LFMode.VoltageDropBalanced,
        LFMode.NewtonRaphsonUnbalanced,
        LFMode.NewtonRaphson,
    ):
        try:
            cfg.AnalysisMode = m
            print("set", m.name, "->", cfg.AnalysisMode)
            c.sim.LoadFlow().Run([net])
            print("LF SUCCESS", m.name)
            ok_mode = m.name
            break
        except Exception as ex:
            print("LF FAIL", m.name, ex)

    if not ok_mode:
        try:
            c.sim.LoadFlow().Run()
            print("LF SUCCESS Run()")
            ok_mode = "Run()"
        except Exception as ex:
            print("LF FAIL Run()", ex)

    print("=== LA ===")
    try:
        lap = props.LoadAllocation()
        la = lap._cympyObject
        lap.Method = ME.KWHMethod
        lap.DemandType = DT.FeederDemand
        lap.LoadFlowParamConfigID = "DEFAULT"
        lap.RunVoltageDrop = False
        meter = c.study.Meter()
        meter.Connected = True
        meter.IsTotalDemand = True
        meter.LoadValueType = c.enums.LoadValueType.KW_KVAR
        meter.DemandTotal = c.study.LoadValue(9538.0, 2588.0)
        la.SetDemand(net, meter)
        la.Run([net])
        print("LA SUCCESS")
    except Exception as ex:
        print("LA FAIL", ex)

if __name__ == "__main__":
    main()
