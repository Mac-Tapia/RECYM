# -*- coding: utf-8 -*-
"""Segunda pasada 130013: VoltageRange + Add config + fuente."""
from __future__ import print_function

def main():
    from core.feeder_context import load_settings
    from core.common import require_cympy, load_json
    from core.cympy_adapter import CymPyAdapter
    from cympy.properties import properties as props
    from cympy.properties.CymeEnums import (
        _CymdistDataEnum_LFCalculationMethodEnum as LFMode,
        _CymdistDataEnum_SourceImpedanceSelectionEnum as SrcZ,
        _CymdistDataEnum_ParametersConfigTypeEnum as CT,
    )

    s = load_settings(feeder_id="PA217")
    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()
    net = str(s.get("network_id"))
    c.study.SelectLoadModel("DEFAULT")

    lf = props.LoadFlow()
    cfg = list(lf.ParametersConfigurations.GetValues())[0]
    path = "ParametersConfigurations[0]"

    # Ensure VoltageRange exists and has limits (percent)
    vr = cfg.LoadFlowVoltageRangeVoltageLimits
    if int(vr.GetCount()) == 0:
        lf._cympyObject.Execute(path + ".LoadFlowVoltageRangeVoltageLimits.Add()")
    item = list(vr.GetValues())[0]
    for i in range(1, 6):
        setattr(item, "LowVoltageLimit%d" % i, 95.0)
        setattr(item, "HighVoltageLimit%d" % i, 105.0)
    try:
        item.VoltageRangeUpperLimit = 1000.0
    except Exception as e:
        print("VoltageRangeUpperLimit", e)
    print("VR[0] low1", item.LowVoltageLimit1, "high1", item.HighVoltageLimit1, "upper", getattr(item, "VoltageRangeUpperLimit", None))

    # Global limits also percent
    g = cfg.LoadFlowGlobalVoltageLimits
    for i in range(1, 6):
        setattr(g, "LowVoltageLimit%d" % i, 95.0)
        setattr(g, "HighVoltageLimit%d" % i, 105.0)

    cfg.AnalysisMode = LFMode.VoltageDropUnbalanced
    cfg.RatingType = 1
    cfg.EquipmentRatings = 1
    cfg.ProtectiveDeviceRatings = 1
    cfg.UseGlobalVoltageLimits = True
    cfg.IncludeSourceImpedance = False  # try without source Z
    cfg.Flatstart = True
    cfg.PerformLoadDiversification = False
    cfg.IncludeDCSystems = False
    cfg.DCLoadFlowParametersConfigID = ""
    cfg.MaximumIterations = 100
    lf.ActiveConfigurationID = "DEFAULT"

    try:
        c.sim.LoadFlow().Run([net])
        print("SUCCESS after VR fill IncludeSourceImpedance=False")
        a.save_study()
        return
    except Exception as e:
        print("FAIL1", e)

    cfg.IncludeSourceImpedance = True
    for src in (SrcZ.AsDefined, SrcZ.FirstLevel, SrcZ.SecondLevel):
        try:
            cfg.SourceImpedanceSelection = src
            c.sim.LoadFlow().Run([net])
            print("SUCCESS src", src.name)
            a.save_study()
            return
        except Exception as e:
            print("FAIL src", src.name, e)

    # Try Add with Custom enum name only
    print("=== Add configs ===")
    for cmd in (
        "ParametersConfigurations.Add(Custom)",
        "ParametersConfigurations.Add(Default)",
        "ParametersConfigurations.Add()",
        "ParametersConfigurations.Add(Custom, RECYM)",
        "ParametersConfigurations.Add(Custom, 'RECYM')",
        "ParametersConfigurations.Add('Custom', 'RECYM')",
    ):
        try:
            before = int(lf.ParametersConfigurations.GetCount())
            lf._cympyObject.Execute(cmd)
            after = int(lf.ParametersConfigurations.GetCount())
            print("OK", cmd, before, "->", after)
            if after > before:
                break
        except Exception as e:
            print("FAIL", cmd, str(e)[:160])

    # Source / equivalent check
    print("=== sources ===")
    for dtype_name in ("Source", "EquivalentSource", "Bus", "Node"):
        dt = getattr(c.enums.DeviceType, dtype_name, None)
        if dt is None:
            continue
        try:
            devs = list(c.study.ListDevices(dt, net))
            print(dtype_name, len(devs))
            for d in devs[:3]:
                print(" ", getattr(d, "DeviceNumber", None), getattr(d, "GetType", lambda: None)())
        except Exception as e:
            print(dtype_name, e)

    # ListDevices without filter
    try:
        srcs = list(c.study.ListDevices(c.enums.DeviceType.Source, net))
        print("Source count", len(srcs))
        for d in srcs[:5]:
            lid = str(d.DeviceNumber)
            print("SRC", lid)
            for fld in ("OperatingVoltage", "BaseVoltage", "Voltage", "EquivalentImpedance", "R1", "X1"):
                try:
                    print(" ", fld, d.GetValue(fld))
                except Exception:
                    pass
    except Exception as e:
        print("Source list", e)

    # Try tutorial study quickly?
    print("DONE without LF success")

if __name__ == "__main__":
    main()
