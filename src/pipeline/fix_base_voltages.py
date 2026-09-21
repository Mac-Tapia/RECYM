from __future__ import print_function
"""Alinea lista de tensiones base predeterminadas + UserDefinedBaseVoltage de nodos."""
import math
from collections import Counter

from core.common import require_cympy, load_json, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings


def _vb_count(nd, path_list):
    return int(float(str(nd.GetValue(path_list + ".GetCount()")).replace(",", ".")))


def _vb_values(nd, path_list):
    vals = []
    for i in range(_vb_count(nd, path_list)):
        raw = str(nd.GetValue("%s[%d]" % (path_list, i))).replace(",", ".")
        try:
            vals.append(float(raw))
        except Exception:
            pass
    return vals


def _vb_add(nd, path_list, kv):
    """Add(22.9) en CYME trunca a 22.0; Add(0)+SetValue(float) conserva decimales."""
    kv = float(kv)
    existing = _vb_values(nd, path_list)
    if any(abs(x - kv) < 1e-3 for x in existing):
        return False
    nd.Execute("%s.Add(0)" % path_list)
    idx = _vb_count(nd, path_list) - 1
    nd.SetValue(float(kv), "%s[%d]" % (path_list, idx))
    got = str(nd.GetValue("%s[%d]" % (path_list, idx))).replace(",", ".")
    print("Agregado ValidBaseVoltage:", kv, "slot", idx, "leido", got)
    return True


def ensure_base_voltages(cympy, settings, adapter=None):
    vll = float(settings.get("voltage_ll_kv") or 22.9)
    nd = cympy.study.NetworkDiagnostic()
    path_en = "PreDeterminedNetworkBaseVoltagesVerification.Enable"
    path_list = "PreDeterminedNetworkBaseVoltagesVerification.ValidBaseVoltages"
    try:
        nd.SetValue(True, path_en)
    except Exception as ex:
        print("AVISO Enable ValidBaseVoltages:", ex)

    before = _vb_values(nd, path_list)
    print("ValidBaseVoltages antes:", before)

    # Tensiones a registrar: Vll del alimentador + todas las UserDefinedBaseVoltage de nodos
    needed = {round(vll, 5)}
    node_counts = Counter()
    for n in cympy.study.ListNodes():
        try:
            raw = str(cympy.study.GetValueNode("UserDefinedBaseVoltage", n.ID)).replace(",", ".")
            vv = float(raw)
            if vv > 0.05:
                needed.add(round(vv, 5))
                node_counts[round(vv, 5)] += 1
        except Exception:
            pass
    print("Tensiones nodos:", dict(node_counts))

    added = []
    for kv in sorted(needed):
        if _vb_add(nd, path_list, kv):
            added.append(kv)

    after = _vb_values(nd, path_list)
    print("ValidBaseVoltages despues:", after, "added", added)

    # No forzar todos los nodos a Vll: BT/MT mixtos deben conservar su base.
    # Solo rellenar nodos sin tension / basura con Vll del feeder.
    n_ok = 0
    n_fill = 0
    for n in cympy.study.ListNodes():
        try:
            raw = str(cympy.study.GetValueNode("UserDefinedBaseVoltage", n.ID)).replace(",", ".")
            vv = float(raw) if raw not in ("", "None", "none") else 0.0
        except Exception:
            vv = 0.0
        if vv <= 0.05:
            try:
                cympy.study.SetValueNode(vll, "UserDefinedBaseVoltage", n.ID)
                n_fill += 1
                n_ok += 1
            except Exception:
                pass
        else:
            n_ok += 1
    print("Nodos OK:", n_ok, "rellenados con Vll:", n_fill)

    # Fuente: OperatingVoltage LN = Vll/sqrt(3)
    net = settings.get("network_id")
    try:
        sources = list(cympy.study.ListDevices(cympy.enums.DeviceType.Source, net))
        vln = vll / math.sqrt(3.0)
        for src in sources:
            for ph in ("OperatingVoltageA", "OperatingVoltageB", "OperatingVoltageC"):
                try:
                    src.SetValue(vln, ph)
                except Exception:
                    pass
            print("Fuente", src.DeviceNumber, "OperatingVoltage LN=", round(vln, 5))
    except Exception as ex:
        print("AVISO fuentes:", ex)

    # Verificar
    try:
        nd.Run([str(net)])
        n52 = sum(1 for m in cympy.app.GetMessages(cympy.enums.Severity.Error) if str(m.Code) == "220052")
        n47 = sum(1 for m in cympy.app.GetMessages(cympy.enums.Severity.Error) if str(m.Code) == "220047")
        print("Post-fix 220052=%s 220047=%s" % (n52, n47))
    except Exception as ex:
        print("AVISO post-check:", ex)
        n52, n47 = -1, -1
    return {
        "220052": n52,
        "220047": n47,
        "nodes": n_ok,
        "filled": n_fill,
        "vll": vll,
        "added": added,
        "valid_list": after,
    }


def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    res = ensure_base_voltages(c, s, a)
    if s.get("save_after_fix", True):
        a.save_study()
        print("Estudio guardado.")
    print(res)


if __name__ == "__main__":
    run_cympy_main(main)
