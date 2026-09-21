# -*- coding: utf-8 -*-
"""Aplicar parametros LoadFlow como en sample oficial CYME + FromLibrary."""
from __future__ import print_function

def apply_official_lf_params(cympy, network_id=None):
    lf = cympy.sim.LoadFlow()
    base = "ParametersConfigurations[0]"
    sets = [
        ("VoltageDropUnbalanced", base + ".AnalysisMode"),
        (100, base + ".MaximumIterations"),
        (0.1, base + ".VoltageTolerance"),
        (0.01, base + ".PowerTolerance"),
        (True, base + ".Flatstart"),
        (False, base + ".PerformLoadDiversification"),
        (False, base + ".IncludeDCSystems"),
        (False, base + ".DisplayStatus"),
        ("FromLibrary", base + ".LoadFlowVoltageSensitivityLoadModel.Mode"),
        ("None", base + ".LoadFlowLoadScalingFactors.Mode"),
        ("None", base + ".LoadFlowGenerationScalingFactors.Mode"),
        ("None", base + ".LoadFlowMotorScalingFactors.Mode"),
        (False, base + ".FlowAnalysisOutput.DisplayIterationReport"),
        (False, base + ".FlowAnalysisOutput.DisplayIterationReportNonConvergence"),
        (False, base + ".FlowAnalysisOutput.EnableReport"),
        (False, base + ".FlowAnalysisOutput.EnableColorCoding"),
        (False, base + ".FlowAnalysisOutput.EnableResultTags"),
        (False, base + ".FlowAnalysisOutput.EnableTooltips"),
        (1, base + ".RatingType"),
        (1, base + ".EquipmentRatings"),
        (1, base + ".ProtectiveDeviceRatings"),
    ]
    notes = []
    for val, path in sets:
        try:
            lf.SetValue(val, path)
            notes.append("OK %s=%s" % (path, val))
        except Exception as ex:
            notes.append("FAIL %s: %s" % (path, ex))
            # try alternate Mode values
            if path.endswith(".Mode"):
                for alt in ("FromLibrary", "None", "NoScaling", "Disabled", "Off", "DoNotScale", "Constant"):
                    try:
                        lf.SetValue(alt, path)
                        notes.append("OK alt %s=%s" % (path, alt))
                        break
                    except Exception:
                        pass
    # networks
    if network_id:
        try:
            lf.Execute("AnalysisNetworks.SelectedNetworks.Clear()")
        except Exception:
            pass
        try:
            lf.Execute("AnalysisNetworks.SelectedNetworks.Add('%s')" % network_id)
            notes.append("SelectedNetworks=" + str(network_id))
        except Exception as ex:
            notes.append("SelectedNetworks FAIL: " + str(ex))
    return lf, notes

def main():
    from core.feeder_context import load_settings
    from core.common import require_cympy, load_json
    from core.cympy_adapter import CymPyAdapter
    import cympy

    s = load_settings(feeder_id="PA217")
    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()
    net = str(s.get("network_id"))

    try:
        c.app.ActivateRefresh(False)
    except Exception:
        pass

    # Inspect current Mode values
    lf0 = c.sim.LoadFlow()
    for path in (
        "ParametersConfigurations[0].LoadFlowVoltageSensitivityLoadModel.Mode",
        "ParametersConfigurations[0].LoadFlowLoadScalingFactors.Mode",
        "ParametersConfigurations[0].LoadFlowGenerationScalingFactors.Mode",
        "ParametersConfigurations[0].LoadFlowMotorScalingFactors.Mode",
        "ParametersConfigurations[0].AnalysisMode",
        "ParametersConfigurations[0].CFCalculationMethod",
        "ActiveConfigurationID",
    ):
        try:
            print("GET", path, "=", lf0.GetValue(path))
        except Exception as ex:
            print("GET", path, "ERR", ex)

    # Enum choices for Mode
    from cympy.properties.CymeEnums import _CymdistDataEnum_LoadFlowFactorTypeEnum as FT
    print("FactorType enums:", [x.name for x in FT])

    lf, notes = apply_official_lf_params(c, net)
    for n in notes:
        print(n)

    try:
        lf.Run([net])
        print("LF SUCCESS official params")
        a.save_study()
        return
    except Exception as ex:
        print("LF FAIL official", ex)

    # Retry Mode sweep for VoltageSensitivity
    for mode in [x.name for x in FT]:
        try:
            lf.SetValue(mode, "ParametersConfigurations[0].LoadFlowVoltageSensitivityLoadModel.Mode")
            lf.Run([net])
            print("LF SUCCESS sens mode", mode)
            a.save_study()
            return
        except Exception as ex:
            print("sens", mode, str(ex)[:80])

    print("NO SUCCESS")

if __name__ == "__main__":
    main()
