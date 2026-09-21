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
    Escribe demanda en CYMDIST = Propiedades de la red > Demanda:
    Ingresar demanda + Conectado + Total + tipo kW-kvar → casilleros (P, Q).
    """
    from cympy.properties import properties as props

    net = str(network_id)
    p_kw = float(p_kw)
    q_kvar = float(q_kvar)
    lap = props.LoadAllocation()
    la = lap._cympyObject
    meter = cympy.study.Meter()
    meter.Connected = True
    meter.IsTotalDemand = True
    meter.LoadValueType = cympy.enums.LoadValueType.KW_KVAR
    meter.DemandTotal = cympy.study.LoadValue(p_kw, q_kvar)
    la.SetDemand(net, meter)
    return {
        "network_id": net,
        "P_kW": p_kw,
        "Q_kvar": q_kvar,
        "Connected": True,
        "Total": True,
        "Tipo": "kW-kvar",
    }

def sync_control_excel_cabecera(settings, p_kw, q_kvar, cosfi=None, fecha=None):
    """Refleja medicion UI en Control_Simulacion (misma fuente unica de cabecera)."""
    book = control_path(settings)
    if not os.path.isfile(book):
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

def apply_cabecera_medicion(settings, p_kw, q_kvar, save=True):
    """Abre estudio, escribe casilleros Demanda CYMDIST y guarda."""
    api = load_json("config/cympy_api_map.json")
    c = require_cympy(settings)
    a = CymPyAdapter(c, api, settings)
    a.open_study()
    info = set_network_demand(c, settings.get("network_id"), p_kw, q_kvar)
    if save and settings.get("save_after_fix", True):
        a.save_study()
        info["saved"] = True
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
        })
    return fixed

def run_allocation(settings, session=None):
    """
    Distribucion de carga CYMDIST con ajustes fijos de la captura:
      - Modelo de carga: DEFAULT
      - Metodo: Consumo (kWh) = KWHMethod
      - Parametros flujo: DEFAULT
      - Demanda: Conectado + Total + kW-kvar = cabecera
      - Datos aguas abajo: energia (kWh) en las cargas
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

    # Sesion fisica CYMDIST: pausar GUI para LoadAllocation exclusivo vía CymPy/API
    from core.cymdist_com import pause_cymdist_for_cympy, resume_cymdist_gui, is_keep_open
    keep = is_keep_open(s)
    if keep:
        pause_cymdist_for_cympy(s)

    c = require_cympy(s)
    a = CymPyAdapter(c, api, s)
    a.open_study()
    net = str(s.get("network_id"))

    try:
        from core.sim_params import ensure_loadflow_networks, try_repair_loadflow_defaults
        ensure_loadflow_networks(c, net)
        try_repair_loadflow_defaults(c)
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
        }
        print(
            "Unlock residual:", result["unlock"]["n_unlocked"],
            "| Locked fijos/nuevas:", result["unlock"]["n_kept_locked"],
        )
    except Exception as ex:
        print("AVISO unlock residual:", ex)
        result["unlock_error"] = str(ex)

    try:
        result["residual_before"] = a.snapshot_spot_loads_pq_kwh(net, exclude_ids=fixed_ids)
    except Exception as ex:
        print("AVISO snapshot before:", ex)
        result["residual_before"] = []

    allocated = False
    alloc_error = None
    method_used = None
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
        print("LoadAllocation.Run OK (Consumo kWh)")
    except Exception as ex:
        alloc_error = str(ex)
        print("AVISO LoadAllocation:", alloc_error)

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
                    result["com"] = resume_cymdist_gui(s, reason="post_distribucion_error")
                except Exception:
                    pass
            return result
    elif method_used == "cymdist_LoadAllocation_KWH":
        # Nativo OK: releer residual — CYMDIST actualizo kW/kvar segun Consumo
        try:
            after = a.snapshot_spot_loads_pq_kwh(net, exclude_ids=fixed_ids)
            before_map = {
                str(x["LoadID"]): x for x in (result.get("residual_before") or [])
            }
            scaled = []
            for row in after:
                lid = row["LoadID"]
                prev = before_map.get(lid) or {}
                scaled.append({
                    "LoadID": lid,
                    "kW": row.get("kW"),
                    "kvar": row.get("kvar"),
                    "KWH": row.get("KWH"),
                    "kW_before": prev.get("kW"),
                    "kvar_before": prev.get("kvar"),
                    "weight": "KWH",
                })
            result["scaled"] = scaled
            result["residual_after"] = after
            n_changed = sum(
                1 for x in scaled
                if x.get("kW") is not None and x.get("kW_before") is not None
                and abs(float(x["kW"]) - float(x["kW_before"])) > 0.01
            )
            result["n_residual_kw_updated"] = n_changed
            print(
                "Residual post-Run: %d cargas, %d con kW actualizado"
                % (len(scaled), n_changed)
            )
        except Exception as ex:
            print("AVISO snapshot after:", ex)
            if not result.get("scaled"):
                result["scaled"] = []

    try:
        result["applied"] = apply_fixed_loads(a, fixed)
    except Exception as ex:
        print("AVISO reaplica fijos:", ex)
        result["reapply_error"] = str(ex)
    # Reaplicar P/Q de cargas nuevas (nunca deben quedar en 0 por el fallback)
    if new_fixed:
        try:
            result["applied_nuevas"] = apply_fixed_loads(a, new_fixed)
        except Exception as ex:
            print("AVISO reaplica nuevas §3:", ex)
            result["reapply_nuevas_error"] = str(ex)

    # Validar EA → Consumo(KWH) intacto en clientes fijos tras la corrida
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

    if s.get("save_after_fix", True):
        try:
            a.save_study()
        except Exception as ex:
            print("AVISO save_study:", ex)
            result["save_error"] = str(ex)

    try:
        a.close_study(save=False)
    except Exception:
        pass

    # Reabrir CYMDIST visible tras distribución (sesion §§2–5)
    if keep:
        try:
            com = resume_cymdist_gui(s, reason="post_distribucion")
            result["cymdist_open"] = bool(com.get("cymdist_open"))
            result["com"] = com
        except Exception as ex:
            result["com_error"] = str(ex)

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
