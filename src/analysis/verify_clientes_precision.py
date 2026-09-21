# -*- coding: utf-8 -*-
"""
Prueba de precisión: relee KWH/KW desde CYMDIST y compara vs EA/Pot del archivo CI.
"""
from __future__ import print_function
import json
import math
import os
from core.common import require_cympy, load_json, write_csv, mkdir, run_cympy_main
from core.feeder_context import load_settings, output_path
from core.cympy_adapter import CymPyAdapter

def _f(v):
    """Parse number; CYMDIST GetValue often returns locale comma decimals."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace(" ", "").replace("\xa0", "")
        if not s:
            return None
        if "," in s and "." in s:
            # 1.234.567,89 or 1,234,567.89
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return None

def _close(a, b, tol):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= float(tol)

def read_load_values(adapter, load_id):
    cfg = adapter.obj_cfg("Load")
    d = adapter.get_device("Load", load_id)
    value_base = cfg.get("value_base") or (
        "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue"
    )
    kwh_field = cfg.get("kwh_field") or (
        "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].KWH"
    )
    errs = []
    kwh = kw = kvar = load_type = None
    try:
        kwh = _f(d.GetValue(kwh_field))
    except Exception as ex:
        errs.append("KWH:" + str(ex))
    try:
        load_type = str(d.GetValue(value_base + ".GetType()") or "")
    except Exception as ex:
        errs.append("TYPE:" + str(ex))
    # Prefer KW/KVAR; fallback PF variants
    for p_suf, q_suf in (("KW", "KVAR"), ("KW", "PF"), ("KVA", "PF")):
        try:
            pv = _f(d.GetValue(value_base + "." + p_suf))
            qv = _f(d.GetValue(value_base + "." + q_suf))
            if pv is not None:
                if p_suf == "KW":
                    kw = pv
                    if q_suf == "KVAR":
                        kvar = qv
                    elif q_suf == "PF" and qv:
                        # reconstruct kvar from PF
                        import math
                        pf = max(0.01, min(1.0, abs(qv)))
                        kvar = kw * math.tan(math.acos(pf))
                elif p_suf == "KVA" and qv:
                    import math
                    pf = max(0.01, min(1.0, abs(qv)))
                    kw = pv * pf
                    kvar = pv * math.sin(math.acos(pf))
                break
        except Exception as ex:
            errs.append("%s/%s:%s" % (p_suf, q_suf, ex))
    # Also try configured p_field/q_field
    if kw is None:
        try:
            kw = _f(d.GetValue(cfg.get("p_field") or (value_base + ".KW")))
            kvar = _f(d.GetValue(cfg.get("q_field") or (value_base + ".KVAR")))
        except Exception as ex:
            errs.append("pq_cfg:" + str(ex))
    return {"KWH": kwh, "KW": kw, "KVAR": kvar, "Type": load_type, "errs": errs}

def main():
    s = load_settings()
    table_path = output_path(s, "clientes", "clientes_alimentador.json")
    if not os.path.isfile(table_path):
        print("ERROR: no existe tabla clientes:", table_path)
        raise SystemExit(2)

    with open(table_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows") or data.get("data") or []
    if isinstance(data, list):
        rows = data

    tol_kwh = float(s.get("precision_tol_kwh") or 0.5)
    tol_kw = float(s.get("precision_tol_kw") or 0.01)
    fp = float(s.get("clientes_fp") or 0.95)

    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()

    report = []
    n_ok = n_fail = n_skip = 0
    for r in rows:
        lid = r.get("LoadID_CYMDIST")
        ea = _f(r.get("EA"))
        pot = _f(r.get("Pot"))
        from core.common import truthy
        if not truthy(r.get("Activo", True)):
            n_skip += 1
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": lid or "", "Estado": "SKIP_EXCLUIDO",
                "EA": ea, "Pot": pot,
                "Detalle": "Incluir off: debe estar Disconnected / 0 en CYMDIST",
            })
            continue
        if not lid:
            n_skip += 1
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": "", "Estado": "SKIP_SIN_SED",
                "EA": ea, "Pot": pot,
            })
            continue
        if ea is None and pot is None:
            n_skip += 1
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": lid, "Estado": "SKIP_SIN_EA_POT",
                "EA": ea, "Pot": pot,
            })
            continue
        try:
            got = read_load_values(a, lid)
            exp_kvar = None
            if pot is not None:
                exp_kvar = pot * math.tan(math.acos(max(0.01, min(1.0, fp))))
            ok_kwh = _close(got["KWH"], ea, tol_kwh) if ea is not None else True
            ok_kw = _close(got["KW"], pot, tol_kw) if pot is not None else True
            ok_kvar = True
            if pot is not None and got["KVAR"] is not None:
                ok_kvar = _close(got["KVAR"], exp_kvar, max(tol_kw, abs(exp_kvar) * 0.02 + 0.05))
            estado = "OK" if (ok_kwh and ok_kw and ok_kvar) else "FAIL"
            if estado == "OK":
                n_ok += 1
            else:
                n_fail += 1
            report.append({
                "Suministro": r.get("Suministro"),
                "Cliente": r.get("Cliente"),
                "SED": r.get("SED"),
                "LoadID": lid,
                "EA": ea,
                "Pot": pot,
                "KWH_CYM": got["KWH"],
                "KW_CYM": got["KW"],
                "KVAR_CYM": got["KVAR"],
                "dKWH": None if ea is None or got["KWH"] is None else round(got["KWH"] - ea, 4),
                "dKW": None if pot is None or got["KW"] is None else round(got["KW"] - pot, 4),
                "Estado": estado,
            })
            tag = "OK" if estado == "OK" else "FAIL"
            print(tag, lid, "SED", r.get("SED"),
                  "EA", ea, "->", got["KWH"],
                  "Pot", pot, "->", got["KW"])
        except Exception as ex:
            n_fail += 1
            report.append({
                "Suministro": r.get("Suministro"), "SED": r.get("SED"),
                "LoadID": lid, "Estado": "ERROR", "Detalle": str(ex),
                "EA": ea, "Pot": pot,
            })
            print("ERROR", lid, ex)

    out_csv = output_path(s, "clientes", "precision_report.csv")
    out_json = output_path(s, "clientes", "precision_report.json")
    mkdir(os.path.dirname(out_csv))
    write_csv(
        out_csv, report,
        ["Suministro", "Cliente", "SED", "LoadID", "EA", "Pot",
         "KWH_CYM", "KW_CYM", "KVAR_CYM", "dKWH", "dKW", "Estado", "Detalle"],
    )
    summary = {
        "feeder_id": s.get("feeder_id"),
        "tol_kwh": tol_kwh,
        "tol_kw": tol_kw,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "n_skip": n_skip,
        "n_total": len(report),
        "pass": n_fail == 0 and n_ok > 0,
        "rows": report,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("-" * 50)
    print("Precision OK:", n_ok, "| FAIL:", n_fail, "| SKIP:", n_skip)
    print("tol_kwh=", tol_kwh, "tol_kw=", tol_kw)
    print(out_csv)
    print(out_json)
    if n_fail:
        raise SystemExit(1)
    if n_ok == 0:
        print("AVISO: ninguna fila verificada")
        raise SystemExit(2)

if __name__ == "__main__":
    run_cympy_main(main)
