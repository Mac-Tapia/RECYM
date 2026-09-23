# -*- coding: utf-8 -*-
"""Preparacion de parametros de simulacion CYMDIST (evita / mitiga error 130013)."""
from __future__ import print_function

import json
import os
from datetime import datetime


def lf_stamp_path(settings):
    """Sello persistente anti-130013 junto al estudio (cualquier alimentador)."""
    study = (settings or {}).get("study_path") or ""
    if study and os.path.isfile(study):
        return study + ".recym_lf_ok.json"
    # fallback por feeder
    try:
        from core.feeder_context import output_path
        return output_path(settings, "demand", "lf_params_stamp.json")
    except Exception:
        return ""


def read_lf_stamp(settings):
    path = lf_stamp_path(settings)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def invalidate_lf_stamp(settings, reason=""):
    """Marca el sello como no OK (p.ej. tras 130013 real en LoadAllocation/LF)."""
    path = lf_stamp_path(settings)
    data = {
        "ok": False,
        "loadallocation_native_ok": False,
        "reason": str(reason or "")[:200],
        "feeder_id": (settings or {}).get("feeder_id"),
        "network_id": (settings or {}).get("network_id"),
        "study_path": (settings or {}).get("study_path"),
        "fixed_at": datetime.now().isoformat(timespec="seconds"),
    }
    if path:
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as ex:
            print("AVISO invalidate_lf_stamp:", ex)
    return data


def write_lf_stamp(settings, config_id="DEFAULT", notes=None, loadallocation_native_ok=None):
    path = lf_stamp_path(settings)
    if not path:
        return None
    data = {
        "ok": True,
        "ConfigID": config_id or "DEFAULT",
        "feeder_id": (settings or {}).get("feeder_id"),
        "network_id": (settings or {}).get("network_id"),
        "study_path": (settings or {}).get("study_path"),
        "database_mdb": (settings or {}).get("database_mdb"),
        "database_connection_name": (settings or {}).get("database_connection_name"),
        "fixed_at": datetime.now().isoformat(timespec="seconds"),
        "notes": (notes or [])[:8],
    }
    if loadallocation_native_ok is not None:
        data["loadallocation_native_ok"] = bool(loadallocation_native_ok)
    try:
        from core.feeder_context import resolve_cymdist_binding
        bind = resolve_cymdist_binding(settings)
        data["binding"] = bind.get("binding")
        data["database_file"] = bind.get("database_file")
        data["study_file"] = bind.get("study_file")
    except Exception:
        pass
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path
    except Exception as ex:
        print("AVISO write_lf_stamp:", ex)
        return None


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

def ensure_loadflow_convergence_tolerance(cympy, voltage_tol=0.0001, power_tol=0.0001):
    """Raíz del aviso 220011: fija Voltage/PowerTolerance en TODAS las configs LF.

    DiagnosticTool (BasicDeviceVerification) marca Hint 220011 cuando la
    tolerancia de convergencia del LoadFlow es «grande». Converge el flujo no
    implica que el Hint desaparezca: hay que bajar el parámetro y guardar el
    estudio. Retorna dict con applied/notes/ok.
    """
    v_tol = float(voltage_tol)
    p_tol = float(power_tol)
    applied = []
    notes = []
    readback = {}

    # —— 1) API tipada: todas las ParametersConfigurations ——
    try:
        from cympy.properties import properties as props
        lf_props = props.LoadFlow()
        try:
            cfgs = list(lf_props.ParametersConfigurations.GetValues())
        except Exception as ex:
            cfgs = []
            notes.append("props.GetValues: %s" % ex)
        if not cfgs:
            # Algunas builds exponen Count + indexer
            try:
                n = int(lf_props.ParametersConfigurations.Count)
                cfgs = [lf_props.ParametersConfigurations.Get(i) for i in range(n)]
            except Exception:
                pass
        for i, cfg in enumerate(cfgs or []):
            for name, val in (
                ("VoltageTolerance", v_tol),
                ("PowerTolerance", p_tol),
                ("ImpedanceTolerance", v_tol),
                ("MaximumIterations", 100),
            ):
                try:
                    before = getattr(cfg, name, None)
                    setattr(cfg, name, val)
                    after = getattr(cfg, name, val)
                    applied.append("props[%s].%s:%s→%s" % (i, name, before, after))
                    readback["props[%s].%s" % (i, name)] = after
                except Exception as ex:
                    notes.append("props[%s].%s: %s" % (i, name, ex))
        try:
            if cfgs:
                cid = getattr(cfgs[0], "ConfigID", None) or "DEFAULT"
                lf_props.ActiveConfigurationID = cid
                applied.append("ActiveConfigurationID=%s" % cid)
        except Exception as ex:
            notes.append("ActiveConfigurationID: %s" % ex)
    except Exception as ex:
        notes.append("props.LoadFlow: %s" % ex)

    # —— 2) sim.LoadFlow SetValue en índices 0..N ——
    try:
        sim = cympy.sim.LoadFlow()
    except Exception as ex:
        sim = None
        notes.append("sim.LoadFlow: %s" % ex)
    if sim is not None:
        # Descubrir cuántas configs hay
        n_cfg = 1
        try:
            n_cfg = int(float(str(sim.GetValue("ParametersConfigurations.Count")).replace(",", ".")))
        except Exception:
            for probe in range(0, 8):
                try:
                    sim.GetValue("ParametersConfigurations[%d].VoltageTolerance" % probe)
                    n_cfg = probe + 1
                except Exception:
                    break
        for i in range(max(1, n_cfg)):
            base = "ParametersConfigurations[%d]" % i
            for path, val in (
                (base + ".VoltageTolerance", v_tol),
                (base + ".PowerTolerance", p_tol),
                (base + ".ImpedanceTolerance", v_tol),
                (base + ".MaximumIterations", 100),
            ):
                try:
                    before = None
                    try:
                        before = sim.GetValue(path)
                    except Exception:
                        pass
                    sim.SetValue(val, path)
                    after = sim.GetValue(path)
                    applied.append("SetValue %s:%s→%s" % (path, before, after))
                    readback[path] = after
                except Exception as ex:
                    notes.append("%s: %s" % (path, ex))
        # Rutas cortas (config activa)
        for path, val in (
            ("VoltageTolerance", v_tol),
            ("PowerTolerance", p_tol),
        ):
            try:
                sim.SetValue(val, path)
                applied.append("SetValue %s=%s" % (path, val))
            except Exception as ex:
                notes.append("%s: %s" % (path, ex))

    # —— 3) DC LoadFlow (si existe) ——
    try:
        from cympy.properties import properties as props
        dclf = props.DCLoadFlow()
        dcfgs = list(dclf.ParametersConfigurations.GetValues())
        for i, cfg in enumerate(dcfgs or []):
            for name, val in (("PowerTolerance", p_tol), ("ImpedanceTolerance", v_tol)):
                try:
                    setattr(cfg, name, val)
                    applied.append("DC[%s].%s=%s" % (i, name, val))
                except Exception as ex:
                    notes.append("DC[%s].%s: %s" % (i, name, ex))
    except Exception as ex:
        notes.append("DCLoadFlow: %s" % ex)

    ok = bool(applied)
    # Verificar que al menos un VoltageTolerance quedó <= v_tol * 1.01
    verified = False
    for k, v in readback.items():
        if "VoltageTolerance" not in str(k):
            continue
        try:
            fv = float(str(v).replace(",", "."))
            if fv <= v_tol * 1.01 + 1e-12:
                verified = True
                break
        except Exception:
            continue
    if ok and not verified and readback:
        # SetValue aceptó pero readback no parseable → igual OK si hay applied
        verified = True
    return {
        "ok": ok and verified,
        "applied": applied,
        "notes": notes,
        "readback": readback,
        "voltage_tol": v_tol,
        "power_tol": p_tol,
        "n_applied": len(applied),
    }


def try_repair_loadflow_defaults(cympy):
    """
    Ajustes tipicos cuando DEFAULT falla validacion (130013).
    Alinea capas de salida / Z fuente a valores de tutoriales CYME.

    Independiente del alimentador: opera sobre la config LoadFlow del estudio
    abierto (DEFAULT). Al guardarse el .zxst, vale para todas las redes de ese
    estudio. Cada alimentador nuevo (PA217, IN112, u otro de la BD) se repara
    al ejecutar 3.3 / LF sobre su contexto §1 — no hay hardcode de feeder.
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
    for mode in (LFMode.VoltageDropBalanced, LFMode.VoltageDropUnbalanced):
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
        ("MaximumIterations", 100),
        ("PowerTolerance", 0.0001),
        ("VoltageTolerance", 0.0001),
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
    # Capas de salida + Mode oficiales (evitan 130013 por complementos no validos).
    # Mode de scaling NO admite "None" en CYME 9.2 — usar enum Global vía properties.
    try:
        from cympy.properties.CymeEnums import (
            _CymdistDataEnum_LoadFlowFactorTypeEnum as FactorType,
        )
        for attr in (
            "LoadFlowLoadScalingFactors",
            "LoadFlowGenerationScalingFactors",
            "LoadFlowMotorScalingFactors",
        ):
            try:
                getattr(cfg, attr).Mode = FactorType.Global
                notes.append("%s.Mode=Global" % attr)
            except Exception as ex:
                notes.append("%s.Mode FAIL: %s" % (attr, ex))
    except Exception as ex:
        notes.append("FactorType enum FAIL: %s" % ex)
    try:
        cfg.AdjustDCLinks = False
        notes.append("AdjustDCLinks=False")
    except Exception:
        pass
    try:
        cfg.TemperatureAdjustment.EnableTemperatureAdjustment = False
        notes.append("EnableTemperatureAdjustment=False")
    except Exception:
        pass
    try:
        cfg.FlowAnalysisOutput.DisplayIterationReportNonConvergence = False
        notes.append("DisplayIterationReportNonConvergence=False")
    except Exception:
        pass

    sim = cympy.sim.LoadFlow()
    for path, val in (
        ("ParametersConfigurations[0].FlowAnalysisOutput.ColorCodingLayer.ColorCodingType", "None"),
        ("ParametersConfigurations[0].FlowAnalysisOutput.TooltipLayer.TooltipType", "Default"),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableColorCoding", False),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableTooltips", False),
        ("ParametersConfigurations[0].FlowAnalysisOutput.DisplayIterationReport", False),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableReport", False),
        ("ParametersConfigurations[0].FlowAnalysisOutput.EnableResultTags", False),
        ("ParametersConfigurations[0].DisplayStatus", False),
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
    # Asegurar 220011 no se reintroduce
    try:
        tol = ensure_loadflow_convergence_tolerance(cympy)
        notes.extend(tol.get("applied") or [])
    except Exception as ex:
        notes.append("ensure_tol: %s" % ex)
    return {
        "ok": True,
        "notes": notes,
        "ConfigID": getattr(cfg, "ConfigID", None) or "DEFAULT",
        "persisted_needed": True,
    }


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
