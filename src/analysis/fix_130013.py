# -*- coding: utf-8 -*-
"""Intentar reparar Error 130013 en LoadFlow PA217."""
from __future__ import print_function
import traceback

def main():
    from core.feeder_context import load_settings
    from core.common import require_cympy, load_json
    from core.cympy_adapter import CymPyAdapter

    s = load_settings(feeder_id="PA217")
    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()
    net = str(s.get("network_id"))

    from cympy.properties import properties as props
    from cympy.properties.CymeEnums import (
        _CymdistDataEnum_LFCalculationMethodEnum as LFMode,
        _CymdistDataEnum_SourceImpedanceSelectionEnum as SrcZ,
        _CymdistDataEnum_LFTapOperationModeEnum as TapMode,
    )
    import cympy.enums as enums
    import cympy.utils as utils

    # Simulation parameter name
    try:
        st = enums.SimulationType
        names = [x for x in dir(st) if not x.startswith("_")]
        print("SimulationType:", names)
        for n in names:
            try:
                print("  params", n, "=", utils.GetSimulationParametersName(getattr(st, n)))
            except Exception as ex:
                print("  params", n, "ERR", ex)
    except Exception as ex:
        print("SimType ERR", ex)

    lf = props.LoadFlow()
    cfg = list(lf.ParametersConfigurations.GetValues())[0]
    print("ConfigID", cfg.ConfigID, "ConfigType", cfg.ConfigType)
    print("RatingType", cfg.RatingType, "EquipmentRatings", cfg.EquipmentRatings)
    print("ProtectiveDeviceRatings", cfg.ProtectiveDeviceRatings)
    print("SourceImpedanceSelection", cfg.SourceImpedanceSelection)
    print("AnalysisMode", cfg.AnalysisMode)

    # Ensure network selected
    an = lf.AnalysisNetworks
    try:
        vals = list(an.SelectedNetworks.GetValues())
        print("SelectedNetworks", vals)
        if net not in vals:
            lf._cympyObject.Execute("AnalysisNetworks.SelectedNetworks.Add('%s')" % net)
            print("Added network")
    except Exception as ex:
        print("networks ERR", ex)

    # Try SelectLoadModel
    try:
        c.study.SelectLoadModel("DEFAULT")
        print("LoadModel DEFAULT OK", c.study.GetActiveLoadModel().Name)
    except Exception as ex:
        print("LoadModel ERR", ex)

    # Sweep RatingType / EquipmentRatings (0 often invalid)
    success = None
    for mode in (LFMode.VoltageDropUnbalanced, LFMode.VoltageDropBalanced):
        for rating in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 16, 18):
            for eqr in (1, 2, 3, 4, 5, 0):
                try:
                    cfg.AnalysisMode = mode
                    cfg.RatingType = rating
                    cfg.EquipmentRatings = eqr
                    cfg.ProtectiveDeviceRatings = eqr if eqr else 1
                    try:
                        cfg.SourceImpedanceSelection = SrcZ.AsDefined
                    except Exception:
                        pass
                    try:
                        cfg.IncludeSourceImpedance = True
                    except Exception:
                        pass
                    try:
                        cfg.RegulatorTapOperationMode = TapMode.Normal
                        cfg.TransformerTapOperationMode = TapMode.Normal
                    except Exception:
                        pass
                    cfg.MaximumIterations = 100
                    cfg.PowerTolerance = 0.01
                    cfg.VoltageTolerance = 0.1
                    cfg.Flatstart = True
                    cfg.PerformLoadDiversification = False
                    cfg.IncludeDCSystems = False
                    lf.ActiveConfigurationID = "DEFAULT"
                    c.sim.LoadFlow().Run([net])
                    success = (mode.name, rating, eqr)
                    print("SUCCESS", success)
                    break
                except Exception as ex:
                    msg = str(ex)
                    if "130013" not in msg:
                        print("OTHER ERR", mode.name, rating, eqr, msg[:120])
            if success:
                break
        if success:
            break

    if not success:
        print("Sweep failed; try Add new config RECYM")
        try:
            # Add new parameters configuration
            lf._cympyObject.Execute("ParametersConfigurations.Add()")
            print("Add count", lf.ParametersConfigurations.GetCount())
            cfgs = list(lf.ParametersConfigurations.GetValues())
            newcfg = cfgs[-1]
            print("new ConfigID before", newcfg.ConfigID)
            try:
                newcfg.ConfigID = "RECYM"
            except Exception as ex:
                print("set ConfigID", ex)
            try:
                from cympy.properties.CymeEnums import _CymdistDataEnum_ParametersConfigTypeEnum as CT
                newcfg.ConfigType = CT.Custom
            except Exception as ex:
                print("set ConfigType", ex)
            newcfg.AnalysisMode = LFMode.VoltageDropUnbalanced
            newcfg.RatingType = 1
            newcfg.EquipmentRatings = 1
            newcfg.ProtectiveDeviceRatings = 1
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
            lf.ActiveConfigurationID = newcfg.ConfigID or "RECYM"
            print("Active", lf.ActiveConfigurationID)
            c.sim.LoadFlow().Run([net])
            print("SUCCESS new config", lf.ActiveConfigurationID)
            success = ("RECYM", newcfg.ConfigID)
        except Exception as ex:
            print("NEW CONFIG FAIL", ex)
            traceback.print_exc()

    if success:
        a.save_study()
        print("SAVED study with working LF params", success)
        # Also test LoadAllocation quickly
        try:
            from cympy.properties.CymeEnums import (
                _CymdistDataEnum_DemandTypeEnum as DT,
                _CymdistDataEnum_LoadAllocationMethodEnum as ME,
            )
            lap = props.LoadAllocation()
            la = lap._cympyObject
            lap.Method = ME.KWHMethod
            lap.DemandType = DT.FeederDemand
            lap.LoadFlowParamConfigID = lf.ActiveConfigurationID
            lap.RunVoltageDrop = False
            meter = c.study.Meter()
            meter.Connected = True
            meter.IsTotalDemand = True
            meter.LoadValueType = c.enums.LoadValueType.KW_KVAR
            meter.DemandTotal = c.study.LoadValue(9538.0, 2588.0)
            la.SetDemand(net, meter)
            la.Run([net])
            print("LA SUCCESS with same params")
            a.save_study()
        except Exception as ex:
            print("LA still FAIL", ex)
    else:
        print("NO SUCCESS - dump nested objects")
        for attr in dir(cfg):
            if attr.startswith("_") or attr.endswith("Choices"):
                continue
            try:
                v = getattr(cfg, attr)
                if callable(v):
                    continue
                sv = str(v)
                if "object at" in sv:
                    # nested - try list members
                    print("NESTED", attr)
                    if hasattr(v, "GetCount"):
                        print("  count", v.GetCount())
                else:
                    print(attr, "=", sv[:120])
            except Exception as e:
                print(attr, "ERR", str(e)[:80])

if __name__ == "__main__":
    main()
