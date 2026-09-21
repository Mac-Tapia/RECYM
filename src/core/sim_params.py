# -*- coding: utf-8 -*-
"""Preparacion de parametros de simulacion CYMDIST (evita / mitiga error 130013)."""
from __future__ import print_function

def ensure_loadflow_networks(cympy, network_id):
    """Asegura que AnalysisNetworks.SelectedNetworks incluya el alimentador."""
    from cympy.properties import properties as props
    lf = props.LoadFlow()
    an = lf.AnalysisNetworks
    net = str(network_id)
    try:
        current = list(an.SelectedNetworks.GetValues())
    except Exception:
        current = []
    if net not in current:
        try:
            lf._cympyObject.Execute("AnalysisNetworks.SelectedNetworks.Add('%s')" % net)
        except Exception:
            try:
                an.SelectedNetworks.Add(net)
            except Exception as ex:
                print("AVISO SelectedNetworks.Add:", ex)
    try:
        lf.ActiveConfigurationID = "DEFAULT"
    except Exception:
        pass
    return list(an.SelectedNetworks.GetValues()) if hasattr(an, "SelectedNetworks") else []

def try_repair_loadflow_defaults(cympy):
    """
    Ajustes tipicos cuando DEFAULT falla validacion (130013).
    Alinea capas de salida / Z fuente a valores de tutoriales CYME.
    """
    from cympy.properties import properties as props
    from cympy.properties.CymeEnums import (
        _CymdistDataEnum_LFCalculationMethodEnum as LFMode,
        _CymdistDataEnum_SourceImpedanceSelectionEnum as SrcZ,
    )
    lf = props.LoadFlow()
    notes = []
    try:
        cfg = list(lf.ParametersConfigurations.GetValues())[0]
    except Exception as ex:
        return {"ok": False, "error": str(ex), "notes": notes}
    for mode in (LFMode.VoltageDropUnbalanced, LFMode.VoltageDropBalanced):
        try:
            cfg.AnalysisMode = mode
            notes.append("AnalysisMode=" + mode.name)
            break
        except Exception as ex:
            notes.append("AnalysisMode fail: " + str(ex))
    for name, val in (
        ("IncludeSourceImpedance", False),
        ("Flatstart", True),
        ("PerformLoadDiversification", False),
        ("IncludeDCSystems", False),
        ("MaximumIterations", 20),
        ("PowerTolerance", 0.01),
        ("VoltageTolerance", 0.1),
        ("RatingType", 1),
        ("EquipmentRatings", 1),
        ("ProtectiveDeviceRatings", 0),
        ("UseGlobalVoltageLimits", True),
    ):
        try:
            setattr(cfg, name, val)
            notes.append("%s=%s" % (name, val))
        except Exception:
            pass
    try:
        cfg.SourceImpedanceSelection = SrcZ.AsDefined
        notes.append("SourceImpedanceSelection=AsDefined")
    except Exception:
        pass
    try:
        cfg.DCLoadFlowParametersConfigID = ""
        notes.append("DCLoadFlowParametersConfigID=clear")
    except Exception:
        pass
    # Capas de salida: evitar tipos IntegrationCapacity / EPRI no licenciados
    sim = cympy.sim.LoadFlow()
    for path, val in (
        ("ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType", "None"),
        ("ParametersConfigurations[0].FlowAnalysisOutput.TooltipLayer.TooltipType", "Default"),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding", False),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableTooltips", False),
        ("ParametersConfigurations[0].LoadFlowVoltageSensitivityLoadModel.Mode", "FromLibrary"),
    ):
        try:
            sim.SetValue(val, path)
            notes.append("SetValue %s=%s" % (path.split(".")[-1], val))
        except Exception:
            pass
    try:
        lf.ActiveConfigurationID = "DEFAULT"
    except Exception:
        pass
    return {"ok": True, "notes": notes, "ConfigID": getattr(cfg, "ConfigID", None)}

def run_loadflow_cympy(cympy, network_id):
    """Intenta LoadFlow via CymPy. Retorna (ok, error)."""
    net = str(network_id)
    ensure_loadflow_networks(cympy, net)
    try_repair_loadflow_defaults(cympy)
    try:
        cympy.sim.LoadFlow().Run([net])
        return True, None
    except Exception as ex1:
        try:
            cympy.sim.LoadFlow().Run()
            return True, None
        except Exception as ex2:
            return False, "%s | %s" % (ex1, ex2)

def run_loadflow_safe(cympy, network_id, settings=None):
    """
    CymPy primero; si 130013 / fallo de complemento, usa COM Cyme.exe.
    Retorna (ok, error, meta_dict).
    """
    ok, err = run_loadflow_cympy(cympy, network_id)
    if ok:
        return True, None, {"engine": "CymPy"}

    meta = {"engine": "CymPy", "cympy_error": err}
    # Cerrar estudio CymPy para liberar el .zxst antes del COM
    try:
        cympy.study.Save()
    except Exception:
        pass
    try:
        cympy.study.Close()
    except Exception:
        pass

    if settings is None:
        return False, err, meta

    from core.cymdist_com import run_loadflow_com
    print("AVISO CymPy LoadFlow fallo (%s). Reintentando via COM Cyme..." % (err or "")[:80])
    com = run_loadflow_com(settings, network_id)
    meta["engine"] = "COM"
    meta["com"] = com
    if com.get("ok"):
        return True, None, meta
    return False, "%s || COM: %s" % (err, com.get("error")), meta
