# -*- coding: utf-8 -*-
"""
Corrige avisos tipicos de Flujo de carga en PA217 / Electro Dunas 22.9 kV:

- 480010: tension nominal de condensador (equipo DEFAULT ShuntCapacitor en 7.2 kV
  tipico de 12.47 kV). El estudio .zxst sobrescribe la BD al abrirse; hay que
  escribir RatedVoltageKVLN en MDB (CYMEQSHUNTCAPACITOR) Y guardar el estudio
  con SaveStudyEquipmentOption.AllEquipments.
- 260035: sustitucion de modelo por sensibilidad de tension cuando V < umbral.
  Mode=FromLibrary ignora V (~80% biblioteca). Se fuerza Mode=Global y V=0.01
  (1%) para no reemplazar masivamente a Z constante bajo demanda alta.
- Fuente: OperatingVoltage A/B/C en kV LN (= Vll/sqrt(3)), coherente con Base 22.9 LL.
"""
from __future__ import print_function
import math
import os
from core.common import require_cympy, load_json
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings
import cympy.eq as eq


def _vln(settings):
    vll = float(settings.get("voltage_ll_kv") or 22.9)
    return vll, vll / math.sqrt(3.0)


def fix_source_operating_voltage(adapter, network_id, vln):
    c = adapter.cympy
    notes = []
    devices = list(c.study.ListDevices(c.enums.DeviceType.Source, str(network_id)))
    for d in devices:
        for ph in ("A", "B", "C"):
            fld = "OperatingVoltage" + ph
            try:
                before = d.GetValue(fld)
                d.SetValue(float(vln), fld)
                after = d.GetValue(fld)
                notes.append("%s %s: %s -> %s" % (d.DeviceNumber, fld, before, after))
            except Exception as ex:
                notes.append("%s %s FAIL: %s" % (d.DeviceNumber, fld, ex))
    return notes


def _persist_default_shunt_mdb(settings, vln, rated_kvar=100.0):
    """
    UPSERT DEFAULT en CYMEQSHUNTCAPACITOR via PowerShell+ACE (comtypes ADO es inestable).
    La columna se llama RatedVoltageKVLL pero CymPy la expone como RatedVoltageKVLN
    (7.2 LN tipico US = 12.47/sqrt(3)); para 22.9 LL usamos LN = 22.9/sqrt(3).
    """
    notes = []
    mdb = settings.get("database_mdb") or ""
    if not mdb or not os.path.isfile(mdb):
        return ["MDB shunt: sin database_mdb"]

    try:
        import subprocess
        # No matar Cyme si la sesion pide mantenerlo abierto (§§4–5)
        keep = False
        try:
            keep = bool(settings.get("cymdist_keep_open"))
            if not keep:
                from pipeline.run_demand_allocation import load_session
                keep = bool(load_session(settings).get("cymdist_keep_open"))
        except Exception:
            keep = False
        if not keep:
            subprocess.call(
                ["taskkill", "/F", "/IM", "Cyme.exe"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
    except Exception:
        pass

    v = float(vln)
    kvar = float(rated_kvar)
    comment = "RECYM fix 480010 RatedVoltageKVLN=%.5f" % v
    # PowerShell here-string; escape single quotes for SQL
    sql_comment = comment.replace("'", "''")
    ps = r"""
$ErrorActionPreference = 'Stop'
$mdb = '%s'
$v = %s
$kvar = %s
$comment = '%s'
$cs = "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$mdb;Persist Security Info=False;"
$conn = New-Object -ComObject ADODB.Connection
try { $conn.Open($cs) } catch {
  $cs = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$mdb;Persist Security Info=False;"
  $conn.Open($cs)
}
$rs = $conn.Execute("SELECT COUNT(*) FROM CYMEQSHUNTCAPACITOR WHERE EquipmentId='DEFAULT'")
$n = [int]$rs.Fields.Item(0).Value
$rs.Close()
if ($n -gt 0) {
  $conn.Execute("UPDATE CYMEQSHUNTCAPACITOR SET RatedVoltageKVLL=$v, RatedKVAR=$kvar, ModifiedByUser=1, Comments='$comment' WHERE EquipmentId='DEFAULT'") | Out-Null
  Write-Output "UPDATE $v"
} else {
  $conn.Execute("INSERT INTO CYMEQSHUNTCAPACITOR (EquipmentId, ComponentMask, RatedKVAR, RatedVoltageKVLL, CostForFixedBank, CostForSwitchedBank, LossesKW, InterruptingRating, PhaseType, Favorite, ModifiedByUser, Flags, Comments) VALUES ('DEFAULT', 0, $kvar, $v, 0, 0, 0, 0, 0, 0, 1, 0, '$comment')") | Out-Null
  Write-Output "INSERT $v"
}
$conn.Close()
""" % (mdb.replace("'", "''"), v, kvar, sql_comment)

    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        notes.append("MDB CYMEQSHUNTCAPACITOR DEFAULT: %s" % out.strip())
    except Exception as ex:
        notes.append("MDB shunt FAIL: %s" % ex)
    return notes


def fix_voltage_sensitivity_threshold(cympy, percent=0.01):
    """
    260035: con Mode=FromLibrary CYME ignora V y usa ~80% de biblioteca.
    Mode=Global aplica el umbral V indicado (0.01 = 1%).
    """
    notes = []
    sim = cympy.sim.LoadFlow()
    base = "ParametersConfigurations[0].LoadFlowVoltageSensitivityLoadModel"
    try:
        before_mode = sim.GetValue(base + ".Mode")
        sim.SetValue("Global", base + ".Mode")
        after_mode = sim.GetValue(base + ".Mode")
        notes.append("LoadFlowVoltageSensitivityLoadModel.Mode: %s -> %s" % (
            before_mode, after_mode))
    except Exception as ex:
        notes.append("Sensitivity Mode FAIL: %s" % ex)
    try:
        before = sim.GetValue(base + ".V")
        sim.SetValue(float(percent), base + ".V")
        after = sim.GetValue(base + ".V")
        notes.append("LoadFlowVoltageSensitivityLoadModel.V: %s -> %s" % (before, after))
    except Exception as ex:
        notes.append("Sensitivity V FAIL: %s" % ex)
    try:
        before_u = sim.GetValue(base + ".UseDefaultValuesByLoad")
        sim.SetValue(False, base + ".UseDefaultValuesByLoad")
        notes.append("UseDefaultValuesByLoad: %s -> %s" % (
            before_u, sim.GetValue(base + ".UseDefaultValuesByLoad")))
    except Exception as ex:
        notes.append("UseDefaultValuesByLoad FAIL: %s" % ex)
    return notes


def run(settings=None):
    s = settings or load_settings()
    vll, vln = _vln(s)
    result = {
        "feeder_id": s.get("feeder_id"),
        "network_id": s.get("network_id"),
        "Vll_kV": vll,
        "Vln_kV": vln,
        "notes": [],
        "ok": True,
    }

    # 1) Escribir MDB primero (Cyme cerrado)
    result["notes"].extend(_persist_default_shunt_mdb(s, vln))

    c = require_cympy(s)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s)
    a.open_study()

    result["notes"].extend(fix_source_operating_voltage(a, s.get("network_id"), vln))
    # Sesion + Save(AllEquipments); MDB ya escrito arriba (evitar doble taskkill largo)
    et = c.enums.EquipmentType.ShuntCapacitor
    try:
        before = eq.GetValue("RatedVoltageKVLN", "DEFAULT", et)
        eq.SetValue(float(vln), "RatedVoltageKVLN", "DEFAULT", et)
        after = eq.GetValue("RatedVoltageKVLN", "DEFAULT", et)
        result["notes"].append(
            "DEFAULT ShuntCapacitor RatedVoltageKVLN: %s -> %s" % (before, after)
        )
    except Exception as ex:
        result["notes"].append("DEFAULT ShuntCapacitor FAIL: %s" % ex)
        result["ok"] = False

    result["notes"].extend(fix_voltage_sensitivity_threshold(c, 0.01))

    if s.get("save_after_fix", True):
        try:
            from cympy.enums import SaveStudyEquipmentOption
            import cympy.db as db
            path = s.get("study_path") or ""
            c.study.Save(path, True, True, SaveStudyEquipmentOption.AllEquipments)
            db.Update()
            db.SaveProject()
            result["saved_study"] = True
            result["notes"].append("study.Save(AllEquipments)+db OK")
        except Exception as ex:
            result["saved_study"] = False
            result["notes"].append("save_study: %s" % ex)
            result["ok"] = False

    try:
        c.study.Close()
    except Exception:
        pass
    try:
        import cympy.db as db
        db.DisconnectDatabase()
    except Exception:
        pass

    for n in result["notes"]:
        print(n)
    return result


def main():
    r = run()
    print(r)
    if not r.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
