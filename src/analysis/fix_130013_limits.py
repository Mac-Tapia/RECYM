# -*- coding: utf-8 -*-
"""Reparar 130013: limites de tension / nueva config LoadFlow."""
from __future__ import print_function

def dump_nested(obj, label, depth=0):
    if depth > 2:
        return
    pad = "  " * depth
    for attr in dir(obj):
        if attr.startswith("_") or attr.endswith("Choices"):
            continue
        try:
            v = getattr(obj, attr)
        except Exception as e:
            print(pad + label + "." + attr, "ERR", str(e)[:80])
            continue
        if callable(v):
            continue
        sv = str(v)
        if "object at" in sv:
            print(pad + label + "." + attr, "(nested)")
            if hasattr(v, "GetCount"):
                try:
                    n = int(v.GetCount())
                    print(pad + "  count=", n)
                    if n and hasattr(v, "GetValues"):
                        for i, item in enumerate(list(v.GetValues())[:3]):
                            dump_nested(item, "%s[%d]" % (attr, i), depth + 1)
                except Exception as e:
                    print(pad + "  count ERR", e)
            else:
                dump_nested(v, attr, depth + 1)
        else:
            print(pad + label + "." + attr, "=", sv[:100])

def main():
    from core.feeder_context import load_settings
    from core.common import require_cympy, load_json
    from core.cympy_adapter import CymPyAdapter
    from cympy.properties import properties as props
    from cympy.properties.CymeEnums import (
        _CymdistDataEnum_LFCalculationMethodEnum as LFMode,
        _CymdistDataEnum_SourceImpedanceSelectionEnum as SrcZ,
        _CymdistDataEnum_LFTapOperationModeEnum as TapMode,
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

    print("=== GlobalVoltageLimits ===")
    dump_nested(cfg.LoadFlowGlobalVoltageLimits, "GVL")
    print("=== VoltageRangeVoltageLimits ===")
    dump_nested(cfg.LoadFlowVoltageRangeVoltageLimits, "VRVL")
    print("=== CustomerVoltageLimits ===")
    dump_nested(cfg.LoadFlowCustomerVoltageLimits, "CVL")
    print("=== ImpedanceTolerance ===")
    dump_nested(cfg.ImpedanceTolerance, "Ztol")
    print("=== EquipmentStatusParameters ===")
    dump_nested(cfg.EquipmentStatusParameters, "EqStat")

    # Try populate voltage limits
    print("=== try set voltage limits ===")
    gvl = cfg.LoadFlowGlobalVoltageLimits
    for name, val in (
        ("MinimumVoltage", 0.95),
        ("MaximumVoltage", 1.05),
        ("MinimumVoltagePU", 0.95),
        ("MaximumVoltagePU", 1.05),
        ("MinVoltage", 0.95),
        ("MaxVoltage", 1.05),
        ("LowLimit", 0.95),
        ("HighLimit", 1.05),
    ):
        if hasattr(gvl, name):
            try:
                setattr(gvl, name, val)
                print("set GVL", name, getattr(gvl, name))
            except Exception as e:
                print("GVL", name, e)

    # Add voltage range limit if list empty
    vr = cfg.LoadFlowVoltageRangeVoltageLimits
    try:
        print("VR count", vr.GetCount())
        if int(vr.GetCount()) == 0:
            for cmd in (
                "ParametersConfigurations[0].LoadFlowVoltageRangeVoltageLimits.Add()",
                "ParametersConfigurations[0].LoadFlowVoltageRangeVoltageLimits.Add(0, 100, 0.95, 1.05)",
                "ParametersConfigurations[0].LoadFlowVoltageRangeVoltageLimits.Add('0','100','0.95','1.05')",
            ):
                try:
                    lf._cympyObject.Execute(cmd)
                    print("OK", cmd, "count", vr.GetCount())
                    break
                except Exception as e:
                    print("FAIL", cmd, str(e)[:120])
    except Exception as e:
        print("VR ERR", e)

    # UseGlobalVoltageLimits True/False trials after setting
    for use_g in (True, False):
        try:
            cfg.UseGlobalVoltageLimits = use_g
            cfg.AnalysisMode = LFMode.VoltageDropUnbalanced
            cfg.RatingType = 1
            cfg.EquipmentRatings = 1
            cfg.ProtectiveDeviceRatings = 1
            cfg.IncludeSourceImpedance = True
            cfg.SourceImpedanceSelection = SrcZ.AsDefined
            cfg.Flatstart = True
            cfg.PerformLoadDiversification = False
            cfg.IncludeDCSystems = False
            cfg.MaximumIterations = 100
            lf.ActiveConfigurationID = "DEFAULT"
            c.sim.LoadFlow().Run([net])
            print("SUCCESS UseGlobalVoltageLimits", use_g)
            a.save_study()
            return
        except Exception as e:
            print("FAIL UseGlobal", use_g, e)

    # Try Add config with name
    print("=== Add named config ===")
    for cmd in (
        "ParametersConfigurations.Add(RECYM)",
        "ParametersConfigurations.Add('RECYM')",
        "ParametersConfigurations.Add(\"RECYM\")",
        "ParametersConfigurations.Add(RECYM, Custom)",
        "ParametersConfigurations.Add('RECYM', Custom)",
    ):
        try:
            lf._cympyObject.Execute(cmd)
            print("ADD OK", cmd, "count", lf.ParametersConfigurations.GetCount())
            break
        except Exception as e:
            print("ADD FAIL", cmd, str(e)[:140])

    if int(lf.ParametersConfigurations.GetCount()) > 1:
        newcfg = list(lf.ParametersConfigurations.GetValues())[-1]
        print("new cfg", newcfg.ConfigID, newcfg.ConfigType)
        try:
            newcfg.ConfigID = "RECYM"
        except Exception as e:
            print("ConfigID", e)
        try:
            newcfg.ConfigType = CT.Custom
        except Exception as e:
            print("ConfigType", e)
        newcfg.AnalysisMode = LFMode.VoltageDropUnbalanced
        newcfg.RatingType = 1
        newcfg.EquipmentRatings = 1
        newcfg.ProtectiveDeviceRatings = 1
        newcfg.UseGlobalVoltageLimits = True
        newcfg.MaximumIterations = 100
        newcfg.PowerTolerance = 0.01
        newcfg.VoltageTolerance = 0.1
        newcfg.Flatstart = True
        newcfg.PerformLoadDiversification = False
        newcfg.IncludeDCSystems = False
        try:
            newcfg.IncludeSourceImpedance = True
            newcfg.SourceImpedanceSelection = SrcZ.AsDefined
        except Exception:
            pass
        # copy/set global VL
        try:
            ng = newcfg.LoadFlowGlobalVoltageLimits
            for name in dir(ng):
                if "Voltage" in name or "Limit" in name:
                    if name.startswith("_") or name.endswith("Choices"):
                        continue
                    try:
                        print("NG attr", name, getattr(ng, name))
                    except Exception:
                        pass
        except Exception as e:
            print("NG", e)
        lf.ActiveConfigurationID = newcfg.ConfigID or "RECYM"
        try:
            c.sim.LoadFlow().Run([net])
            print("SUCCESS RECYM config")
            a.save_study()
            return
        except Exception as e:
            print("RECYM FAIL", e)

    print("STILL FAIL")

if __name__ == "__main__":
    main()
