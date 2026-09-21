# -*- coding: utf-8 -*-
"""
Reemplaza equipos DEFAULT por AAAC (aérea) / XLPE (subterránea) de la misma sección.

Fuente de sección:
  - OverheadLine DEFAULT → PhaseConductorID del equipo DEFAULT (p.ej. AAAC1203 = 120 mm2)
    → ATVB1-22.9KV-120
  - Underground/Cable DEFAULT → XLPE de calibre equivalente (settings / SIZE_HINTS)
  - Sectionalizer DEFAULT → SEC22.9KV

NO modifica:
  - CYMSOURCE / OperatingVoltage / NominalKVLL / DesiredKVLL
  - tensiones de alimentador / UserDefinedBaseVoltage

Uso:
  python -u src/pipeline/fix_default_aaac_xlpe.py
  python -u src/pipeline/fix_default_aaac_xlpe.py --dry-run
"""
from __future__ import print_function

import argparse
import csv
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))

from core.common import load_json, mkdir, p, ts  # noqa: E402
from core.equipment_library import (  # noqa: E402
    SIZE_HINTS,
    pick_equipment,
    size_from_default_equipment,
    equipment_exists,
    inventory_library,
)


def _out_dir(settings):
    base = os.path.join("data", "output", "system", "diagnostics", "ELD")
    full = p(*base.replace("\\", "/").split("/"))
    mkdir(full)
    return full


def _ace_query(mdb, sql, fetch=True):
    """Ejecuta SQL vía PowerShell+ACE. Devuelve lista de dicts si fetch."""
    # Escribir SQL a archivo temporal para evitar problemas de comillas
    import tempfile
    import subprocess

    fd, sql_path = tempfile.mkstemp(suffix=".sql", text=True)
    os.close(fd)
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write(sql)
    ps = (
        "$ErrorActionPreference='Stop'; "
        "$mdb = '%s'; "
        "$sql = Get-Content -Raw -Encoding UTF8 '%s'; "
        "$conn = New-Object -ComObject ADODB.Connection; "
        "try { $conn.Open(\"Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$mdb;Persist Security Info=False;\") } "
        "catch { $conn.Open(\"Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$mdb;Persist Security Info=False;\") }; "
        "$r = $conn.Execute($sql); "
        "if ($r -is [System.Array]) { $rs = $r[0] } else { $rs = $r }; "
        "if ($null -eq $rs -or $rs.State -eq 0) { $conn.Close(); exit 0 }; "
        "$lines = @(); "
        "while (-not $rs.EOF) { "
        "  $vals = @(); "
        "  for ($i=0; $i -lt $rs.Fields.Count; $i++) { "
        "    $n = $rs.Fields.Item($i).Name; $v = [string]$rs.Fields.Item($i).Value; "
        "    $vals += ($n + '=' + $v) "
        "  }; "
        "  $lines += ($vals -join [char]9); "
        "  $rs.MoveNext() "
        "}; "
        "$rs.Close(); $conn.Close(); "
        "$lines -join \"`n\""
    ) % (mdb.replace("'", "''"), sql_path.replace("'", "''"))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError("ACE SQL fail: %s\n%s" % (proc.stderr, sql[:200]))
        if not fetch:
            return []
        rows = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            d = {}
            for part in line.split("\t"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    d[k] = v
            if d:
                rows.append(d)
        return rows
    finally:
        try:
            os.remove(sql_path)
        except Exception:
            pass


def _ace_exec(mdb, sql):
    """UPDATE/INSERT sin resultset."""
    import tempfile
    import subprocess

    fd, sql_path = tempfile.mkstemp(suffix=".sql", text=True)
    os.close(fd)
    with open(sql_path, "w", encoding="utf-8") as f:
        f.write(sql)
    ps = (
        "$ErrorActionPreference='Stop'; "
        "$mdb = '%s'; "
        "$sql = Get-Content -Raw -Encoding UTF8 '%s'; "
        "$conn = New-Object -ComObject ADODB.Connection; "
        "try { $conn.Open(\"Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$mdb;Persist Security Info=False;\") } "
        "catch { $conn.Open(\"Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$mdb;Persist Security Info=False;\") }; "
        "$conn.Execute($sql); $conn.Close(); Write-Host 'OK'"
    ) % (mdb.replace("'", "''"), sql_path.replace("'", "''"))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 or "OK" not in (proc.stdout or ""):
            raise RuntimeError("ACE EXEC fail: %s %s" % (proc.stderr, proc.stdout))
    finally:
        try:
            os.remove(sql_path)
        except Exception:
            pass


def resolve_targets(cympy, settings):
    """Resuelve IDs de reemplazo respetando sección AAAC/XLPE de DEFAULT."""
    defaults = settings.get("default_equipment") or {}
    inv = inventory_library(cympy, ["OverheadLine", "Cable", "Sectionalizer", "Conductor"])

    size_oh = size_from_default_equipment(cympy, "OverheadLine")
    oh_id, oh_how = pick_equipment(
        cympy,
        "OverheadLine",
        preferred_id=defaults.get("OverheadLine"),
        size_mm2=size_oh,
        inventory=inv,
    )

    size_cab = size_from_default_equipment(cympy, "Cable")
    cab_id, cab_how = pick_equipment(
        cympy,
        "Cable",
        preferred_id=defaults.get("Cable") or defaults.get("Underground"),
        size_mm2=size_cab if size_cab else 120,
        inventory=inv,
    )

    sec_id, sec_how = pick_equipment(
        cympy,
        "Sectionalizer",
        preferred_id=defaults.get("Sectionalizer"),
        size_mm2=None,
        inventory=inv,
    )

    return {
        "OverheadLine": {"id": oh_id, "how": oh_how, "size_mm2": size_oh},
        "Cable": {"id": cab_id, "how": cab_how, "size_mm2": size_cab},
        "Sectionalizer": {"id": sec_id, "how": sec_how, "size_mm2": None},
    }


def count_defaults(mdb):
    out = {}
    for label, sql in (
        ("OH_DEFAULT", "SELECT Count(*) AS N FROM [CYMOVERHEADLINE] WHERE LineId='DEFAULT'"),
        ("UG_DEFAULT", "SELECT Count(*) AS N FROM [CYMUNDERGROUNDLINE] WHERE CableId='DEFAULT'"),
        ("SEC_DEFAULT", "SELECT Count(*) AS N FROM [CYMSECTIONALIZER] WHERE EquipmentId='DEFAULT'"),
        ("OH_total", "SELECT Count(*) AS N FROM [CYMOVERHEADLINE]"),
        ("UG_total", "SELECT Count(*) AS N FROM [CYMUNDERGROUNDLINE]"),
        ("SEC_total", "SELECT Count(*) AS N FROM [CYMSECTIONALIZER]"),
    ):
        rows = _ace_query(mdb, sql)
        out[label] = int(float(rows[0].get("N") or 0)) if rows else 0
    return out


def backup_mdb(mdb, out_dir):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(out_dir, "backup_20260919_%s.mdb" % stamp)
    print("[fix-default] Backup MDB →", dest)
    shutil.copy2(mdb, dest)
    return dest


def apply_mdb_updates(mdb, targets, dry_run=False):
    """UPDATE masivo en tablas de dispositivos. No toca CYMSOURCE."""
    oh = targets["OverheadLine"]["id"]
    cab = targets["Cable"]["id"]
    sec = targets["Sectionalizer"]["id"]
    stmts = [
        ("OH", "UPDATE [CYMOVERHEADLINE] SET LineId='%s' WHERE LineId='DEFAULT'" % oh),
        ("UG", "UPDATE [CYMUNDERGROUNDLINE] SET CableId='%s' WHERE CableId='DEFAULT'" % cab),
        ("SEC", "UPDATE [CYMSECTIONALIZER] SET EquipmentId='%s' WHERE EquipmentId='DEFAULT'" % sec),
    ]
    results = []
    for label, sql in stmts:
        print("[fix-default]", "DRY" if dry_run else "EXEC", label, sql)
        if not dry_run:
            _ace_exec(mdb, sql)
        results.append({"table": label, "sql": sql})
    return results


def verify_no_source_change(mdb, before_sample):
    """Comprueba que NominalKVLL de fuentes no cambió."""
    rows = _ace_query(
        mdb,
        "SELECT TOP 5 EquipmentId, NominalKVLL, DesiredKVLL FROM [CYMEQSOURCE]",
    )
    return {"before": before_sample, "after": rows, "ok": True}


def refresh_eld_study(settings, targets):
    """Reabre ELD, carga redes, verifica muestra, guarda (no cambia fuentes)."""
    import cympy
    import cympy.db as db
    import cympy.study as study

    conn = settings.get("database_connection_name") or "20260919"
    study_path = settings.get("eld_study_path")
    db.ConnectDatabaseByName(conn)
    study.Open(study_path)
    nets = [str(n) for n in list(db.ListNetworks())]
    opt = cympy.enums.LoadNetworkOption.NoDependencies
    print("[fix-default] LoadNetworks(%d)..." % len(nets))
    study.LoadNetworks(nets, opt)

    # Verificar muestra PA217
    net = "NET_2030_179_PA217"
    sample = {"oh": [], "ug": [], "sources": []}
    if net in list(study.ListNetworks()):
        oh = list(cympy.study.ListDevices(cympy.enums.DeviceType.OverheadLine, net))[:5]
        ug = list(cympy.study.ListDevices(cympy.enums.DeviceType.Underground, net))[:5]
        for d in oh:
            sample["oh"].append({
                "DeviceNumber": d.DeviceNumber,
                "LineID": str(d.GetValue("LineID") or ""),
            })
        for d in ug:
            sample["ug"].append({
                "DeviceNumber": d.DeviceNumber,
                "CableID": str(d.GetValue("CableID") or ""),
            })
        srcs = list(cympy.study.ListDevices(cympy.enums.DeviceType.Source, net))[:3]
        for s in srcs:
            row = {"DeviceNumber": s.DeviceNumber}
            for f in ("OperatingVoltageA", "OperatingVoltageB", "OperatingVoltageC"):
                try:
                    row[f] = str(s.GetValue(f) or "")
                except Exception:
                    pass
            sample["sources"].append(row)

    # Contar DEFAULT residuales en memoria
    n_def_oh = 0
    n_def_ug = 0
    for net_id in list(study.ListNetworks())[:5]:  # muestra 5 redes
        for d in cympy.study.ListDevices(cympy.enums.DeviceType.OverheadLine, net_id):
            if str(d.GetValue("LineID") or "").upper() == "DEFAULT":
                n_def_oh += 1
        for d in cympy.study.ListDevices(cympy.enums.DeviceType.Underground, net_id):
            if str(d.GetValue("CableID") or "").upper() == "DEFAULT":
                n_def_ug += 1

    study.Save(study_path, False)
    try:
        db.Update()
    except Exception as ex:
        print("[fix-default] AVISO db.Update:", ex)

    return {
        "sample": sample,
        "residual_DEFAULT_oh_sample5nets": n_def_oh,
        "residual_DEFAULT_ug_sample5nets": n_def_ug,
        "targets": targets,
    }


def main(argv=None):
    settings = load_json("config/settings.json")
    ap = argparse.ArgumentParser(description="DEFAULT → AAAC/XLPE misma seccion")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--skip-refresh", action="store_true", help="Solo MDB, no reabrir ELD")
    args = ap.parse_args(argv)

    mdb = settings.get("database_mdb")
    if not mdb or not os.path.isfile(mdb):
        print("FAIL: database_mdb no existe:", mdb)
        return 1

    out_dir = _out_dir(settings)
    report = {
        "timestamp": ts(),
        "mdb": mdb,
        "dry_run": bool(args.dry_run),
        "policy": "DEFAULT→AAAC/XLPE misma seccion; NO tocar fuentes/tensiones",
    }

    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(settings)
    except Exception as ex:
        print("AVISO pause:", ex)

    print("[fix-default] Contar DEFAULT antes...")
    before = count_defaults(mdb)
    report["counts_before"] = before
    print(before)

    src_before = _ace_query(
        mdb, "SELECT TOP 5 EquipmentId, NominalKVLL, DesiredKVLL FROM [CYMEQSOURCE]"
    )
    report["sources_before"] = src_before

    # Resolver targets con CymPy (biblioteca)
    import cympy
    import cympy.db as db
    db.ConnectDatabaseByName(settings.get("database_connection_name") or "20260919")
    targets = resolve_targets(cympy, settings)
    report["targets"] = targets
    print("[fix-default] Targets:", json.dumps(targets, ensure_ascii=False, indent=2))

    for kind, t in targets.items():
        if not t.get("id"):
            print("FAIL: sin ID para", kind)
            return 1
        et = "Cable" if kind == "Cable" else kind
        if not equipment_exists(cympy, t["id"], et):
            print("FAIL: equipo no existe en biblioteca:", t["id"], et)
            return 1

    try:
        db.DisconnectDatabase()
        print("[fix-default] BD desconectada para UPDATE ACE")
    except Exception as ex:
        print("[fix-default] AVISO DisconnectDatabase:", ex)

    if not args.skip_backup and not args.dry_run:
        report["backup"] = backup_mdb(mdb, out_dir)

    report["updates"] = apply_mdb_updates(mdb, targets, dry_run=args.dry_run)

    after = count_defaults(mdb) if not args.dry_run else before
    report["counts_after"] = after
    print("[fix-default] Contar DEFAULT despues:", after)

    if not args.dry_run:
        residual = (
            int(after.get("OH_DEFAULT") or 0)
            + int(after.get("UG_DEFAULT") or 0)
            + int(after.get("SEC_DEFAULT") or 0)
        )
        if residual > 0:
            raise RuntimeError(
                "Quedan %d DEFAULT tras UPDATE (OH=%s UG=%s SEC=%s)"
                % (
                    residual,
                    after.get("OH_DEFAULT"),
                    after.get("UG_DEFAULT"),
                    after.get("SEC_DEFAULT"),
                )
            )
        report["default_cleared"] = True

    src_check = verify_no_source_change(mdb, src_before)
    report["sources_check"] = src_check
    # Validar que NominalKVLL no cambio
    before_map = {
        (r.get("EquipmentId") or ""): (r.get("NominalKVLL"), r.get("DesiredKVLL"))
        for r in (src_before or [])
    }
    after_src = src_check.get("after") or []
    drift = []
    for r in after_src:
        eid = r.get("EquipmentId") or ""
        if eid in before_map and before_map[eid] != (r.get("NominalKVLL"), r.get("DesiredKVLL")):
            drift.append({"EquipmentId": eid, "before": before_map[eid], "after": (r.get("NominalKVLL"), r.get("DesiredKVLL"))})
    if drift:
        raise RuntimeError("Se alteraron tensiones de fuente (CYMEQSOURCE): %s" % drift)
    report["sources_unchanged"] = True
    print("[fix-default] Fuentes (NominalKVLL) intactas:", after_src)

    if not args.dry_run and not args.skip_refresh:
        report["refresh"] = refresh_eld_study(settings, targets)

    path = os.path.join(out_dir, "fix_default_aaac_xlpe_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("[fix-default] Report:", path)
    print("OK" if not args.dry_run else "DRY-RUN OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("FAIL:", e)
        traceback.print_exc()
        sys.exit(1)
