from __future__ import print_function

import os

from core.common import truthy
from core.excel_io import read_kv, read_rows
from core.feeder_context import catalog_path, control_path, load_settings


def _issue(code, message, **details):
    row = {"code": code, "message": message}
    row.update(details)
    return row


def inspect_feeder_inputs(settings):
    """Valida archivos e identidad sin escribir ni abrir CYMDIST."""
    s = settings or {}
    book = control_path(s)
    catalog = catalog_path(s)
    errors = []
    warnings = []
    ctrl = {}
    clients = []
    fixes = []

    if not os.path.isfile(book):
        errors.append(_issue(
            "CONTROL_WORKBOOK_MISSING",
            "No existe Control_Simulacion.xlsx",
            path=book,
        ))
    else:
        try:
            ctrl = read_kv(book, "Control_Proyecto") or {}
        except Exception as ex:
            errors.append(_issue(
                "CONTROL_WORKBOOK_INVALID",
                "No se pudo leer Control_Proyecto: %s" % ex,
                path=book,
            ))

    if not os.path.isfile(catalog):
        errors.append(_issue(
            "CATALOG_WORKBOOK_MISSING",
            "No existe Catalogo_Maestro.xlsx",
            path=catalog,
        ))

    required = ["NetworkID", "Tension_MT_LL", "Demanda_Max_Cabecera_kW", "Escenario_Base"]
    missing = [name for name in required if ctrl.get(name) in (None, "")]
    if ctrl and missing:
        errors.append(_issue(
            "CONTROL_REQUIRED_FIELDS_MISSING",
            "Faltan campos en Control_Proyecto: %s" % ", ".join(missing),
            fields=missing,
        ))

    network_config = str(s.get("network_id") or "").strip()
    network_excel = str(ctrl.get("NetworkID") or "").strip()
    if network_config and network_excel and network_config != network_excel:
        errors.append(_issue(
            "NETWORK_ID_MISMATCH",
            "NetworkID Excel (%s) != configuración (%s)" % (
                network_excel, network_config
            ),
            network_id_excel=network_excel,
            network_id_config=network_config,
        ))

    if os.path.isfile(book) and ctrl:
        try:
            clients = [r for r in read_rows(book, "Clientes_Grandes") if truthy(r.get("Activo"))]
            for row in clients:
                if not row.get("LoadID") or row.get("kW_Fijo") in (None, ""):
                    errors.append(_issue(
                        "LARGE_CUSTOMER_INCOMPLETE",
                        "Cliente grande sin LoadID o kW_Fijo",
                        load_id=row.get("LoadID"),
                    ))
                if row.get("kvar_Fijo") in (None, "") and row.get("FP") in (None, ""):
                    errors.append(_issue(
                        "LARGE_CUSTOMER_REACTIVE_MISSING",
                        "Cliente grande sin kvar_Fijo ni FP",
                        load_id=row.get("LoadID"),
                    ))
        except Exception as ex:
            errors.append(_issue(
                "LARGE_CUSTOMERS_INVALID",
                "No se pudo leer Clientes_Grandes: %s" % ex,
                path=book,
            ))

    if os.path.isfile(catalog):
        try:
            fixes = [r for r in read_rows(catalog, "Correcciones") if truthy(r.get("Activo"))]
        except Exception as ex:
            errors.append(_issue(
                "CATALOG_CORRECTIONS_INVALID",
                "No se pudo leer Correcciones: %s" % ex,
                path=catalog,
            ))

    return {
        "ok": not errors,
        "inputs_ready": not errors,
        "feeder_id": s.get("feeder_id"),
        "network_id_config": network_config,
        "network_id_excel": network_excel,
        "control_workbook": book,
        "catalog_workbook": catalog,
        "control_exists": os.path.isfile(book),
        "catalog_exists": os.path.isfile(catalog),
        "errors": errors,
        "warnings": warnings,
        "n_clients_active": len(clients),
        "n_corrections_active": len(fixes),
        "control": ctrl,
    }


def main():
    s = load_settings()
    result = inspect_feeder_inputs(s)
    ctrl = result.get("control") or {}

    print("Utility:", s.get("utility_name"))
    print("Alimentador:", s.get("feeder_id"), "-", s.get("feeder_name"))
    for issue in result.get("errors") or []:
        print("ERROR %s: %s" % (issue.get("code"), issue.get("message")))
    if not result.get("ok"):
        raise SystemExit(1)

    print("VALIDACION OK")
    print("NetworkID:", ctrl.get("NetworkID"))
    print("Demanda cabecera kW:", ctrl.get("Demanda_Max_Cabecera_kW"))
    print("Clientes grandes activos:", result.get("n_clients_active"))
    print("Correcciones activas:", result.get("n_corrections_active"))
    print("dry_run:", s.get("dry_run"))
    print("study_path:", s.get("study_path") or "(pendiente para WRITE)")
    return result


if __name__ == "__main__":
    main()
