from __future__ import print_function
"""
Distribución de carga CYMDIST (LoadAllocation) — manual IL917115ES.

Fundamento CYME (tutorial Distribución de carga):
  - La DEMANDA de cabecera/medidor se ingresa en potencia (kW-kvar / A-FP).
  - El MÉTODO «Consumo (kWh)» usa la ENERGÍA de cada carga como peso para
    repartir esa demanda.
  - El RESULTADO que queda escrito en cada SpotLoad es potencia (kW / kvar).
  - El Flujo de carga (IL917123ES) NO redistribuye: resuelve el régimen
    permanente con esos kW-kvar ya fijados.

Flujo RECYM:
1) Cabecera P/Q (sesion UI o Control_Proyecto)
2) Fijos = clientes importantes (Pot->SED bloqueadas) si hay tabla; si no, sesion
3) LoadAllocation nativo: Modelo DEFAULT, Metodo KWHMethod, demanda
   Conectado+Total en kW-kvar, pesos = KWH de cada carga
4) Si Run falla (p.ej. 130013): fallback prorrateo por KWH (misma logica;
   cargas con KWH<=0 reciben 0 kW/kvar, como CYME)
5) Cargas nuevas §3 (SpotLoad concentrada) quedan Locked y NO entran en el
   prorrateo: tras conectarlas el analisis sigue con LoadFlow, no redistribuye.
"""
import json
import math
import os
from core.common import require_cympy, load_json, write_csv, truthy, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, output_path, control_path
from core.excel_io import read_kv
from pipeline.add_spot_load import new_loads_as_fixed

def compute_head_pq(mode, p_kw, q_kvar=None, cosfi=None, i_a=None, v_ll_kv=None):
    """
    Calcula P/Q de cabecera desde medicion de maxima demanda.
    Modos:
      KW_KVAR  — P (kW) + Q (kvar)
      KW_COSFI — P (kW) + cosφ
      A_COSFI  — I (A) + cosφ + Vll (kV) → P = √3·V·I·cosφ (kW)
    """
    mode = (mode or "KW_KVAR").upper().replace("-", "_")
    if mode in ("A_COSFI", "A_FP", "AMP_FP", "I_COSFI"):
        if i_a in (None, ""):
            raise RuntimeError("Modo A_COSFI requiere corriente I (A) de cabecera")
        if v_ll_kv in (None, ""):
            raise RuntimeError("Modo A_COSFI requiere tension Vll (kV)")
        fp = float(cosfi if cosfi not in (None, "") else 0.95)
        if fp <= 0 or fp > 1:
            raise RuntimeError("cosφ debe estar en (0, 1]")
        i = float(i_a)
        v = float(v_ll_kv)
        if i < 0 or v <= 0:
            raise RuntimeError("I (A) y Vll (kV) deben ser > 0")
        # P[kW] = √3 · Vll[kV] · I[A] · cosφ
        p = math.sqrt(3.0) * v * i * fp
        q = p * math.tan(math.acos(fp))
        return p, q
    p = float(p_kw)
    if mode in ("KW_KVAR", "KWKVAR", "PQ"):
        if q_kvar in (None, ""):
            raise RuntimeError("Modo KW_KVAR requiere Q_kvar")
        q = float(q_kvar)
    elif mode in ("KW_COSFI", "KW_FP", "KWCOSFI", "PF"):
        fp = float(cosfi)
        if fp <= 0 or fp > 1:
            raise RuntimeError("cosφ debe estar en (0, 1]")
        q = p * math.tan(math.acos(fp))
    else:
        raise RuntimeError("Modo de cabecera no soportado: " + mode)
    return p, q

def set_network_demand(cympy, network_id, p_kw, q_kvar):
    """
    Escribe demanda física en CYMDIST = Propiedades de la red > Demanda:
    Ingresar demanda + Conectado + Total + tipo kW-kvar → casilleros (P, Q).
    Solo API CymPy (nada inventado).
    """
    from cympy.properties import properties as props

    net = str(network_id or "").strip()
    if not net:
        raise RuntimeError("Falta network_id para escribir Demanda de cabecera en CYMDIST")
    p_kw = float(p_kw)
    q_kvar = float(q_kvar)

    # Asegurar red cargada/activa en el estudio físico
    try:
        loaded = [str(x) for x in list(cympy.study.ListNetworks())]
    except Exception:
        loaded = []
    if net not in loaded:
        try:
            opt = cympy.enums.LoadNetworkOption.NoDependencies
            cympy.study.LoadNetwork(net, opt)
            print("LoadNetwork OK:", net)
        except Exception as ex:
            raise RuntimeError(
                "No se pudo cargar la red %s en el estudio CYMDIST: %s" % (net, ex)
            )

    lap = props.LoadAllocation()
    la = lap._cympyObject
    meter = cympy.study.Meter()
    meter.Connected = True
    meter.IsTotalDemand = True
    meter.LoadValueType = cympy.enums.LoadValueType.KW_KVAR
    meter.DemandTotal = cympy.study.LoadValue(p_kw, q_kvar)
    la.SetDemand(net, meter)
    print("SetDemand OK", net, "P=", p_kw, "Q=", q_kvar)
    return {
        "network_id": net,
        "P_kW": p_kw,
        "Q_kvar": q_kvar,
        "Connected": True,
        "Total": True,
        "Tipo": "kW-kvar",
        "api": "cympy.LoadAllocation.SetDemand",
    }


def set_source_phase_voltages(cympy, network_id, va_kv, vb_kv, vc_kv, vll_kv=None):
    """Escribe tensiones de fase LN (kV) en la fuente / equivalente del alimentador.

    Campos CYMDIST: OperatingVoltageA/B/C (kV LN). Si hay Vll, también intenta
    OperatingVoltage / NominalVoltage en LL.
    """
    import math

    net = str(network_id or "").strip()
    if not net:
        raise RuntimeError("Falta network_id para tensiones de fuente")
    va = float(va_kv)
    vb = float(vb_kv)
    vc = float(vc_kv)
    if min(va, vb, vc) <= 0:
        raise RuntimeError("Tensiones de fase A/B/C deben ser > 0 kV")

    try:
        loaded = [str(x) for x in list(cympy.study.ListNetworks())]
    except Exception:
        loaded = []
    if net not in loaded:
        try:
            opt = cympy.enums.LoadNetworkOption.NoDependencies
            cympy.study.LoadNetwork(net, opt)
        except Exception as ex:
            raise RuntimeError("No se pudo cargar la red %s: %s" % (net, ex))

    sources = []
    for dtype_name in ("Source", "EquivalentSource"):
        try:
            dtype = getattr(cympy.enums.DeviceType, dtype_name)
        except Exception:
            continue
        try:
            for d in list(cympy.study.ListDevices(dtype, net)):
                sources.append((dtype_name, d))
        except Exception as ex:
            print("AVISO ListDevices %s: %s" % (dtype_name, ex))

    if not sources:
        raise RuntimeError(
            "No hay fuente/equivalente en la red %s para escribir tensiones A/B/C" % net
        )

    vll = float(vll_kv) if vll_kv not in (None, "") else None
    if vll is None:
        # reconstruir LL aprox. desde promedio LN
        vll = ((va + vb + vc) / 3.0) * math.sqrt(3.0)

    written = []
    for dtype_name, src in sources:
        sid = str(getattr(src, "DeviceNumber", None) or getattr(src, "ID", None) or "?")
        row = {"device": sid, "type": dtype_name, "fields": {}}
        for fld, val in (
            ("OperatingVoltageA", va),
            ("OperatingVoltageB", vb),
            ("OperatingVoltageC", vc),
        ):
            try:
                src.SetValue(float(val), fld)
                row["fields"][fld] = float(val)
            except Exception as ex:
                row["fields"][fld] = "ERR:%s" % ex
        for fld in ("OperatingVoltage", "NominalVoltage", "RatedVoltage"):
            try:
                src.SetValue(float(vll), fld)
                row["fields"][fld] = float(vll)
                break
            except Exception:
                continue
        written.append(row)
        print(
            "Fuente", sid, "Vph LN A/B/C=",
            round(va, 5), round(vb, 5), round(vc, 5), "Vll=", round(vll, 5)
        )

    return {
        "network_id": net,
        "Vll_kV": vll,
        "Va_kV": va,
        "Vb_kV": vb,
        "Vc_kV": vc,
        "sources": written,
        "api": "Source.OperatingVoltageA/B/C",
    }


def sync_control_excel_cabecera(settings, p_kw, q_kvar, cosfi=None, fecha=None):
    """Refleja medicion UI en Control_Simulacion SOLO si el Excel existe (opcional)."""
    book = control_path(settings)
    if not book or not os.path.isfile(book):
        return None
    from core.excel_io import write_kv
    updates = {
        "Demanda_Max_Cabecera_kW": float(p_kw),
        "Q_Cabecera_kvar": float(q_kvar),
    }
    if cosfi not in (None, ""):
        try:
            updates["FP_Cabecera"] = float(cosfi)
        except Exception:
            pass
    if fecha not in (None, ""):
        updates["Fecha_Medicion_Cabecera"] = str(fecha)
    write_kv(book, "Control_Proyecto", updates)
    return book


def apply_cabecera_medicion(settings, p_kw, q_kvar, save=True,
                            vll_kv=None, va_kv=None, vb_kv=None, vc_kv=None):
    """Escribe cabecera física: SetDemand P/Q + tensiones fuente A/B/C (si vienen)."""
    import math

    api = load_json("config/cympy_api_map.json")
    c = require_cympy(settings)
    a = CymPyAdapter(c, api, settings)
    a.open_study(force_backup=False)
    info = set_network_demand(c, settings.get("network_id"), p_kw, q_kvar)
    info["study_path"] = settings.get("study_path")
    info["feeder_id"] = settings.get("feeder_id")

    # Tensiones de fase en fuente/equivalente del alimentador
    has_ph = all(x not in (None, "") for x in (va_kv, vb_kv, vc_kv))
    if has_ph or vll_kv not in (None, ""):
        vll = float(vll_kv) if vll_kv not in (None, "") else None
        if has_ph:
            va, vb, vc = float(va_kv), float(vb_kv), float(vc_kv)
        else:
            vln = float(vll) / math.sqrt(3.0)
            va = vb = vc = vln
        try:
            info["source_voltage"] = set_source_phase_voltages(
                c, settings.get("network_id"), va, vb, vc, vll_kv=vll
            )
        except Exception as ex_v:
            print("AVISO tensiones fuente:", ex_v)
            info["source_voltage_error"] = str(ex_v)

    if save and settings.get("save_after_fix", True):
        try:
            a.save_study()
            info["saved"] = True
            print("Estudio guardado:", settings.get("study_path"))
        except Exception as ex_save:
            print("AVISO Save estudio (SetDemand ya aplicado):", ex_save)
            info["saved"] = False
            info["save_error"] = str(ex_save)
    else:
        info["saved"] = False
    return info

def session_path(settings):
    return output_path(settings, "demand", "session.json")

def load_session(settings):
    path = session_path(settings)
    if not os.path.isfile(path):
        return {
            "feeder_id": settings.get("feeder_id"),
            "mode": "KW_COSFI",
            "P_kW": None,
            "Q_kvar": None,
            "cosfi": 0.95,
            "I_A": None,
            "Vll_kV": settings.get("voltage_ll_kv") or 22.9,
            "fecha_medicion": "",
            "fixed_loads": [],
            "status": "empty",
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_session(settings, data):
    path = session_path(settings)
    data["feeder_id"] = settings.get("feeder_id")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path

def seed_session_from_excel(settings, force=False):
    """Rellena cabecera desde Control_Proyecto.

    force=False: solo si la sesion no tiene P_kW (compat UI).
    force=True: sobrescribe cabecera desde Excel (pipeline CLI).
    """
    sess = load_session(settings)
    if not force and sess.get("P_kW") not in (None, ""):
        return sess
    book = control_path(settings)
    if not os.path.isfile(book):
        return sess
    ctrl = read_kv(book, "Control_Proyecto")
    if ctrl.get("Demanda_Max_Cabecera_kW") in (None, ""):
        return sess
    sess["P_kW"] = float(ctrl["Demanda_Max_Cabecera_kW"])
    if ctrl.get("Q_Cabecera_kvar") not in (None, ""):
        sess["mode"] = "KW_KVAR"
        sess["Q_kvar"] = float(ctrl["Q_Cabecera_kvar"])
    if ctrl.get("FP_Cabecera") not in (None, ""):
        sess["cosfi"] = float(ctrl["FP_Cabecera"])
        if sess.get("mode") != "KW_KVAR":
            sess["mode"] = "KW_COSFI"
    if ctrl.get("I_Cabecera_A") not in (None, ""):
        sess["I_A"] = float(ctrl["I_Cabecera_A"])
    if ctrl.get("Vll_Cabecera_kV") not in (None, ""):
        sess["Vll_kV"] = float(ctrl["Vll_Cabecera_kV"])
    elif settings.get("voltage_ll_kv") not in (None, ""):
        sess.setdefault("Vll_kV", float(settings.get("voltage_ll_kv")))
    if ctrl.get("Fecha_Medicion_Cabecera") not in (None, ""):
        sess["fecha_medicion"] = str(ctrl["Fecha_Medicion_Cabecera"])
    sess["status"] = "seeded_excel"
    save_session(settings, sess)
    return sess

def apply_fixed_loads(adapter, fixed_loads):
    applied = []
    for r in fixed_loads:
        if not truthy(r.get("Activo", True)):
            continue
        lid = r.get("LoadID")
        kw = float(r["kW_Fijo"])
        if r.get("kvar_Fijo") not in (None, ""):
            kvar = float(r["kvar_Fijo"])
        elif r.get("FP") not in (None, ""):
            fp = float(r["FP"])
            kvar = kw * math.tan(math.acos(fp))
        else:
            raise RuntimeError("Carga fija sin kvar ni FP: " + str(lid))
        before, after = adapter.set_load_pq(lid, kw, kvar, lock=True)
        applied.append({"LoadID": lid, "kW": kw, "kvar": kvar, "before": before, "after": after})
        print("FIXED", lid, kw, round(kvar, 3))
    return applied

def _parse_num(v):
    if v in (None, ""):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0

def allocate_residual_by_kwh(adapter, network_id, fixed_ids, p_res, q_res):
    """
    Fallback equivalente a metodo CYME «Consumo (kWh)» (IL917115ES):

    - Peso = energia KWH de cada SpotLoad (no fija/bloqueada).
    - Se escribe el RESULTADO en kW/kvar (lo que luego usa LoadFlow).
    - KWH <= 0 → porcion 0 (kW=kvar=0). No se inventa peso=1: CYME no asigna
      demanda a cargas sin consumo cuando el metodo es Consumo (kWh).
    """
    c = adapter.cympy
    devices = list(c.study.ListDevices(c.enums.DeviceType.SpotLoad, network_id))
    with_energy = []
    zero_energy = []
    base = "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0]"
    for d in devices:
        lid = str(getattr(d, "DeviceNumber", "") or "")
        if not lid or lid in fixed_ids:
            continue
        try:
            kwh = _parse_num(d.GetValue(base + ".KWH"))
        except Exception:
            kwh = 0.0
        if kwh > 0:
            with_energy.append((lid, kwh))
        else:
            zero_energy.append(lid)
    total = sum(w for _, w in with_energy) or 1.0
    scaled = []
    for lid, kwh in with_energy:
        share = kwh / total
        kw = p_res * share
        kvar = q_res * share
        before, after = adapter.set_load_pq(lid, kw, kvar, lock=False)
        scaled.append({
            "LoadID": lid, "kW": kw, "kvar": kvar, "share": share,
            "KWH": kwh, "weight": "KWH",
        })
    # Sin energia: 0 kW/kvar (manual: porcion segun consumo; consumo 0 => 0)
    for lid in zero_energy:
        before, after = adapter.set_load_pq(lid, 0.0, 0.0, lock=False)
        scaled.append({
            "LoadID": lid, "kW": 0.0, "kvar": 0.0, "share": 0.0,
            "KWH": 0.0, "weight": "KWH_zero",
        })
    print(
        "Fallback Consumo(kWh): %d con energia, %d sin KWH(=0 kW), residual %.1f kW"
        % (len(with_energy), len(zero_energy), p_res)
    )
    return scaled

# Compatibilidad: nombre antiguo
allocate_residual_by_connected_kva = allocate_residual_by_kwh

def fixed_from_clientes(settings, fp=0.95):
    """
    Clientes importantes ya cruzados (EA/Pot -> SED) = cargas fijas bloqueadas.
    Solo filas con EA (NIS de clientesimportantes), no inventario SpotLoad.
    El residual de cabecera se reparte sobre el resto de SpotLoads por energia (kWh).
    """
    path = output_path(settings, "clientes", "clientes_alimentador.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data.get("rows") or []
    fixed = []
    for r in rows:
        # Solo clientes importantes (tienen EA de CI). Inventario SpotLoad se ignora.
        if r.get("Origen") == "inventario_spotload":
            continue
        if r.get("EA") in (None, ""):
            continue
        lid = r.get("LoadID_CYMDIST")
        pot = r.get("Pot")
        if not lid or pot in (None, ""):
            continue
        if not r.get("Match_SED"):
            continue
        # Desmarcadas en la UI = salen del alimentador / no actualizar → no fijar demanda
        if not truthy(r.get("Activo", True)):
            continue
        fixed.append({
            "Activo": True,
            "LoadID": lid,
            "kW_Fijo": float(pot),
            "kvar_Fijo": "",
            "FP": float(settings.get("clientes_fp") or fp),
            "SED": r.get("SED"),
            "Suministro": r.get("Suministro"),
            "Fuente": "clientesimportantes",
            "EA": r.get("EA"),
        })
    return fixed


def validate_allocation_fixed_only(adapter, fixed_rows, p_cabecera_kw, p_fijos_kw=None, tol_pct=0.08):
    """Validación rápida O(n_fijos) vía GetDevice — sin ListDevices de 250+ SED.

    Tras LoadAllocation.Run OK (API), el módulo CYME iguala la demanda de cabecera;
    aquí se verifica que los fijos Locked conserven Pot/EA y se reporta balance
    esperado (cabecera − fijos = residual).
    """
    rows = []
    n_ok = n_warn = n_fail = 0
    n_zero_fixed = 0
    sum_fixed = 0.0
    cfg = adapter.obj_cfg("Load")
    base = "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0]"
    value_base = cfg.get("value_base") or (base + ".LoadValue")
    kwh_field = cfg.get("kwh_field") or (base + ".KWH")

    for fr in fixed_rows or []:
        lid = str(fr.get("LoadID") or fr.get("LoadID_CYMDIST") or "").strip()
        if not lid:
            continue
        pot = fr.get("kW_Fijo")
        if pot is None:
            pot = fr.get("Pot")
        try:
            pot_f = float(pot) if pot not in (None, "") else None
        except Exception:
            pot_f = None
        ea = fr.get("EA")
        try:
            ea_f = float(ea) if ea not in (None, "") else None
        except Exception:
            ea_f = None

        estado = "OK"
        detalle = ""
        kwh_f = kw_f = kvar = None
        try:
            d = adapter.get_device("Load", lid)
            if d is None:
                raise RuntimeError("sin dispositivo")
            try:
                kwh_f = adapter._parse_load_number(d.GetValue(kwh_field))
            except Exception:
                kwh_f = None
            try:
                kw_f = adapter._parse_load_number(d.GetValue(value_base + ".KW"))
                kvar = adapter._parse_load_number(d.GetValue(value_base + ".KVAR"))
            except Exception:
                pass
        except Exception:
            estado = "FAIL"
            detalle = "LoadID no existe en modelo CYMDIST"
            n_fail += 1
            n_zero_fixed += 1
            rows.append({
                "LoadID": lid, "tipo": "fijo", "SED": fr.get("SED") or "",
                "KWH": None, "kW": None, "kvar": None,
                "Estado": estado, "Detalle": detalle,
            })
            continue

        if kw_f is not None and kw_f > 0:
            sum_fixed += float(kw_f)

        if kw_f is None or abs(float(kw_f)) < 1e-6:
            estado = "FAIL"
            detalle = "Fijo 3.2 con kW=0 (debe conservar Pot Locked)"
            n_zero_fixed += 1
            n_fail += 1
        elif pot_f is not None and abs(float(kw_f) - pot_f) > max(0.5, abs(pot_f) * 0.02):
            estado = "WARN"
            detalle = "Fijo kW=%.3f ≠ Pot=%.3f" % (float(kw_f), pot_f)
            n_warn += 1
        elif ea_f is not None and (kwh_f is None or abs(float(kwh_f)) < 1e-6):
            estado = "FAIL"
            detalle = "Fijo sin Consumo(KWH); EA esperada=%.1f" % ea_f
            n_fail += 1
        else:
            detalle = "Fijo Locked OK"
            n_ok += 1

        rows.append({
            "LoadID": lid, "tipo": "fijo", "SED": fr.get("SED") or "",
            "KWH": kwh_f, "kW": kw_f, "kvar": kvar,
            "Estado": estado, "Detalle": detalle,
        })

    p_cab = float(p_cabecera_kw or 0)
    p_fix = float(p_fijos_kw if p_fijos_kw is not None else sum_fixed)
    residual_esperada = max(0.0, p_cab - p_fix)
    # Balance: fijos ≈ Pot y cabecera coherente (LoadAllocation API ya repartió residual)
    bal_ok = True
    if p_fix > 0 and sum_fixed > 0:
        pct_f = abs(sum_fixed - p_fix) / max(p_fix, 1e-9)
        if pct_f > float(tol_pct):
            bal_ok = False
            n_fail += 1
    balance_msg = (
        "Fijos ΣkW=%.1f · cabecera=%.1f · residual esperado=%.1f (API LoadAllocation)"
        % (sum_fixed, p_cab, residual_esperada)
    )
    ok = n_fail == 0 and bal_ok
    return {
        "ok": ok,
        "fast": True,
        "mode": "fixed_only",
        "n_ok": n_ok,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "n_zero_fixed": n_zero_fixed,
        "n_zero_residual": 0,
        "sum_kw": round(sum_fixed + residual_esperada, 3) if ok else round(sum_fixed, 3),
        "sum_fixed_kw": round(sum_fixed, 3),
        "P_cabecera_kW": p_cab,
        "balance_ok": bal_ok,
        "balance_msg": balance_msg,
        "n_loads": len(rows),
        "n_detail_rows": len(rows),
        "rows": rows,
        "msg": (
            ("Validacion rapida OK · %s" % balance_msg)
            if ok else
            ("Validacion fallos · ceros fijos=%d · %s" % (n_zero_fixed, balance_msg))
        ),
    }


def validate_allocation_sed_loads(adapter, network_id, fixed_rows, p_cabecera_kw, tol_pct=0.05, fast=True):
    """Revisa SED/SpotLoad tras LoadAllocation (API CYMDIST).

    - Fijos 3.2: KWH y kW no deben ser cero; kW ≈ Pot.
    - Residual con Consumo(KWH)>0: kW no debe quedar en 0.
    - Suma kW conectados ≈ cabecera §1.

    fast=True: índice hash LoadID; detalle CSV solo fijos + FAIL/WARN (no 250 OK).
    """
    fixed_ids = {}
    for r in fixed_rows or []:
        lid = str(r.get("LoadID") or r.get("LoadID_CYMDIST") or "").strip()
        if not lid:
            continue
        fixed_ids[lid] = r

    rows = []
    try:
        if fast and hasattr(adapter, "snapshot_spot_loads_indexed"):
            index = adapter.snapshot_spot_loads_indexed(network_id)
            snap = list(index.values())
        else:
            snap = adapter.snapshot_spot_loads_pq_kwh(network_id, exclude_ids=None)
            index = {str(r.get("LoadID") or ""): r for r in snap}
    except Exception as ex:
        return {
            "ok": False,
            "error": "No se pudo leer SpotLoad: %s" % ex,
            "n_ok": 0,
            "n_warn": 0,
            "n_fail": 0,
            "rows": [],
        }

    sum_kw = 0.0
    n_ok = n_warn = n_fail = 0
    n_zero_residual = 0
    n_zero_fixed = 0
    detail_rows = []

    for srow in snap:
        lid = str(srow.get("LoadID") or "").strip()
        kwh = srow.get("KWH")
        kw = srow.get("kW")
        kvar = srow.get("kvar")
        try:
            kwh_f = float(kwh) if kwh is not None else None
        except Exception:
            kwh_f = None
        try:
            kw_f = float(kw) if kw is not None else None
        except Exception:
            kw_f = None
        if kw_f is not None and kw_f > 0:
            sum_kw += kw_f

        is_fixed = lid in fixed_ids
        estado = "OK"
        detalle = ""
        if is_fixed:
            fr = fixed_ids[lid]
            pot = fr.get("kW_Fijo")
            if pot is None:
                pot = fr.get("Pot")
            try:
                pot_f = float(pot) if pot not in (None, "") else None
            except Exception:
                pot_f = None
            ea = fr.get("EA")
            try:
                ea_f = float(ea) if ea not in (None, "") else None
            except Exception:
                ea_f = None
            if kw_f is None or abs(kw_f) < 1e-6:
                estado = "FAIL"
                detalle = "Fijo 3.2 con kW=0 (debe conservar Pot Locked)"
                n_zero_fixed += 1
            elif pot_f is not None and abs(kw_f - pot_f) > max(0.5, abs(pot_f) * 0.02):
                estado = "WARN"
                detalle = "Fijo kW=%.3f ≠ Pot=%.3f" % (kw_f, pot_f)
            elif ea_f is not None and (kwh_f is None or abs(kwh_f) < 1e-6):
                estado = "FAIL"
                detalle = "Fijo sin Consumo(KWH); EA esperada=%.1f" % ea_f
            else:
                detalle = "Fijo Locked OK"
        else:
            if kwh_f is not None and kwh_f > 1.0:
                if kw_f is None or abs(kw_f) < 1e-6:
                    estado = "FAIL"
                    detalle = "Residual con KWH=%.1f pero kW=0 (no distribuido)" % kwh_f
                    n_zero_residual += 1
                else:
                    detalle = "Residual distribuido"
            elif kwh_f is None or kwh_f <= 1.0:
                if kw_f is not None and abs(kw_f) < 1e-6:
                    estado = "OK"
                    detalle = "Sin KWH → kW=0 (esperado)"
                else:
                    estado = "WARN"
                    detalle = "Sin KWH pero kW=%.3f" % (kw_f or 0)

        if estado == "OK":
            n_ok += 1
        elif estado == "WARN":
            n_warn += 1
        else:
            n_fail += 1

        row = {
            "LoadID": lid,
            "tipo": "fijo" if is_fixed else "residual",
            "SED": (fixed_ids[lid].get("SED") if is_fixed else ""),
            "KWH": kwh_f,
            "kW": kw_f,
            "kvar": kvar,
            "Estado": estado,
            "Detalle": detalle,
        }
        # fast: detalle completo solo fijos + no-OK (busqueda O(1) por hash)
        if not fast or is_fixed or estado != "OK":
            detail_rows.append(row)
        rows.append(row)

    # Fijos ausentes del modelo (LoadID sin SpotLoad)
    for lid, fr in fixed_ids.items():
        if lid in index:
            continue
        n_fail += 1
        n_zero_fixed += 1
        miss = {
            "LoadID": lid,
            "tipo": "fijo",
            "SED": fr.get("SED") or "",
            "KWH": None,
            "kW": None,
            "kvar": None,
            "Estado": "FAIL",
            "Detalle": "LoadID no existe en modelo CYMDIST",
        }
        detail_rows.append(miss)
        rows.append(miss)

    balance_ok = True
    balance_msg = ""
    if p_cabecera_kw and float(p_cabecera_kw) > 0:
        pct = abs(sum_kw - float(p_cabecera_kw)) / float(p_cabecera_kw)
        balance_ok = pct <= float(tol_pct)
        balance_msg = (
            "Suma kW=%.1f vs cabecera=%.1f (Δ=%.1f%%)"
            % (sum_kw, float(p_cabecera_kw), pct * 100.0)
        )
        if not balance_ok:
            n_fail += 1

    ok = n_fail == 0 and balance_ok
    out_rows = detail_rows if fast else rows
    return {
        "ok": ok,
        "fast": bool(fast),
        "n_ok": n_ok,
        "n_warn": n_warn,
        "n_fail": n_fail,
        "n_zero_fixed": n_zero_fixed,
        "n_zero_residual": n_zero_residual,
        "sum_kw": round(sum_kw, 3),
        "P_cabecera_kW": float(p_cabecera_kw or 0),
        "balance_ok": balance_ok,
        "balance_msg": balance_msg,
        "n_loads": len(snap),
        "n_detail_rows": len(out_rows),
        "rows": out_rows,
        "msg": (
            ("Validacion OK · %s · %d cargas"
             % (balance_msg or "sin ceros indebidos", len(snap)))
            if ok else
            ("Validacion con fallos · ceros fijos=%d · ceros residual=%d · %s"
             % (n_zero_fixed, n_zero_residual, balance_msg))
        ),
    }


def run_load_allocation_module(settings, session=None):
    """3.3 · Ejecuta LoadAllocation.Run y valida SED/cargas (sin reescribir).

    Precondiciones (NO las escribe aquí):
      - §1: cabecera P/Q ya en sesion.
      - §3.2: EA→Consumo(KWH) y Pot→kW Locked ya cargados.

    Tras Run: revision de valores (no ceros indebidos, balance vs cabecera).

    Universal por alimentador: usa settings['feeder_id'] / settings['network_id']
    del contexto §1 (cualquier radial de la BD, con o sin config/feeders previa).
    PA217 es solo una muestra; al insertar otro alimentador se aplica igual.
    """
    import time as _time
    s = settings
    api = load_json("config/cympy_api_map.json")
    sess = session or load_session(s)
    if sess.get("P_kW") in (None, ""):
        raise RuntimeError(
            "Falta cabecera §1. Guarde medicion (1.2 · Cargar en la fuente) antes de 3.3."
        )

    Phead, Qhead = compute_head_pq(
        sess.get("mode"),
        sess.get("P_kW"),
        sess.get("Q_kvar"),
        sess.get("cosfi"),
    )
    fixed = fixed_from_clientes(s)
    Pfixed = sum(float(r["kW_Fijo"]) for r in fixed)
    Pres = Phead - Pfixed
    fid = str(s.get("feeder_id") or sess.get("feeder_id") or "")
    nid = str(s.get("network_id") or "")
    result = {
        "mode": sess.get("mode") or "KW_KVAR",
        "module_only": True,
        "feeder_id": fid,
        "network_id": nid,
        "P_cabecera_kW": Phead,
        "Q_cabecera_kvar": Qhead,
        "P_fijos_kW": Pfixed,
        "n_fijos": len(fixed),
        "P_residual_kW": Pres,
        "fijos_fuente": "clientesimportantes" if fixed else "ninguno",
        "aviso": (
            "3.3 · %s (%s): LoadAllocation + validacion. "
            "Cabecera=§1 · fijos Locked=§3.2. Anti-130013 se guarda en el estudio activo."
            % (fid or "alimentador", nid or "red")
        ),
        "cymdist_settings": {
            "LoadModel": "DEFAULT",
            "Method": "KWHMethod",
            "Method_UI": "Consumo (kWh)",
            "DemandType": "FeederDemand",
            "LoadFlowParamConfigID": "DEFAULT",
            "Demand_Connected": True,
            "Demand_Total": True,
            "Demand_Unit": "kW-kvar",
            "Downstream_Unit": "Consumo (kWh)",
        },
        "applied": [],
        "scaled": [],
        "status": "ok",
        "timing": {},
        "validation": None,
    }
    if not fixed:
        result["aviso_sin_fijos"] = (
            "No hay clientes fijos de 3.2 en disco. "
            "Ejecute 3.2 · Cargar EA/Pot antes si desea cargas Locked."
        )
    if Pres < 0:
        raise RuntimeError(
            "Cargas fijas (%.1f kW) superan cabecera §1 (%.1f kW)."
            % (Pfixed, Phead)
        )

    print("[%s] 3.3 LoadAllocation API (rapido)" % s.get("feeder_id"))
    print("  Cabecera §1 P/Q:", Phead, "/", round(Qhead, 3))
    print("  Fijos 3.2:", len(fixed), "->", round(Pfixed, 3), "kW")

    if s.get("dry_run"):
        result["status"] = "dry_run"
        return result

    # Enlace obligatorio: estudio del alimentador activo + BD del proyecto (cualquier radial)
    from core.feeder_context import resolve_cymdist_binding
    binding = resolve_cymdist_binding(s)
    result["cymdist_binding"] = binding
    print("[3.3] binding:", binding.get("binding"))

    # Raiz demora: SaveProject BD completo + kill/reopen Cyme + ListDevices x257
    # Se guarda .zxst del alimentador + db.Update a la BD conectada (sin SaveProject).
    s = dict(s)
    s["skip_db_project_save"] = True
    s["auto_backup"] = False
    s["study_path"] = binding["study_path"]
    s["database_mdb"] = binding["database_mdb"]
    s["database_connection_name"] = binding["database_connection_name"]
    s["network_id"] = binding["network_id"] or s.get("network_id")

    result["strategy"] = {
        "engine": "cymdist_api",
        "module": "LoadAllocation",
        "method": "KWHMethod",
        "search": "GetDevice_fixed_O(n)",
        "feeder_scope": "active_from_section1",
        "study_file": binding.get("study_file"),
        "database_file": binding.get("database_file"),
        "database_connection_name": binding.get("database_connection_name"),
        "skip_db_project_save": True,
        "db_update_after_save": False,
        "refs": [
            "Eaton CYMDIST Load Allocation (kWh / FeederDemand)",
            "CYME LF templates: Scaling/Sensitivity As Defined|FromLibrary",
            "Sandia/CymPy: ActivateRefresh(False) en automatizacion",
            "Flujo: alimentador → su .zxst + BD 20260919",
        ],
    }

    def _progress(msg):
        print("[3.3]", msg)
        try:
            cb = (settings or {}).get("_job_progress")
            if callable(cb):
                cb(msg)
        except Exception:
            pass

    t0 = _time.time()
    from core.cymdist_com import (
        pause_cymdist_for_cympy, resume_cymdist_gui, is_keep_open, cyme_is_running,
    )
    keep = is_keep_open(s)
    if keep or cyme_is_running():
        pause_info = pause_cymdist_for_cympy(s)
    else:
        pause_info = {"ok": True, "skipped": True, "paused": False}
    result["pause"] = pause_info
    result["timing"]["pause_gui_sec"] = round(_time.time() - t0, 2)
    _progress("estudio...")

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    refresh_off = False
    try:
        c.app.ActivateRefresh(False)
        refresh_off = True
    except Exception:
        try:
            c.ActivateRefresh(False)
            refresh_off = True
        except Exception:
            pass

    t1 = _time.time()
    a.open_study(force_backup=False)
    result["timing"]["open_study_sec"] = round(_time.time() - t1, 2)
    net = str(s.get("network_id") or "")
    study_dirty = False

    t_sp = _time.time()
    from core.sim_params import (
        ensure_loadflow_networks, try_repair_loadflow_defaults,
        read_lf_stamp, write_lf_stamp,
    )
    stamp = read_lf_stamp(s) or {}
    lf_cfg_id = str(
        stamp.get("ConfigID")
        or sess.get("lf_params_config_id")
        or "DEFAULT"
    )
    lf_already = bool(stamp.get("ok") or sess.get("lf_params_fixed_130013"))
    try:
        ensure_loadflow_networks(c, net)
        if lf_already:
            result["sim_params_repair"] = {
                "ok": True,
                "skipped_full": True,
                "reason": "stamp_or_session",
                "ConfigID": lf_cfg_id,
                "stamp": stamp.get("fixed_at"),
            }
            _progress("LF listo (sello) · Run...")
        else:
            repair = try_repair_loadflow_defaults(c)
            result["sim_params_repair"] = {
                "ok": repair.get("ok"),
                "notes": (repair.get("notes") or [])[:12],
                "ConfigID": repair.get("ConfigID"),
            }
            if repair.get("ConfigID"):
                lf_cfg_id = str(repair["ConfigID"])
            study_dirty = True
            write_lf_stamp(s, lf_cfg_id, repair.get("notes"))
            try:
                from datetime import datetime
                sess["lf_params_fixed_130013"] = True
                sess["lf_params_fixed_at"] = datetime.now().isoformat(timespec="seconds")
                sess["lf_params_config_id"] = lf_cfg_id
                save_session(s, sess)
            except Exception as ex_sess:
                print("AVISO session flag 130013:", ex_sess)
            _progress("LF reparado · Run...")
    except Exception as ex:
        print("AVISO sim_params:", ex)
        result["sim_params_error"] = str(ex)
    result["timing"]["sim_params_sec"] = round(_time.time() - t_sp, 2)

    try:
        c.study.SelectLoadModel("DEFAULT")
    except Exception as ex:
        print("AVISO SelectLoadModel:", ex)

    fixed_ids = set(str(r.get("LoadID")) for r in fixed)
    fixed_key = ",".join(sorted(fixed_ids))
    t_lock = _time.time()
    locks_ready = (
        sess.get("alloc_locks_ready")
        and str(sess.get("alloc_locks_fixed_key") or "") == fixed_key
    )
    if locks_ready:
        result["unlock"] = {"skipped": True, "reason": "mismos_fijos_ya_locked"}
    else:
        try:
            unlock_info = a.ensure_locks_for_allocation(net, fixed_ids)
            result["unlock"] = unlock_info
            if unlock_info.get("n_write", 0) > 0:
                study_dirty = True
            try:
                sess["alloc_locks_ready"] = True
                sess["alloc_locks_fixed_key"] = fixed_key
                save_session(s, sess)
            except Exception:
                pass
        except Exception as ex:
            print("AVISO unlock residual:", ex)
            result["unlock_error"] = str(ex)
    result["timing"]["locks_sec"] = round(_time.time() - t_lock, 2)

    def _configure_and_run_allocation(cfg_id):
        from cympy.properties import properties as props
        from cympy.properties.CymeEnums import (
            _CymdistDataEnum_DemandTypeEnum as DemandTypeEnum,
            _CymdistDataEnum_LoadAllocationMethodEnum as MethodEnum,
        )
        lap = props.LoadAllocation()
        la = lap._cympyObject
        try:
            lap.DemandType = DemandTypeEnum.FeederDemand
            lap.Method = MethodEnum.KWHMethod
            lap.LoadFlowParamConfigID = str(cfg_id or "DEFAULT")
            lap.RunVoltageDrop = False
            lap.UnlockAllLoads = False
            try:
                lap.Tolerance = 0.01
            except Exception:
                pass
        except Exception:
            la.SetValue("FeederDemand", "DemandType")
            la.SetValue("KWHMethod", "Method")
            try:
                la.SetValue(str(cfg_id or "DEFAULT"), "LoadFlowParamConfigID")
            except Exception:
                pass
        meter = c.study.Meter()
        meter.Connected = True
        meter.IsTotalDemand = True
        meter.LoadValueType = c.enums.LoadValueType.KW_KVAR
        meter.DemandTotal = c.study.LoadValue(float(Phead), float(Qhead))
        la.SetDemand(net, meter)
        print("SetDemand API §1", net, "P=", Phead, "Q=", round(Qhead, 3), "LF=", cfg_id)
        la.Run([net])

    t_run = _time.time()
    allocated = False
    alloc_error = None
    try:
        _configure_and_run_allocation(lf_cfg_id)
        result["method"] = "cymdist_LoadAllocation_KWH"
        result["status"] = "ok"
        result["allocation_ok"] = True
        allocated = True
        study_dirty = True
        _progress("LoadAllocation.Run OK")
    except Exception as ex:
        alloc_error = str(ex)
        print("AVISO LoadAllocation.Run:", alloc_error)
        need_retry = (
            "130013" in alloc_error
            or "simulacion no validos" in alloc_error.lower()
            or "simulación no válidos" in alloc_error.lower()
        )
        if need_retry:
            try:
                repair2 = try_repair_loadflow_defaults(c)
                cfg2 = str(repair2.get("ConfigID") or lf_cfg_id)
                result["sim_params_retry"] = {"ok": repair2.get("ok"), "ConfigID": cfg2}
                _configure_and_run_allocation(cfg2)
                result["method"] = "cymdist_LoadAllocation_KWH"
                result["status"] = "ok"
                result["allocation_ok"] = True
                result["allocation_retry"] = True
                allocated = True
                study_dirty = True
                lf_cfg_id = cfg2
                write_lf_stamp(s, cfg2, repair2.get("notes"))
                try:
                    from datetime import datetime
                    sess["lf_params_fixed_130013"] = True
                    sess["lf_params_fixed_at"] = datetime.now().isoformat(timespec="seconds")
                    sess["lf_params_config_id"] = cfg2
                    save_session(s, sess)
                except Exception:
                    pass
                _progress("LoadAllocation.Run OK (reintento)")
            except Exception as ex2:
                alloc_error = "%s | retry: %s" % (alloc_error, ex2)
                print("AVISO reintento API fallo:", ex2)

    if not allocated:
        q_res = float(Qhead) * (float(Pres) / float(Phead)) if Phead else 0.0
        try:
            result["scaled"] = allocate_residual_by_kwh(a, net, fixed_ids, Pres, q_res)
            result["method"] = "fallback_KWH_api"
            result["status"] = "ok_fallback_kwh"
            result["allocation_ok"] = True
            result["allocation_error"] = alloc_error
            result["aviso"] = (
                "LoadAllocation.Run (API) fallo. Fallback Consumo(kWh) via API SetValue."
            )
            allocated = True
            study_dirty = True
        except Exception as ex_fb:
            result["status"] = "error"
            result["allocation_ok"] = False
            result["allocation_error"] = alloc_error
            result["fallback_error"] = str(ex_fb)
            result["method"] = None

    result["timing"]["loadallocation_run_sec"] = round(_time.time() - t_run, 2)

    if result.get("allocation_ok"):
        t_val = _time.time()
        _progress("validacion fijos...")
        try:
            if result.get("method") == "cymdist_LoadAllocation_KWH":
                validation = validate_allocation_fixed_only(
                    a, fixed, Phead, Pfixed, tol_pct=0.08
                )
            else:
                validation = validate_allocation_sed_loads(
                    a, net, fixed, Phead, tol_pct=0.08, fast=True
                )
            result["validation"] = validation
            result["validation_ok"] = bool(validation.get("ok"))
            if not validation.get("ok"):
                if result.get("status") == "ok":
                    result["status"] = (
                        "ok_with_warnings" if validation.get("n_fail", 0) == 0 else "ok_validation_fail"
                    )
                elif result.get("status") == "ok_fallback_kwh" and validation.get("n_fail", 0) > 0:
                    result["status"] = "ok_validation_fail"
            val_path = output_path(s, "demand", "allocation_validation.json")
            with open(val_path, "w", encoding="utf-8") as f:
                json.dump(validation, f, indent=2, ensure_ascii=False)
            try:
                write_csv(
                    output_path(s, "demand", "allocation_validation.csv"),
                    validation.get("rows") or [],
                    ["LoadID", "tipo", "SED", "KWH", "kW", "kvar", "Estado", "Detalle"],
                )
            except Exception:
                pass
            result["validation_path"] = val_path
        except Exception as ex:
            result["validation"] = {"ok": False, "error": str(ex)}
            result["validation_ok"] = False
            print("AVISO validacion:", ex)
        result["timing"]["validation_sec"] = round(_time.time() - t_val, 2)

    if study_dirty and result.get("allocation_ok") and s.get("save_after_write", True):
        t_save = _time.time()
        _progress("guardando .zxst...")
        try:
            a.save_study()
            result["sim_params_saved"] = True
            write_lf_stamp(s, lf_cfg_id)
        except Exception as ex:
            result["save_error"] = str(ex)
            print("AVISO save_study:", ex)
        result["timing"]["save_sec"] = round(_time.time() - t_save, 2)

    if refresh_off:
        try:
            c.app.ActivateRefresh(True)
        except Exception:
            try:
                c.ActivateRefresh(True)
            except Exception:
                pass

    try:
        a.close_study(save=False)
    except Exception:
        pass

    # No reabrir Cyme por defecto (reopen GUI era 15-40s)
    resume_gui = bool(s.get("resume_gui_after_alloc"))
    if keep and resume_gui:
        try:
            import threading
            def _resume():
                try:
                    resume_cymdist_gui(s, reason="post_distribucion")
                except Exception as ex_gui:
                    print("AVISO resume GUI:", ex_gui)
            threading.Thread(target=_resume, name="resume_cyme_3_3", daemon=True).start()
            result["com"] = {"ok": True, "deferred": True}
        except Exception as ex:
            result["com_error"] = str(ex)
    else:
        result["com"] = {
            "ok": True,
            "skipped_resume": True,
            "reason": "rapidez_3_3_sin_reabrir_GUI",
            "cymdist_keep_open": keep,
        }

    result["timing"]["total_sec"] = round(_time.time() - t0, 2)
    out = output_path(s, "demand", "allocation_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    _progress("listo · %.1fs" % result["timing"]["total_sec"])
    print("OK 3.3", result["timing"], out)
    return result



def run_allocation(settings, session=None):
    """
    Distribucion de carga CYMDIST con ajustes fijos de la captura:
      - Modelo de carga: DEFAULT
      - Metodo: Consumo (kWh) = KWHMethod
      - Parametros flujo: DEFAULT
      - Demanda: Conectado + Total + kW-kvar = cabecera
      - Datos aguas abajo: energia (kWh) en las cargas

    Para la SPA §3.3 use run_load_allocation_module (solo API LoadAllocation.Run).
    """
    return _run_allocation_full(settings, session)


def _run_allocation_full(settings, session=None):
    """
    Distribucion completa (fijos + unlock + Run + validacion). Uso CLI / legacy.
    """
    s = settings
    api = load_json("config/cympy_api_map.json")
    sess = session or load_session(s)
    if sess.get("P_kW") in (None, ""):
        raise RuntimeError("Defina demanda de cabecera en la interfaz antes de distribuir.")

    Phead, Qhead = compute_head_pq(
        sess.get("mode"),
        sess.get("P_kW"),
        sess.get("Q_kvar"),
        sess.get("cosfi"),
    )
    fixed_cli = fixed_from_clientes(s)
    fixed = fixed_cli if fixed_cli else [
        r for r in (sess.get("fixed_loads") or []) if truthy(r.get("Activo", True))
    ]
    # Cargas nuevas §3: Locked, fuera del residual (no se redistribuyen)
    new_fixed = new_loads_as_fixed(s)
    new_ids = set(str(r["LoadID"]) for r in new_fixed)
    fixed_ids_cli = set(str(r.get("LoadID")) for r in fixed)
    # Evitar doble conteo si un LoadID apareciera en ambos
    new_fixed = [r for r in new_fixed if str(r["LoadID"]) not in fixed_ids_cli]
    Pfixed = sum(float(r["kW_Fijo"]) for r in fixed)
    Pnew = sum(float(r["kW_Fijo"]) for r in new_fixed)
    # Residual = cabecera - clientes fijos. Las nuevas NO restan: son demanda
    # proyectada adicional; solo se excluyen/bloquean del prorrateo.
    Pres = Phead - Pfixed
    if Pres < 0:
        raise RuntimeError(
            "Cargas fijas (%.1f kW) superan la medicion de cabecera (%.1f kW). "
            "En la interfaz §1 ingrese y guarde la medicion real (P/Q); "
            "no se altera la cabecera automaticamente."
            % (Pfixed, Phead)
        )
    q_res = Qhead * (Pres / Phead) if Phead else Qhead

    result = {
        "mode": sess.get("mode"),
        "P_cabecera_kW": Phead,
        "Q_cabecera_kvar": Qhead,
        "P_fijos_kW": Pfixed,
        "P_nuevas_kW": Pnew,
        "n_nuevas": len(new_fixed),
        "P_residual_kW": Pres,
        "Q_residual_kvar": q_res,
        "n_fijos": len(fixed),
        "fijos_fuente": "clientesimportantes" if fixed_cli else "session",
        "cymdist_settings": {
            "LoadModel": "DEFAULT",
            "Method": "KWHMethod",
            "Method_UI": "Consumo (kWh)",
            "DemandType": "FeederDemand",
            "LoadFlowParamConfigID": "DEFAULT",
            "Demand_Connected": True,
            "Demand_Total": True,
            "Demand_Unit": "kW-kvar",
            "Downstream_Unit": "Consumo (kWh)",
        },
        "applied": [],
        "scaled": [],
        "status": "ok",
    }
    if new_fixed:
        result["aviso_nuevas"] = (
            "Hay %d carga(s) nueva(s) del §3 (%.1f kW) Locked: no entran en "
            "distribucion. Tras conectarlas use Flujo situacional/proyectado."
            % (len(new_fixed), Pnew)
        )
    print("[%s] Distribucion de carga (Consumo kWh)" % s.get("feeder_id"))
    print("  Cabecera P/Q (demanda total):", Phead, "/", round(Qhead, 3))
    print("  Fijos (%s):" % result["fijos_fuente"], len(fixed), "->", round(Pfixed, 3), "kW")
    print("  Nuevas §3 (excluidas):", len(new_fixed), "->", round(Pnew, 3), "kW")
    print("  Residual esperado:", round(Pres, 3), "/", round(q_res, 3))

    if s.get("dry_run"):
        result["status"] = "dry_run"
        print("DRY_RUN distribucion", {k: result[k] for k in result if k not in ("scaled", "applied")})
        return result

    # Continua con el cuerpo completo historico (tras el comentario de sesion fisica)
    return _run_allocation_full_body(s, api, sess, fixed, new_fixed, new_ids, Phead, Qhead, Pres, q_res, result)


def _run_allocation_full_body(s, api, sess, fixed, new_fixed, new_ids, Phead, Qhead, Pres, q_res, result):
    """Cuerpo COM del camino completo (legacy)."""
    # Sesion fisica CYMDIST: pausar GUI para LoadAllocation exclusivo vía CymPy/API
    import time as _time
    t0 = _time.time()
    from core.cymdist_com import pause_cymdist_for_cympy, resume_cymdist_gui, is_keep_open
    keep = is_keep_open(s)
    if keep:
        pause_cymdist_for_cympy(s)
    result["timing"] = {"pause_gui_sec": round(_time.time() - t0, 2)}

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    t_open = _time.time()
    a.open_study()
    result["timing"]["open_study_sec"] = round(_time.time() - t_open, 2)
    net = str(s.get("network_id"))

    try:
        from core.sim_params import ensure_loadflow_networks, try_repair_loadflow_defaults
        ensure_loadflow_networks(c, net)
        repair = try_repair_loadflow_defaults(c)
        if repair.get("ok") and s.get("save_after_write", True):
            try:
                a.save_study()
                print("Parametros LF guardados en estudio (anti-130013)")
            except Exception as ex_save:
                print("AVISO save tras repair LF:", ex_save)
        try:
            from datetime import datetime
            sess = load_session(s)
            sess["lf_params_fixed_130013"] = True
            sess["lf_params_fixed_at"] = datetime.now().isoformat(timespec="seconds")
            sess["lf_params_config_id"] = repair.get("ConfigID") or "DEFAULT"
            save_session(s, sess)
        except Exception:
            pass
    except Exception as ex:
        print("AVISO sim_params:", ex)

    try:
        c.study.SelectLoadModel("DEFAULT")
        print("LoadModel: DEFAULT")
    except Exception as ex:
        print("AVISO SelectLoadModel DEFAULT:", ex)

    result["applied"] = apply_fixed_loads(a, fixed)
    # Asegurar Locked de cargas nuevas ANTES del Run / fallback
    if new_fixed:
        result["applied_nuevas"] = apply_fixed_loads(a, new_fixed)
        print("Nuevas §3 Locked (excluidas de residual):", [r["LoadID"] for r in new_fixed])

    # Fijos = Locked; resto Unlocked → Consumo(kWh) actualiza kW/kvar del residual
    fixed_ids = set(str(r.get("LoadID")) for r in fixed) | new_ids
    try:
        unlock_info = a.unlock_loads_except(net, fixed_ids)
        result["unlock"] = {
            "n_unlocked": len(unlock_info.get("unlocked") or []),
            "n_kept_locked": len(unlock_info.get("kept_locked") or []),
            "n_skipped": unlock_info.get("skipped_unchanged") or 0,
        }
        print(
            "Unlock residual:", result["unlock"]["n_unlocked"],
            "| Locked fijos/nuevas:", result["unlock"]["n_kept_locked"],
            "| sin cambio:", result["unlock"]["n_skipped"],
        )
    except Exception as ex:
        print("AVISO unlock residual:", ex)
        result["unlock_error"] = str(ex)

    # Sin snapshot pre-Run (~250 SpotLoad vía COM): solo LoadAllocation.Run
    result["residual_before"] = []

    allocated = False
    alloc_error = None
    method_used = None
    t_run = _time.time()
    try:
        from cympy.properties import properties as props
        from cympy.properties.CymeEnums import (
            _CymdistDataEnum_DemandTypeEnum as DemandTypeEnum,
            _CymdistDataEnum_LoadAllocationMethodEnum as MethodEnum,
        )
        lap = props.LoadAllocation()
        la = lap._cympyObject

        # Captura CYMDIST: Consumo (kWh), DEFAULT, FeederDemand
        try:
            lap.DemandType = DemandTypeEnum.FeederDemand
            lap.Method = MethodEnum.KWHMethod
            lap.LoadFlowParamConfigID = "DEFAULT"
            lap.RunVoltageDrop = False
            lap.UnlockAllLoads = False
            try:
                lap.Tolerance = 0.01
            except Exception:
                pass
        except Exception:
            la.SetValue("FeederDemand", "DemandType")
            la.SetValue("KWHMethod", "Method")
            try:
                la.SetValue("DEFAULT", "LoadFlowParamConfigID")
            except Exception:
                pass

        meter = c.study.Meter()
        meter.Connected = True
        meter.IsTotalDemand = True
        meter.LoadValueType = c.enums.LoadValueType.KW_KVAR
        meter.DemandTotal = c.study.LoadValue(float(Phead), float(Qhead))

        la.SetDemand(net, meter)
        print("SetDemand OK", net, "Connected+Total P=", Phead, "Q=", round(Qhead, 3), "Method=KWHMethod")
        la.Run([net])
        allocated = True
        method_used = "cymdist_LoadAllocation_KWH"
        print("LoadAllocation.Run OK (Consumo kWh) en %.2fs" % (_time.time() - t_run))
    except Exception as ex:
        alloc_error = str(ex)
        print("AVISO LoadAllocation:", alloc_error)
    result["timing"]["loadallocation_run_sec"] = round(_time.time() - t_run, 2)

    if not allocated:
        try:
            result["scaled"] = allocate_residual_by_kwh(
                a, net, fixed_ids, Pres, q_res
            )
            allocated = True
            method_used = "fallback_KWH"
            result["allocation_error"] = alloc_error
            result["aviso"] = (
                "CYMDIST LoadAllocation.Run fallo. "
                "Se aplico fallback equivalente a Consumo (kWh): peso=energia KWH, "
                "resultado escrito en kW/kvar; cargas con KWH<=0 quedan en 0 kW/kvar. "
                "Cargas nuevas §3 y clientes fijos se excluyen del prorrateo."
            )
        except Exception as ex_fb:
            result["status"] = "error"
            result["allocation_error"] = alloc_error
            result["fallback_error"] = str(ex_fb)
            print("ERROR fallback KWH:", ex_fb)
            out = output_path(s, "demand", "allocation_result.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            try:
                a.close_study(save=False)
            except Exception:
                pass
            if keep:
                try:
                    import threading
                    threading.Thread(
                        target=lambda: resume_cymdist_gui(s, reason="post_distribucion_error"),
                        name="resume_cyme_alloc_err",
                        daemon=True,
                    ).start()
                    result["com"] = {"ok": True, "deferred": True, "cymdist_open": True}
                except Exception:
                    pass
            return result
    else:
        # Nativo OK: no releer ~250 SpotLoad (el modulo ya escribio kW/kvar)
        result["scaled"] = []
        result["n_residual_kw_updated"] = None
        result["residual_note"] = (
            "Snapshot residual omitido (rapido). Verifique kW en CYMDIST tras LoadAllocation."
        )

    # No reaplicar fijos (ya Locked arriba / desde 3.2)
    if new_fixed:
        try:
            result["applied_nuevas"] = apply_fixed_loads(a, new_fixed)
        except Exception as ex:
            print("AVISO reaplica nuevas §3:", ex)
            result["reapply_nuevas_error"] = str(ex)

    # Validar EA -> Consumo(KWH) solo en clientes fijos (~11)
    try:
        from analysis.verify_clientes_precision import read_load_values, _f, _close
        kwh_checks = []
        path_cli = output_path(s, "clientes", "clientes_alimentador.json")
        if os.path.isfile(path_cli):
            with open(path_cli, "r", encoding="utf-8") as f:
                cli_rows = (json.load(f).get("rows") or [])
            for r in cli_rows:
                if not truthy(r.get("Activo", True)):
                    continue
                if r.get("Origen") == "inventario_spotload":
                    continue
                lid = r.get("LoadID_CYMDIST")
                ea = _f(r.get("EA"))
                if not lid or ea is None:
                    continue
                got = read_load_values(a, lid)
                ok = _close(got.get("KWH"), ea, max(0.5, abs(ea) * 1e-6))
                kwh_checks.append({
                    "LoadID": lid,
                    "SED": r.get("SED"),
                    "EA": ea,
                    "KWH_CYM": got.get("KWH"),
                    "KW_CYM": got.get("KW"),
                    "ok_consumo": ok,
                })
        result["consumo_validation"] = kwh_checks
        n_bad = sum(1 for x in kwh_checks if not x.get("ok_consumo"))
        result["consumo_ok"] = (n_bad == 0)
        if n_bad:
            print("AVISO Consumo(KWH) no coincide en", n_bad, "SED")
        else:
            print("Validacion Consumo(KWH): OK", len(kwh_checks), "SED")
    except Exception as ex:
        print("AVISO validacion consumo:", ex)
        result["consumo_validation_error"] = str(ex)

    if s.get("save_after_write", True):
        try:
            a.save_study()
        except Exception as ex:
            print("AVISO save_study:", ex)
            result["save_error"] = str(ex)

    try:
        a.close_study(save=False)
    except Exception:
        pass

    # Reabrir GUI en 2o plano (taskkill+OpenStudy no bloquea la UI)
    if keep:
        try:
            import threading
            def _resume():
                try:
                    resume_cymdist_gui(s, reason="post_distribucion")
                except Exception as ex_gui:
                    print("AVISO resume GUI diferido:", ex_gui)
            threading.Thread(target=_resume, name="resume_cyme_alloc", daemon=True).start()
            result["cymdist_open"] = True
            result["com"] = {"ok": True, "deferred": True, "cymdist_open": True}
        except Exception as ex:
            result["com_error"] = str(ex)

    result["timing"]["total_sec"] = round(_time.time() - t0, 2)
    print("Distribucion timing:", result["timing"])

    result["allocation_ok"] = True
    result["method"] = method_used
    result["status"] = "ok" if method_used and str(method_used).startswith("cymdist_") else "ok_fallback_kwh"

    out = output_path(s, "demand", "allocation_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    write_csv(
        output_path(s, "demand", "fixed_loads_applied.csv"),
        [{"LoadID": x["LoadID"], "kW": x["kW"], "kvar": x["kvar"]} for x in result["applied"]],
        ["LoadID", "kW", "kvar"],
    )
    if result["scaled"]:
        def _r4(v):
            try:
                return round(float(v), 4)
            except Exception:
                return v
        write_csv(
            output_path(s, "demand", "residual_scaled.csv"),
            [{"LoadID": x["LoadID"], "kW": _r4(x.get("kW")), "kvar": _r4(x.get("kvar")),
              "KWH": x.get("KWH"), "kW_before": _r4(x.get("kW_before"))}
             for x in result["scaled"]],
            ["LoadID", "kW", "kvar", "KWH", "kW_before"],
        )
    print("Residual:", Pres, "kW | method:", method_used, "| status:", result["status"])
    print(out)
    return result

def main():
    s = load_settings()
    # Prioridad: medicion guardada en UI (session). Excel solo si no hay P_kW.
    sess = seed_session_from_excel(s, force=False)
    result = run_allocation(s, sess)
    summary = {k: result[k] for k in result if k not in ("scaled", "applied")}
    summary["n_scaled"] = len(result.get("scaled") or [])
    summary["n_applied"] = len(result.get("applied") or [])
    print(summary)

if __name__ == "__main__":
    run_cympy_main(main)
