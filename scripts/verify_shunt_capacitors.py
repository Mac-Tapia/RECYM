# -*- coding: utf-8 -*-
"""Verifica condensadores shunt PA217: estado, control y efecto en tension (LF on/off).

Uso:
  .tools\\python37-win32\\python.exe -u scripts\\verify_shunt_capacitors.py
  .tools\\python37-win32\\python.exe -u scripts\\verify_shunt_capacitors.py --feeder PA217
"""
from __future__ import print_function
import json
import math
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _num(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", ".")
    if not s or s.startswith("$") or s.startswith("ERR"):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _snap_cap(c, d):
    snap = {"DeviceNumber": getattr(d, "DeviceNumber", None)}
    fields = (
        "SectionID", "DeviceID", "ConnectionStatus", "Location", "KVLN",
        "FixedKVARA", "FixedKVARB", "FixedKVARC",
        "SwitchedKVARA", "SwitchedKVARB", "SwitchedKVARC",
        "ConnectionConfiguration", "VoltageOverride",
        "VoltageOverrideOn", "VoltageOverrideOff", "VoltageOverrideDeadband",
        "CapacitorControl.OnValueA", "CapacitorControl.OffValueA",
        "ClosedPhase", "Phase",
    )
    for f in fields:
        try:
            snap[f] = d.GetValue(f)
        except Exception:
            pass
    try:
        snap["CapacitorControlType"] = d.GetValue("CapacitorControl.GetType()")
    except Exception:
        pass
    if not snap.get("SectionID"):
        try:
            snap["SectionID"] = str(getattr(d, "SectionID", "") or "")
        except Exception:
            pass
    if not snap.get("SectionID"):
        did = str(snap.get("DeviceNumber") or "").upper()
        try:
            for sec in c.study.ListSections():
                sid = getattr(sec, "ID", None)
                if not sid:
                    continue
                try:
                    for dd in sec.ListDevices():
                        if str(getattr(dd, "DeviceNumber", "")).upper() == did:
                            snap["SectionID"] = str(sid)
                            raise StopIteration
                except StopIteration:
                    raise
                except Exception:
                    continue
        except StopIteration:
            pass
        except Exception:
            pass
    fix = [_num(snap.get("FixedKVAR" + p)) or 0.0 for p in "ABC"]
    sw = [_num(snap.get("SwitchedKVAR" + p)) or 0.0 for p in "ABC"]
    snap["FixedKVAR_total"] = sum(fix)
    snap["SwitchedKVAR_total"] = sum(sw)
    snap["RatedKVAR_total"] = snap["FixedKVAR_total"] + snap["SwitchedKVAR_total"]
    return snap


def _set_caps(caps, connected):
    status = "Connected" if connected else "Disconnected"
    notes = []
    for d in caps:
        did = getattr(d, "DeviceNumber", "?")
        try:
            before = d.GetValue("ConnectionStatus")
            d.SetValue(status, "ConnectionStatus")
            after = d.GetValue("ConnectionStatus")
            notes.append("%s: %s -> %s" % (did, before, after))
        except Exception as ex:
            notes.append("%s FAIL: %s" % (did, ex))
    return notes


def _probe_nodes_for(c, s2, inventory):
    probes = []
    try:
        srcs = list(c.study.ListDevices(c.enums.DeviceType.Source, str(s2.get("network_id") or "")))
        if srcs:
            probes.append(str(getattr(srcs[0], "DeviceNumber", "") or ""))
            try:
                sid = srcs[0].GetValue("SectionID")
                if sid:
                    sec = c.study.GetSection(str(sid))
                    probes.append(str(sec.GetValue("FromNode") or ""))
                    probes.append(str(sec.GetValue("ToNode") or ""))
            except Exception:
                pass
    except Exception:
        pass
    from core.cymdist_com import _guess_source_node
    probes.append(_guess_source_node(str(s2.get("network_id") or ""), s2))
    for snap in inventory:
        sid = snap.get("SectionID")
        if not sid:
            continue
        try:
            sec = c.study.GetSection(str(sid))
            probes.append(str(sec.GetValue("FromNode") or ""))
            probes.append(str(sec.GetValue("ToNode") or ""))
        except Exception:
            pass
    seen = set()
    out = []
    for p in probes:
        p = str(p or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _com_lf_sample(settings, net, probe_nodes):
    """LoadFlow COM + Vpu en nodos sonda (incluye cabecera)."""
    from core.cymdist_com import (
        _ensure_comtypes, _access_version, _guess_source_node, _kill_cyme,
    )
    import comtypes.client

    _ensure_comtypes(settings.get("cyme_root"))
    mdb = settings.get("database_mdb") or ""
    study = settings.get("study_path") or ""
    src = _guess_source_node(net, settings)
    nodes = []
    seen = set()
    for n in [src] + list(probe_nodes or []):
        n = str(n or "").strip()
        if n and n not in seen:
            seen.add(n)
            nodes.append(n)

    _kill_cyme()
    time.sleep(0.5)
    app = None
    try:
        app = comtypes.client.CreateObject("Cymdist.Application")
        try:
            app.ShowWindow(0)
        except Exception:
            pass
        app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
        app.OpenStudy(study)

        lf = comtypes.client.CreateObject("Cymdist.LoadFlow")
        try:
            lf.SetCalculationMethod(1)
        except Exception:
            pass
        try:
            lf.NumberOfIterations = 50
            lf.CalculationTolerance = 1.0
            lf.FlatStart = 1
        except Exception:
            pass
        try:
            ret = lf.RunFromID(net)
        except Exception as ex:
            return {"ok": False, "error": str(ex), "engine": "COM"}

        topo = {}
        for kw in ("KWTOT", "KVARTOT", "KWLOSS", "KVARLOSS", "Vpu", "VpuA", "VLN", "VLL"):
            try:
                topo[kw] = lf.QueryResultNode(kw, src)
            except Exception as ex:
                topo[kw] = "ERR:%s" % ex

        vln_base = float(settings.get("voltage_ll_kv") or 22.9) / math.sqrt(3.0)
        probes = {}
        vals = []
        for nid in nodes:
            row = {"NodeID": nid}
            for kw in ("Vpu", "VpuA", "VpuB", "VpuC", "VLN"):
                try:
                    row[kw] = lf.QueryResultNode(kw, nid)
                except Exception as ex:
                    row[kw] = "ERR:%s" % ex
            probes[nid] = row
            v = _num(row.get("VpuA")) or _num(row.get("Vpu"))
            if v is None:
                vln = _num(row.get("VLN"))
                if vln is not None and vln_base > 0:
                    v = vln / vln_base
            if v is not None:
                if v > 2.5:  # kV mal etiquetado como pu
                    v = v / vln_base
                if 0.5 < v < 1.5:
                    vals.append((nid, v))

        stats = {}
        if vals:
            vs = sorted(vals, key=lambda x: x[1])
            stats = {
                "n_probes": len(vals),
                "vpu_min": vs[0][1],
                "vpu_min_node": vs[0][0],
                "vpu_max": vs[-1][1],
                "vpu_max_node": vs[-1][0],
                "vpu_avg": sum(v for _, v in vals) / float(len(vals)),
            }
        ok = False
        try:
            float(str(topo.get("KWTOT") or "").replace(",", "."))
            ok = True
        except Exception:
            ok = False
        return {
            "ok": ok,
            "engine": "COM",
            "run_return": str(ret),
            "source_node": src,
            "topo": topo,
            "probes": probes,
            "stats": stats,
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "engine": "COM"}
    finally:
        if app is not None:
            try:
                app.Close()
            except Exception:
                pass
        _kill_cyme()


def _delta(v_on, v_off):
    delta = {}
    st_on = (v_on or {}).get("stats") or {}
    st_off = (v_off or {}).get("stats") or {}
    for k in ("vpu_min", "vpu_max", "vpu_avg"):
        a_v, b_v = st_on.get(k), st_off.get(k)
        if a_v is not None and b_v is not None:
            delta[k + "_on"] = a_v
            delta[k + "_off"] = b_v
            delta[k + "_delta_pu"] = round(a_v - b_v, 5)
            delta[k + "_delta_pct"] = round((a_v - b_v) * 100.0, 3)
    kvar_on = _num(((v_on or {}).get("topo") or {}).get("KVARTOT"))
    kvar_off = _num(((v_off or {}).get("topo") or {}).get("KVARTOT"))
    if kvar_on is not None and kvar_off is not None:
        delta["KVARTOT_on"] = kvar_on
        delta["KVARTOT_off"] = kvar_off
        delta["KVARTOT_delta"] = round(kvar_on - kvar_off, 2)
    # Probes comunes
    probe_delta = {}
    pon = (v_on or {}).get("probes") or {}
    poff = (v_off or {}).get("probes") or {}
    for nid in sorted(set(pon) & set(poff)):
        a = _num((pon[nid] or {}).get("VpuA")) or _num((pon[nid] or {}).get("Vpu"))
        b = _num((poff[nid] or {}).get("VpuA")) or _num((poff[nid] or {}).get("Vpu"))
        if a is not None and b is not None:
            if a > 2.5:
                a = a  # leave raw; stats already normalized
            probe_delta[nid] = {
                "Vpu_on": a, "Vpu_off": b, "delta_pu": round(a - b, 5),
            }
    if probe_delta:
        delta["probes"] = probe_delta
    return delta


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    from core.feeder_context import load_settings, resolve_cymdist_binding, output_path
    from core.common import require_cympy, load_json, mkdir
    from core.cympy_adapter import CymPyAdapter

    s = load_settings(argv=argv)
    bind = resolve_cymdist_binding(s)
    s2 = dict(s)
    s2.update({k: bind[k] for k in ("study_path", "database_mdb", "database_connection_name")
               if bind.get(k)})
    s2["network_id"] = bind.get("network_id") or s.get("network_id")
    s2["skip_db_project_save"] = True
    s2["auto_backup"] = False
    net = str(s2.get("network_id") or "")
    vll = float(s2.get("voltage_ll_kv") or 22.9)
    vln = vll / math.sqrt(3.0)

    print("=" * 60)
    print("VERIFY SHUNT ·", s2.get("feeder_id"), "·", net)
    print("Vll=%.3f kV  Vln=%.5f kV" % (vll, vln))
    print("=" * 60)

    c = require_cympy(s2)
    a = CymPyAdapter(c, load_json("config/cympy_api_map.json"), s2)
    a.open_study(force_backup=False)

    dtype = c.enums.DeviceType.ShuntCapacitor
    caps = list(c.study.ListDevices(dtype, net))
    inventory = [_snap_cap(c, d) for d in caps]
    print("\n[1] Inventario ShuntCapacitor: %d" % len(inventory))
    for snap in inventory:
        print(
            "  - %s sec=%s eq=%s status=%s fix=%.0f sw=%.0f kvar  KVLN=%s ctrl=%s OV=%s OnA=%s OffA=%s"
            % (
                snap.get("DeviceNumber"),
                snap.get("SectionID"),
                snap.get("DeviceID"),
                snap.get("ConnectionStatus"),
                snap.get("FixedKVAR_total") or 0,
                snap.get("SwitchedKVAR_total") or 0,
                snap.get("KVLN"),
                snap.get("CapacitorControlType"),
                snap.get("VoltageOverride"),
                snap.get("CapacitorControl.OnValueA") or snap.get("VoltageOverrideOn"),
                snap.get("CapacitorControl.OffValueA") or snap.get("VoltageOverrideOff"),
            )
        )

    probe_nodes = _probe_nodes_for(c, s2, inventory)
    print("  sondas:", ", ".join(probe_nodes) or "(ninguna)")

    result = {
        "feeder_id": s2.get("feeder_id"),
        "network_id": net,
        "Vll_kV": vll,
        "Vln_kV": vln,
        "inventory": inventory,
        "n_shunt": len(inventory),
        "probe_nodes": probe_nodes,
        "findings": [],
        "ok": True,
    }
    findings = result["findings"]

    if not inventory:
        findings.append("CRITICO: no hay ShuntCapacitor en la red")
        result["ok"] = False
    for snap in inventory:
        did = snap.get("DeviceNumber")
        kvln = _num(snap.get("KVLN"))
        if kvln is not None and abs(kvln - vln) > 0.5:
            findings.append("WARN %s KVLN=%.3f esperado ~%.3f" % (did, kvln, vln))
        if (snap.get("FixedKVAR_total") or 0) < 1:
            findings.append(
                "WARN %s: FixedKVAR=0 (solo conmutado). Si V>OnValue el banco puede no inyectar kvar."
                % did
            )
        if (snap.get("RatedKVAR_total") or 0) < 1:
            findings.append("CRITICO %s: Fixed+Switched kvar = 0" % did)
            result["ok"] = False
        ov = snap.get("VoltageOverride")
        if str(ov).lower() in ("false", "0", "no"):
            findings.append("INFO %s VoltageOverride=%s" % (did, ov))

    if not inventory:
        out = output_path(s2, "diagnostics", "shunt_capacitors_verify.json")
        mkdir(os.path.dirname(out))
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)
        print("wrote", out)
        return 1

    # --- LF ON ---
    print("\n[2] LoadFlow CON condensadores Connected")
    notes_on = _set_caps(caps, True)
    print("  ", "; ".join(notes_on))
    a.save_study()
    try:
        a.close_study(save=False)
    except Exception:
        pass
    t0 = time.time()
    v_on = _com_lf_sample(s2, net, probe_nodes)
    wall_on = round(time.time() - t0, 2)
    result["lf_connected"] = v_on
    result["wall_on_s"] = wall_on
    print("  LF ok=%s wall=%.1fs topo=%s" % (
        v_on.get("ok"), wall_on,
        {k: v_on.get("topo", {}).get(k) for k in ("KWTOT", "KVARTOT", "Vpu", "VpuA")},
    ))
    print("  stats:", v_on.get("stats"))

    # --- LF OFF ---
    print("\n[3] LoadFlow SIN condensadores (Disconnected)")
    a.open_study(force_backup=False)
    caps = list(a.cympy.study.ListDevices(dtype, net))
    notes_off = _set_caps(caps, False)
    print("  ", "; ".join(notes_off))
    a.save_study()
    try:
        a.close_study(save=False)
    except Exception:
        pass
    t0 = time.time()
    v_off = _com_lf_sample(s2, net, probe_nodes)
    wall_off = round(time.time() - t0, 2)
    result["lf_disconnected"] = v_off
    result["wall_off_s"] = wall_off
    print("  LF ok=%s wall=%.1fs topo=%s" % (
        v_off.get("ok"), wall_off,
        {k: v_off.get("topo", {}).get(k) for k in ("KWTOT", "KVARTOT", "Vpu", "VpuA")},
    ))
    print("  stats:", v_off.get("stats"))

    delta = _delta(v_on, v_off)
    result["delta"] = delta
    print("\n[4] Variacion tension (ON - OFF):")
    print(json.dumps(delta, indent=2, ensure_ascii=False))

    # Restaurar Connected
    a.open_study(force_backup=False)
    caps = list(a.cympy.study.ListDevices(dtype, net))
    _set_caps(caps, True)
    a.save_study()
    try:
        a.close_study(save=False)
    except Exception:
        pass

    d_avg = delta.get("vpu_avg_delta_pu")
    d_min = delta.get("vpu_min_delta_pu")
    d_q = delta.get("KVARTOT_delta")
    if d_avg is None and d_min is None and d_q is None:
        findings.append(
            "WARN: no se midio Vpu/Q (LF sin resultados utiles en nodos sonda)"
        )
        result["ok"] = False
    else:
        lift = d_min if d_min is not None else d_avg
        if lift is not None and lift > 0.001:
            findings.append(
                "OK: condensadores elevan tension (dVpu=%.4f ~ %.2f%%)"
                % (lift, lift * 100.0)
            )
        elif d_q is not None and abs(d_q) > 50:
            findings.append(
                "PARCIAL: Q cabecera cambia %.0f kvar pero dVpu~0 (revisar lectura V)"
                % d_q
            )
        elif lift is not None and abs(lift) <= 0.001:
            findings.append(
                "WARN: dVpu ~ 0 — banco sin efecto (Fixed=0 + control no enciende, o desconectado en LF)"
            )
            result["ok"] = False
        elif lift is not None:
            findings.append("WARN: dVpu negativo al conectar (%.4f)" % lift)
            result["ok"] = False

    print("\n[5] Hallazgos:")
    for f in findings:
        print(" ", f)

    out = output_path(s2, "diagnostics", "shunt_capacitors_verify.json")
    mkdir(os.path.dirname(out))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print("\nwrote", out)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
