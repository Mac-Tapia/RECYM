from __future__ import print_function
"""Alinea lista de tensiones base predeterminadas + UserDefinedBaseVoltage de nodos."""
import math
from core.common import require_cympy, load_json, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings

def ensure_base_voltages(cympy, settings, adapter=None):
    vll = float(settings.get("voltage_ll_kv") or 22.9)
    nd = cympy.study.NetworkDiagnostic()
    path_en = "PreDeterminedNetworkBaseVoltagesVerification.Enable"
    path_list = "PreDeterminedNetworkBaseVoltagesVerification.ValidBaseVoltages"
    nd.SetValue(True, path_en)

    count = int(float(str(nd.GetValue(path_list + ".GetCount()")).replace(",", ".")))
    existing = []
    for i in range(count):
        raw = str(nd.GetValue("%s[%d]" % (path_list, i))).replace(",", ".")
        try:
            existing.append(float(raw))
        except Exception:
            pass

    if not any(abs(x - vll) < 1e-3 for x in existing):
        nd.Execute("%s.Add(%s)" % (path_list, vll))
        print("Agregado ValidBaseVoltage:", vll)
    else:
        print("ValidBaseVoltage ya incluye:", vll)

    # Nodos a tensión del alimentador
    n_ok = 0
    for n in cympy.study.ListNodes():
        try:
            cympy.study.SetValueNode(vll, "UserDefinedBaseVoltage", n.ID)
            n_ok += 1
        except Exception:
            pass
    print("Nodos actualizados UserDefinedBaseVoltage:", n_ok)

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
    nd.Run([str(net)])
    n52 = sum(1 for m in cympy.app.GetMessages(cympy.enums.Severity.Error) if str(m.Code) == "220052")
    n47 = sum(1 for m in cympy.app.GetMessages(cympy.enums.Severity.Error) if str(m.Code) == "220047")
    print("Post-fix 220052=%s 220047=%s" % (n52, n47))
    return {"220052": n52, "220047": n47, "nodes": n_ok, "vll": vll}

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
