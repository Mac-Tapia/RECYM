# -*- coding: utf-8 -*-
"""
Cierra TODOS los equipos DEFAULT en la BD CYMDIST con equipos reales ya creados.

Regla (EquipmentModeling / asignación por tramo):
  - Línea aérea  → ATVB1-22.9KV-XXX (AAAC, misma sección mm2 del DEFAULT de biblioteca)
  - Cable subt.  → XLPE### (catálogo Cu XLPE 18/30 kV)
  - Seccionador  → SEC22.9KV
  - Switch       → SW22.9KV (se crea en biblioteca si falta)
  - Fuente       → SET* más cercano a OperatingVoltage (NO se tocan OperatingVoltageA/B/C)

Nada queda pendiente: tras el UPDATE, Count(DEFAULT)=0 en tablas de dispositivos.
No modifica NominalKVLL/DesiredKVLL de CYMEQSOURCE ni UserDefinedBaseVoltage.

Uso:
  python -u src/pipeline/fix_default_aaac_xlpe.py
  python -u src/pipeline/fix_default_aaac_xlpe.py --dry-run
"""
from __future__ import print_function

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))

from core.common import load_json, mkdir, p, ts  # noqa: E402
from core.equipment_library import (  # noqa: E402
    pick_equipment,
    size_from_default_equipment,
    equipment_exists,
    inventory_library,
)

# Tabla dispositivo → (columna equipo, tipo library / lógica)
DEVICE_EQ_MAP = (
    ("CYMOVERHEADLINE", "LineId", "OverheadLine"),
    ("CYMUNDERGROUNDLINE", "CableId", "Cable"),
    ("CYMSECTIONALIZER", "EquipmentId", "Sectionalizer"),
    ("CYMSWITCH", "EquipmentId", "Switch"),
    ("CYMFUSE", "EquipmentId", "Fuse"),
    ("CYMRECLOSER", "EquipmentId", "Recloser"),
    ("CYMBREAKER", "EquipmentId", "Breaker"),
    ("CYMOVERHEADLINEUNBALANCED", "LineId", "OverheadLine"),
)

# Fuentes: solo EquipmentId; OperatingVoltage* se preserva
SOURCE_TABLE = ("CYMSOURCE", "EquipmentId", "Source")


def _out_dir(settings):
    base = os.path.join("data", "output", "system", "diagnostics", "ELD")
    full = p(*base.replace("\\", "/").split("/"))
    mkdir(full)
    return full


def _ace_query(mdb, sql):
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
    import subprocess
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            raise RuntimeError("ACE SQL fail: %s\n%s" % (proc.stderr, sql[:200]))
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
    import subprocess
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0 or "OK" not in (proc.stdout or ""):
            raise RuntimeError("ACE EXEC fail: %s %s" % (proc.stderr, proc.stdout))
    finally:
        try:
            os.remove(sql_path)
        except Exception:
            pass


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def scan_defaults(mdb):
    """Cuenta DEFAULT en todas las tablas de dispositivos conocidas (+ fuentes)."""
    out = {}
    for table, col, kind in list(DEVICE_EQ_MAP) + [SOURCE_TABLE]:
        key = "%s.%s" % (table, col)
        try:
            rows = _ace_query(
                mdb,
                "SELECT Count(*) AS N FROM [%s] WHERE [%s]='DEFAULT'" % (table, col),
            )
            out[key] = int(float(rows[0].get("N") or 0)) if rows else 0
        except Exception as ex:
            out[key] = "ERR:%s" % ex
    return out


def total_default(scan):
    n = 0
    for v in scan.values():
        if isinstance(v, int):
            n += v
    return n


def ensure_switch_equipment(cympy, eq_id="SW22.9KV"):
    """Crea Switch en biblioteca si solo existe DEFAULT (EquipmentModeling)."""
    import cympy.eq as eq
    et = cympy.enums.EquipmentType.Switch
    ids = [str(e.ID) for e in eq.ListEquipments(et)]
    if eq_id in ids:
        return eq_id, "exists"
    sw = eq.Add(eq_id, et)
    for f, v in (("RatedVoltage", 22.9), ("RatedCurrent", 100.0), ("WithstandRating", 10000.0)):
        try:
            sw.SetValue(v, f)
        except Exception:
            pass
    # Heredar de seccionador si existe
    try:
        sec = eq.GetEquipment("SEC22.9KV", cympy.enums.EquipmentType.Sectionalizer)
        for f in ("RatedVoltage", "RatedCurrent", "WithstandRating"):
            try:
                sw.SetValue(sec.GetValue(f), f)
            except Exception:
                pass
    except Exception:
        pass
    return eq_id, "created"


def list_source_equipment(mdb):
    rows = _ace_query(
        mdb, "SELECT EquipmentId, NominalKVLL, DesiredKVLL FROM [CYMEQSOURCE]"
    )
    out = []
    for r in rows:
        eid = (r.get("EquipmentId") or "").strip()
        if not eid or eid.upper() == "DEFAULT":
            continue
        out.append({
            "id": eid,
            "vll": _num(r.get("NominalKVLL")) or _num(r.get("DesiredKVLL")),
        })
    return out


def pick_source_equipment(v_ln, source_eqs, fallback="SET22.9KV"):
    """Elige SET* por OperatingVoltage LN ≈ NominalKVLL (o Vll/√3)."""
    if v_ln is None or not source_eqs:
        return fallback, "fallback"
    best = None
    best_d = 1e9
    for s in source_eqs:
        vll = s.get("vll")
        if vll is None:
            continue
        # Comparar LN directo y LL/√3
        cand = [vll, vll / math.sqrt(3.0)]
        for c in cand:
            d = abs(c - v_ln)
            if d < best_d:
                best_d = d
                best = s["id"]
    return (best or fallback), "voltage_match_d=%.4f" % best_d


def resolve_targets(cympy, settings, mdb):
    defaults = settings.get("default_equipment") or {}
    inv = inventory_library(
        cympy, ["OverheadLine", "Cable", "Sectionalizer", "Switch", "Conductor"]
    )

    sw_id = defaults.get("Switch") or "SW22.9KV"
    if sw_id == "SEC22.9KV":
        # SEC es Sectionalizer; Switch necesita ID propio en biblioteca Switch
        sw_id = "SW22.9KV"
    sw_id, sw_how = ensure_switch_equipment(cympy, sw_id)

    size_oh = size_from_default_equipment(cympy, "OverheadLine")
    oh_id, oh_how = pick_equipment(
        cympy, "OverheadLine",
        preferred_id=defaults.get("OverheadLine"),
        size_mm2=size_oh, inventory=inv,
    )
    size_cab = size_from_default_equipment(cympy, "Cable")
    cab_id, cab_how = pick_equipment(
        cympy, "Cable",
        preferred_id=defaults.get("Cable") or defaults.get("Underground"),
        size_mm2=size_cab if size_cab else 120, inventory=inv,
    )
    sec_id, sec_how = pick_equipment(
        cympy, "Sectionalizer",
        preferred_id=defaults.get("Sectionalizer"),
        size_mm2=None, inventory=inv,
    )

    source_eqs = list_source_equipment(mdb)

    return {
        "OverheadLine": {"id": oh_id, "how": oh_how, "size_mm2": size_oh},
        "Cable": {"id": cab_id, "how": cab_how, "size_mm2": size_cab},
        "Sectionalizer": {"id": sec_id, "how": sec_how, "size_mm2": None},
        "Switch": {"id": sw_id, "how": sw_how, "size_mm2": None},
        "SourceCatalog": source_eqs,
        "SourceFallback": {"id": "SET22.9KV", "how": "catalog"},
    }


def apply_device_updates(mdb, targets, dry_run=False):
    """UPDATE masivo por tipo. No toca OperatingVoltage*."""
    mapping = {
        "OverheadLine": targets["OverheadLine"]["id"],
        "Cable": targets["Cable"]["id"],
        "Sectionalizer": targets["Sectionalizer"]["id"],
        "Switch": targets["Switch"]["id"],
    }
    results = []
    for table, col, kind in DEVICE_EQ_MAP:
        eq_id = mapping.get(kind)
        if not eq_id:
            # Fuse/Breaker/Recloser: si hay DEFAULT y no hay ID, reportar
            rows = _ace_query(
                mdb,
                "SELECT Count(*) AS N FROM [%s] WHERE [%s]='DEFAULT'" % (table, col),
            )
            n = int(float(rows[0].get("N") or 0)) if rows else 0
            if n > 0:
                raise RuntimeError(
                    "Hay %d DEFAULT en %s.%s sin equipo destino en biblioteca. "
                    "Cree el equipo en CYMDIST y agregue mapping." % (n, table, col)
                )
            continue
        sql = "UPDATE [%s] SET [%s]='%s' WHERE [%s]='DEFAULT'" % (table, col, eq_id, col)
        print("[fix-default]", "DRY" if dry_run else "EXEC", kind, sql)
        if not dry_run:
            _ace_exec(mdb, sql)
        results.append({"table": table, "col": col, "kind": kind, "id": eq_id, "sql": sql})
    return results


def apply_source_updates(mdb, targets, dry_run=False):
    """Asigna EquipmentId SET* por voltage; NO modifica OperatingVoltageA/B/C."""
    source_eqs = targets.get("SourceCatalog") or []
    fallback = (targets.get("SourceFallback") or {}).get("id") or "SET22.9KV"
    rows = _ace_query(
        mdb,
        "SELECT DeviceNumber, NetworkId, EquipmentId, "
        "OperatingVoltageA, OperatingVoltageB, OperatingVoltageC "
        "FROM [CYMSOURCE] WHERE EquipmentId='DEFAULT'",
    )
    updates = []
    # Agrupar por SET elegido para UPDATE masivo cuando posible
    by_set = {}
    for r in rows:
        va = _num(r.get("OperatingVoltageA"))
        eq_id, how = pick_source_equipment(va, source_eqs, fallback=fallback)
        by_set.setdefault(eq_id, []).append({
            "DeviceNumber": r.get("DeviceNumber"),
            "NetworkId": r.get("NetworkId"),
            "Vln": va,
            "how": how,
            "OpA": r.get("OperatingVoltageA"),
            "OpB": r.get("OperatingVoltageB"),
            "OpC": r.get("OperatingVoltageC"),
        })
    for eq_id, devices in by_set.items():
        # UPDATE por DeviceNumber para no tocar voltajes
        for d in devices:
            dn = (d.get("DeviceNumber") or "").replace("'", "''")
            sql = (
                "UPDATE [CYMSOURCE] SET [EquipmentId]='%s' "
                "WHERE [DeviceNumber]='%s' AND [EquipmentId]='DEFAULT'"
                % (eq_id, dn)
            )
            print(
                "[fix-default]",
                "DRY" if dry_run else "EXEC",
                "Source",
                dn,
                "→",
                eq_id,
                "(Vln=%s, Op intacto)" % d.get("Vln"),
            )
            if not dry_run:
                _ace_exec(mdb, sql)
            updates.append({"DeviceNumber": dn, "EquipmentId": eq_id, "Vln": d.get("Vln")})
    return updates


def verify_sources_voltages(mdb, before_rows):
    after_rows = _ace_query(
        mdb,
        "SELECT DeviceNumber, EquipmentId, "
        "OperatingVoltageA, OperatingVoltageB, OperatingVoltageC "
        "FROM [CYMSOURCE]",
    )
    before_map = {
        r.get("DeviceNumber"): (
            r.get("OperatingVoltageA"),
            r.get("OperatingVoltageB"),
            r.get("OperatingVoltageC"),
        )
        for r in (before_rows or [])
    }
    drift = []
    for r in after_rows:
        dn = r.get("DeviceNumber")
        cur = (
            r.get("OperatingVoltageA"),
            r.get("OperatingVoltageB"),
            r.get("OperatingVoltageC"),
        )
        if dn in before_map and before_map[dn] != cur:
            drift.append({"DeviceNumber": dn, "before": before_map[dn], "after": cur})
    # CYMEQSOURCE library voltages
    lib = _ace_query(
        mdb, "SELECT EquipmentId, NominalKVLL, DesiredKVLL FROM [CYMEQSOURCE]"
    )
    return {
        "ok": len(drift) == 0,
        "drift": drift,
        "n_sources": len(after_rows),
        "library": lib,
        "after_devices": after_rows[:10],
    }


def backup_mdb(mdb, out_dir):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(out_dir, "backup_20260919_%s.mdb" % stamp)
    print("[fix-default] Backup MDB →", dest)
    shutil.copy2(mdb, dest)
    return dest


def refresh_eld_study(settings, targets):
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

    oh_id = targets["OverheadLine"]["id"]
    cab_id = targets["Cable"]["id"]
    sw_id = targets["Switch"]["id"]
    net = "NET_2030_179_PA217"
    sample = {}
    if net in list(study.ListNetworks()):
        for d in list(cympy.study.ListDevices(cympy.enums.DeviceType.OverheadLine, net))[:3]:
            lid = str(d.GetValue("LineID") or "")
            if lid != oh_id:
                raise RuntimeError("OH %s LineID=%s != %s" % (d.DeviceNumber, lid, oh_id))
        for d in list(cympy.study.ListDevices(cympy.enums.DeviceType.Underground, net))[:3]:
            cid = str(d.GetValue("CableID") or "")
            if cid != cab_id:
                raise RuntimeError("UG %s CableID=%s != %s" % (d.DeviceNumber, cid, cab_id))
        sample["ok"] = True
        sample["expected"] = {"OH": oh_id, "UG": cab_id, "Switch": sw_id}

    study.Save(study_path, False)
    try:
        db.Update()
    except Exception as ex:
        print("[fix-default] AVISO db.Update:", ex)
    return {"sample": sample, "n_networks": len(nets)}


def main(argv=None):
    settings = load_json("config/settings.json")
    ap = argparse.ArgumentParser(description="Cerrar TODOS los DEFAULT con equipos creados")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-backup", action="store_true")
    ap.add_argument("--skip-refresh", action="store_true")
    ap.add_argument("--skip-sources", action="store_true", help="No tocar CYMSOURCE.EquipmentId")
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
        "policy": (
            "Cerrar DEFAULT con equipos creados (AAAC/XLPE/SEC/SW/SET). "
            "Tramo/sección → LineID/CableID. Fuentes: solo EquipmentId; OpV intacto."
        ),
    }

    try:
        from core.cymdist_com import pause_cymdist_for_cympy
        pause_cymdist_for_cympy(settings)
    except Exception as ex:
        print("AVISO pause:", ex)

    print("[fix-default] Scan DEFAULT antes...")
    before = scan_defaults(mdb)
    report["defaults_before"] = before
    print(json.dumps(before, ensure_ascii=False, indent=2))

    src_volt_before = _ace_query(
        mdb,
        "SELECT DeviceNumber, EquipmentId, "
        "OperatingVoltageA, OperatingVoltageB, OperatingVoltageC "
        "FROM [CYMSOURCE]",
    )
    report["source_voltages_before"] = [
        {
            "DeviceNumber": r.get("DeviceNumber"),
            "EquipmentId": r.get("EquipmentId"),
            "OpA": r.get("OperatingVoltageA"),
            "OpB": r.get("OperatingVoltageB"),
            "OpC": r.get("OperatingVoltageC"),
        }
        for r in src_volt_before
    ]

    import cympy
    import cympy.db as db
    db.ConnectDatabaseByName(settings.get("database_connection_name") or "20260919")
    targets = resolve_targets(cympy, settings, mdb)
    # Persist newly created Switch to MDB
    try:
        db.Update()
    except Exception as ex:
        print("AVISO db.Update library:", ex)
    report["targets"] = {
        k: v for k, v in targets.items() if k != "SourceCatalog"
    }
    report["source_catalog"] = targets.get("SourceCatalog")
    print("[fix-default] Targets:", json.dumps(report["targets"], ensure_ascii=False, indent=2))

    for kind in ("OverheadLine", "Cable", "Sectionalizer", "Switch"):
        t = targets[kind]
        et = "Cable" if kind == "Cable" else kind
        if not t.get("id") or not equipment_exists(cympy, t["id"], et):
            print("FAIL: equipo destino invalido", kind, t)
            return 1

    try:
        db.DisconnectDatabase()
        print("[fix-default] BD desconectada para UPDATE ACE")
    except Exception as ex:
        print("[fix-default] AVISO Disconnect:", ex)

    if not args.skip_backup and not args.dry_run:
        report["backup"] = backup_mdb(mdb, out_dir)

    report["device_updates"] = apply_device_updates(mdb, targets, dry_run=args.dry_run)
    if not args.skip_sources:
        report["source_updates"] = apply_source_updates(mdb, targets, dry_run=args.dry_run)
    else:
        report["source_updates"] = []

    after = scan_defaults(mdb) if not args.dry_run else before
    report["defaults_after"] = after
    print("[fix-default] Scan DEFAULT despues:", json.dumps(after, ensure_ascii=False, indent=2))

    if not args.dry_run:
        left = total_default(after)
        if left > 0:
            raise RuntimeError(
                "Quedan %d DEFAULT pendientes — nada debe quedar: %s" % (left, after)
            )
        report["default_cleared"] = True

    volt_check = verify_sources_voltages(mdb, src_volt_before)
    report["source_voltage_check"] = {
        "ok": volt_check["ok"],
        "drift": volt_check["drift"],
        "n_sources": volt_check["n_sources"],
    }
    if not volt_check["ok"]:
        raise RuntimeError("OperatingVoltage de fuentes cambio: %s" % volt_check["drift"])
    print(
        "[fix-default] OperatingVoltage fuentes intactas (%d sources)"
        % volt_check["n_sources"]
    )

    if not args.dry_run and not args.skip_refresh:
        report["refresh"] = refresh_eld_study(settings, targets)
        # Re-scan after refresh
        after2 = scan_defaults(mdb)
        report["defaults_after_refresh"] = after2
        if total_default(after2) > 0:
            raise RuntimeError("Tras refresh siguen DEFAULT: %s" % after2)

    path = os.path.join(out_dir, "fix_default_aaac_xlpe_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("[fix-default] Report:", path)
    print("OK — 0 DEFAULT pendientes" if not args.dry_run else "DRY-RUN OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("FAIL:", e)
        traceback.print_exc()
        sys.exit(1)
