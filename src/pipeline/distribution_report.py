# -*- coding: utf-8 -*-
"""§3 · Reporte Excel de verificación de la distribución de carga (tras 3.3).

Una fila por carga (SED) del alimentador, vinculada a su cliente importante si
lo tiene. Columnas pedidas por operación:

    SED · Kw · Kvar · (kVA) · FP · kVA_instalado · Kw_actual · Kvar_actual ·
    FP_actual · accion · observaciones

Esperado (Kw/Kvar/kVA/FP):
  - Cliente importante incluido: Pot del Excel con el FP de 3.2 (fijo/Locked).
  - Cliente importante excluido: 0 (desconectado, no recibe carga).
  - Resto: parte proporcional a su consumo kWh del total distribuido, que es
    exactamente lo que hace el método Consumo (kWh) de CYMDIST.
Actual: valores leídos del estudio guardado después de 3.3.
"""
from __future__ import print_function

import math
import re

COLUMNS = [
    "SED", "Kw", "Kvar", "(kVA)", "FP", "kVA_instalado",
    "Kw_actual", "Kvar_actual", "FP_actual", "accion", "observaciones",
]

ACCION_CI = "Cliente importante · fijo (Locked)"
ACCION_EXCLUIDO = "Cliente importante excluido (Incluir off)"
ACCION_DISTRIBUIDO = "Distribuido por consumo (kWh)"
ACCION_SIN_CONSUMO = "Sin consumo kWh en la BD · no recibe carga"
ACCION_MEDIDOR = "Medidor de SED (carga en la SED)"


def meter_twin_sed(sed):
    """M20646 / M-21251 → SE20646 / SE21251 (medidor gemelo de la SED)."""
    text = str(sed or "").upper()
    if not text.startswith("M"):
        return None
    digits = text[1:].lstrip("-")
    return "SE" + digits if digits[:1].isdigit() else None

_LOAD_BASE = "CustomerLoads[0].CustomerLoadModels[0]"


def num(value):
    """Número CYMDIST/Excel (coma decimal) o None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text or text.startswith(("$", "ERR")):
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def sed_from_load_id(load_id):
    """DEV_2010_329293_SE20131 → SE20131 (sufijo SED del DeviceNumber)."""
    text = str(load_id or "").strip()
    match = re.search(r"_([A-Za-z]{1,4}-?\d+[A-Za-z0-9-]*)$", text)
    return match.group(1).upper() if match else text


def pf_of(kw, kvar):
    kva = math.hypot(kw or 0.0, kvar or 0.0)
    return (kw or 0.0) / kva if kva > 1e-9 else None


def kvar_from_pf(kw, pf):
    pf = max(0.01, min(1.0, float(pf)))
    return float(kw) * math.tan(math.acos(pf))


def read_feeder_loads(cympy, network_id, device_types=("SpotLoad",)):
    """Lee cada carga de la red: suma de fases, kWh, kVA instalado, estado.

    Las cargas pueden tener 1 valor ABC (tras 3.3) o 3 monofásicos (3.2);
    con LoadValue KW+PF el kvar se calcula (nunca se confunde PF con kvar).
    """
    rows = []
    for type_name in device_types:
        dtype = getattr(cympy.enums.DeviceType, type_name, None)
        if dtype is None:
            continue
        try:
            devices = list(cympy.study.ListDevices(dtype, network_id) or [])
        except Exception:
            devices = []
        rows.extend(_read_devices(devices, type_name))
    return rows


def _read_devices(devices, type_name):
    rows = []
    for device in devices:
        def get(field):
            try:
                return device.GetValue(field)
            except Exception:
                return None

        n_values = int(num(get(_LOAD_BASE + ".CustomerLoadValues.Count")) or 1)
        kw = kvar = kwh = kva_inst = 0.0
        for index in range(max(1, n_values)):
            base = "%s.CustomerLoadValues[%d]" % (_LOAD_BASE, index)
            p = num(get(base + ".LoadValue.KW")) or 0.0
            q = num(get(base + ".LoadValue.KVAR"))
            if q is None:
                pf = num(get(base + ".LoadValue.PF"))
                q = kvar_from_pf(p, pf / 100.0 if pf and pf > 1.0 else pf) if pf else 0.0
            kw += p
            kvar += q
            kwh += num(get(base + ".KWH")) or 0.0
            kva_inst += num(get(base + ".ConnectedKVA")) or 0.0
        rows.append({
            "LoadID": str(getattr(device, "DeviceNumber", "") or ""),
            "Tipo": type_name,
            "SectionID": str(getattr(device, "SectionID", "") or ""),
            "ZoneID": str(get("ZoneID") or ""),
            "LoadValueType": str(get(_LOAD_BASE + ".CustomerLoadValues[0].LoadValue.GetType()") or ""),
            "n_values": max(1, n_values),
            "kW": kw,
            "kvar": kvar,
            "kWh": kwh,
            "kVA_instalado": kva_inst,
            "locked": str(get(_LOAD_BASE + ".LockDuringLoadAllocation") or "").lower() == "locked",
            "connected": str(get("CustomerLoads[0].ConnectionStatus") or "Connected").lower() == "connected",
        })
    return rows


def _ci_by_load(clientes_rows):
    out = {}
    for row in clientes_rows or []:
        ids = str(row.get("LoadIDs_CYMDIST") or row.get("LoadID_CYMDIST") or "")
        for load_id in [x.strip() for x in re.split(r"[;,|]", ids) if x.strip()]:
            out.setdefault(load_id, []).append(row)
    return out


def build_distribution_report(loads, clientes_rows, cabecera=None, fp_ci=0.95,
                              tol_ci_pct=1.0, tol_dist_pct=2.0):
    """Filas del Excel + resumen. Función pura (testeable sin CYMDIST)."""
    cabecera = cabecera or {}
    ci_map = _ci_by_load(clientes_rows)
    ci_load_ids = set(ci_map)

    regular = [l for l in loads if l["LoadID"] not in ci_load_ids]
    sum_kwh_regular = sum(l["kWh"] for l in regular if l["connected"])
    dist_kw = sum(l["kW"] for l in regular if l["connected"])
    dist_kvar = sum(l["kvar"] for l in regular if l["connected"])

    kw_by_sed = {}
    for item in loads:
        sed_code = sed_from_load_id(item["LoadID"])
        kw_by_sed[sed_code] = kw_by_sed.get(sed_code, 0.0) + (item["kW"] if item["connected"] else 0.0)

    rows = []
    n_revisar = 0
    for load in sorted(loads, key=lambda l: sed_from_load_id(l["LoadID"])):
        twin = meter_twin_sed(sed_from_load_id(load["LoadID"]))
        obs = []
        clients = ci_map.get(load["LoadID"]) or []
        if clients:
            activo = any(c.get("Activo") is not False for c in clients)
            names = ", ".join(str(c.get("Cliente") or c.get("Suministro") or "") for c in clients)
            if activo:
                # Kw/Kvar mostrados = demanda real ya distribuida en CYMDIST (no
                # se calcula a partir de "Pot" del Excel EA/Pot: esa columna es
                # la potencia contratada, no la demanda, y no debe confundirse
                # con el valor real de la carga). "Pot" solo se usa para marcar
                # REVISAR si difiere mucho del valor real.
                pot_kw = sum(num(c.get("Pot")) or 0.0 for c in clients if c.get("Activo") is not False)
                exp_kw, exp_kvar = load["kW"], load["kvar"]
                accion = ACCION_CI
                if not load["locked"]:
                    obs.append("cliente importante sin Locked: LoadAllocation pudo modificarlo")
                if pot_kw > 1e-6:
                    delta_pot_pct = (load["kW"] - pot_kw) / pot_kw * 100.0
                    if abs(delta_pot_pct) > tol_ci_pct:
                        obs.insert(0, "Δ vs Pot contratada %+.2f %% (tol %.1f %%)" % (delta_pot_pct, tol_ci_pct))
                tol = tol_ci_pct
            else:
                exp_kw = exp_kvar = 0.0
                accion = ACCION_EXCLUIDO
                if load["connected"] and load["kW"] > 1e-6:
                    obs.append("excluido pero conectado con carga")
                tol = tol_ci_pct
            obs.append("cliente: %s" % names)
        elif not load["connected"]:
            exp_kw = exp_kvar = 0.0
            accion = "Desconectada"
            tol = tol_dist_pct
        elif load["kWh"] <= 0 and sed_from_load_id(load["LoadID"]).upper().startswith("M"):
            # Medidor (M...): normal que no tenga consumo propio (su carga
            # vive en la SED gemela SE...) · nunca se marca REVISAR por esto,
            # el problema real (si existe) se marca en la fila de esa SED.
            exp_kw = exp_kvar = 0.0
            accion = ACCION_MEDIDOR
            tol = tol_dist_pct
            if twin and twin not in kw_by_sed:
                obs.append("medidor: SED %s no existe en la red" % twin)
            elif twin and kw_by_sed[twin] <= 1e-6:
                obs.append("medidor: su SED %s tampoco tiene consumo en la BD" % twin)
            elif twin:
                obs.append("carga en %s" % twin)
            else:
                obs.append("medidor: sin SED gemela identificada")
        elif load["kWh"] <= 0:
            # SED (SE...): sí o sí debe tener consumo en la BD · se marca
            # REVISAR siempre para investigar por qué no consume carga.
            exp_kw = exp_kvar = 0.0
            accion = ACCION_SIN_CONSUMO
            tol = tol_dist_pct
            obs.append(
                "sin consumo kWh (KWHUsage vacío en la BD): el método Consumo (kWh) "
                "no le asigna carga · cargar su consumo o kW"
            )
        else:
            share = load["kWh"] / sum_kwh_regular if sum_kwh_regular > 0 else 0.0
            exp_kw = dist_kw * share
            exp_kvar = dist_kvar * share
            accion = ACCION_DISTRIBUIDO
            tol = tol_dist_pct

        exp_kva = math.hypot(exp_kw, exp_kvar)
        delta_pct = None
        if exp_kw > 1e-6:
            delta_pct = (load["kW"] - exp_kw) / exp_kw * 100.0
            if abs(delta_pct) > tol:
                obs.insert(0, "Δkw %+.2f %% (tol %.1f %%)" % (delta_pct, tol))
        elif load["kW"] > 1e-3 and accion != ACCION_EXCLUIDO:
            obs.insert(0, "tiene %.2f kW sin consumo/objetivo" % load["kW"])
        kva_actual = math.hypot(load["kW"], load["kvar"])
        if load["kVA_instalado"] > 0 and kva_actual > load["kVA_instalado"] * 1.0001:
            obs.append("sobrecarga: %.1f kVA > %.1f kVA instalado" % (kva_actual, load["kVA_instalado"]))

        problems = [
            o for o in obs
            if not o.startswith("cliente:") and not o.startswith("carga en ") and not o.startswith("medidor:")
        ]
        estado = "REVISAR" if problems else "OK"
        if problems:
            n_revisar += 1
        rows.append({
            "SED": sed_from_load_id(load["LoadID"]),
            "Kw": round(exp_kw, 3),
            "Kvar": round(exp_kvar, 3),
            "(kVA)": round(exp_kva, 3),
            "FP": round(pf_of(exp_kw, exp_kvar), 4) if exp_kva > 1e-9 else None,
            "kVA_instalado": round(load["kVA_instalado"], 3),
            "Kw_actual": round(load["kW"], 3),
            "Kvar_actual": round(load["kvar"], 3),
            "FP_actual": round(pf_of(load["kW"], load["kvar"]), 4) if kva_actual > 1e-9 else None,
            "accion": accion,
            "observaciones": " · ".join([estado] + obs + ["carga %s" % load["LoadID"]]),
        })

    ci_kw = sum(l["kW"] for l in loads if l["LoadID"] in ci_load_ids and l["connected"])
    total_kw = sum(l["kW"] for l in loads if l["connected"])
    total_kvar = sum(l["kvar"] for l in loads if l["connected"])
    p_cab = num(cabecera.get("P_kW"))
    q_cab = num(cabecera.get("Q_kvar"))
    summary = {
        "n_cargas": len(loads),
        "n_clientes_importantes": len(ci_load_ids & {l["LoadID"] for l in loads}),
        "n_revisar": n_revisar,
        "P_cabecera_kW": p_cab,
        "Q_cabecera_kvar": q_cab,
        "P_clientes_importantes_kW": round(ci_kw, 3),
        "P_distribuida_kW": round(dist_kw, 3),
        "P_total_cargas_kW": round(total_kw, 3),
        "Q_total_cargas_kvar": round(total_kvar, 3),
        "diferencia_cabecera_kW": round(p_cab - total_kw, 3) if p_cab is not None else None,
        "diferencia_cabecera_pct": (
            round((p_cab - total_kw) / p_cab * 100.0, 2) if p_cab else None
        ),
        "sed_sin_consumo": sorted(
            r["SED"] for r in rows if r["accion"] == ACCION_SIN_CONSUMO
        ),
        "clientes_sin_carga": sorted(
            str(r.get("Cliente") or r.get("Suministro"))
            for load_id, rs in ci_map.items()
            for r in rs
            if load_id not in {l["LoadID"] for l in loads}
        ),
    }
    return rows, summary


DIGSILENT_COLUMNS = [
    "SED", "P_kW", "Q_kvar", "S_kVA", "FP", "P_MW", "Q_Mvar",
    "kVA_instalado", "Conectada", "Cliente_importante", "Alimentador", "LoadID_CYMDIST",
]


def digsilent_rows(loads, clientes_rows, feeder_id=""):
    """Cargas balanceadas por código SED para actualizar/comprobar DIgSILENT.

    Valores actuales del estudio CYMDIST (tras 3.3). Si una SED tiene varias
    cargas se suman; P/Q también en MW/Mvar (unidades por defecto de ElmLod).
    """
    ci_map = _ci_by_load(clientes_rows)
    by_sed = {}
    for load in loads:
        sed = sed_from_load_id(load["LoadID"])
        row = by_sed.setdefault(sed, {
            "SED": sed, "P_kW": 0.0, "Q_kvar": 0.0, "kVA_instalado": 0.0,
            "Conectada": False, "clientes": [], "load_ids": [],
        })
        if load.get("connected", True):
            row["P_kW"] += load["kW"]
            row["Q_kvar"] += load["kvar"]
            row["Conectada"] = True
        row["kVA_instalado"] += load.get("kVA_instalado") or 0.0
        row["load_ids"].append(load["LoadID"])
        for client in ci_map.get(load["LoadID"]) or []:
            row["clientes"].append(str(client.get("Cliente") or client.get("Suministro") or ""))
    out = []
    for sed in sorted(by_sed):
        row = by_sed[sed]
        p, q = row["P_kW"], row["Q_kvar"]
        s = math.hypot(p, q)
        out.append({
            "SED": sed,
            "P_kW": round(p, 3),
            "Q_kvar": round(q, 3),
            "S_kVA": round(s, 3),
            "FP": round(pf_of(p, q), 4) if s > 1e-9 else None,
            "P_MW": round(p / 1000.0, 6),
            "Q_Mvar": round(q / 1000.0, 6),
            "kVA_instalado": round(row["kVA_instalado"], 3),
            "Conectada": "Sí" if row["Conectada"] else "No",
            "Cliente_importante": ", ".join(row["clientes"]),
            "Alimentador": feeder_id,
            "LoadID_CYMDIST": ", ".join(row["load_ids"]),
        })
    return out


def write_distribution_xlsx(path, rows, summary, feeder_id="", digsilent=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Distribucion"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    revisar = PatternFill("solid", fgColor="FDE2E1")
    for row in rows:
        ws.append([row.get(col) for col in COLUMNS])
        if str(row.get("observaciones") or "").startswith("REVISAR"):
            for cell in ws[ws.max_row]:
                cell.fill = revisar
    widths = [12, 11, 11, 11, 8, 13, 11, 11, 10, 38, 70]
    for index, width in enumerate(widths):
        ws.column_dimensions[chr(ord("A") + index)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    res = wb.create_sheet("Resumen")
    res.append(["Alimentador", feeder_id])
    labels = [
        ("n_cargas", "Cargas (SED) en la red"),
        ("n_clientes_importantes", "Clientes importantes vinculados"),
        ("n_revisar", "Filas a REVISAR"),
        ("P_cabecera_kW", "P cabecera (kW)"),
        ("Q_cabecera_kvar", "Q cabecera (kvar)"),
        ("P_clientes_importantes_kW", "Σ P clientes importantes (kW)"),
        ("P_distribuida_kW", "Σ P distribuida por kWh (kW)"),
        ("P_total_cargas_kW", "Σ P total cargas (kW)"),
        ("Q_total_cargas_kvar", "Σ Q total cargas (kvar)"),
        ("diferencia_cabecera_kW", "Cabecera − Σ cargas (kW) ≈ pérdidas"),
        ("diferencia_cabecera_pct", "Cabecera − Σ cargas (%)"),
    ]
    for key, label in labels:
        res.append([label, summary.get(key)])
    if summary.get("sed_sin_consumo"):
        res.append([
            "SED sin consumo en la BD (%d)" % len(summary["sed_sin_consumo"]),
            ", ".join(summary["sed_sin_consumo"]),
        ])
    if summary.get("clientes_sin_carga"):
        res.append(["Clientes importantes sin carga en la red", ", ".join(summary["clientes_sin_carga"])])
    res.column_dimensions["A"].width = 42
    res.column_dimensions["B"].width = 40

    if digsilent is not None:
        dg = wb.create_sheet("DIgSILENT")
        dg.append(DIGSILENT_COLUMNS)
        for cell in dg[1]:
            cell.font = Font(bold=True)
        for row in digsilent:
            dg.append([row.get(col) for col in DIGSILENT_COLUMNS])
        for index, width in enumerate([12, 11, 11, 11, 8, 11, 11, 13, 10, 30, 12, 40]):
            dg.column_dimensions[chr(ord("A") + index)].width = width
        dg.freeze_panes = "A2"
        dg.auto_filter.ref = dg.dimensions
    wb.save(path)
    return path
