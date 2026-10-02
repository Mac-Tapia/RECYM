# -*- coding: utf-8 -*-
"""
§5.1b · Reportes CYMDIST (datos de entrada + flujo de carga) para el informe.

Ejecuta la seleccion de reportes guardada en CYMDIST con el nombre
RECYM_Informe (Barras/Cables/Cargas + Flujo de carga: Cargas, Lineas y
cables, Reporte sumario, Reporte sumario por red, Transformadores,
Transformadores en limites, Transformadores sobrecargados) y exporta el
resultado a un unico libro Excel.

No se conoce aun el nombre exacto del metodo COM/cympy que dispara el
dialogo "Reportes" de CYMDIST (no hay referencia en docs/cymdist ni uso
previo en este repo). Por eso esta primera version SOLO descubre e informa
la API real disponible (dir(app) / dir(cympy.study) filtrados por "report"),
sin inventar una llamada que podria fallar o dejar el estudio en un estado
raro. Cuando se confirme el nombre real del metodo, se reemplaza el
"intento best-effort" de abajo por la llamada correcta.
"""
from __future__ import print_function
import os
import uuid
from datetime import datetime

from core.common import mkdir

REPORT_SELECTION_NAME = "RECYM_Informe"

# Reportes esperados en la seleccion guardada (solo para verificar en el
# libro Excel final que no falto ninguno · no se usan para marcarlos, eso
# ya esta guardado en CYMDIST bajo REPORT_SELECTION_NAME).
EXPECTED_REPORTS = (
    "Barras",
    "Cables",
    "Cargas",
    "Flujo de carga - Cargas",
    "Flujo de carga - Lineas y cables",
    "Flujo de carga - Reporte sumario",
    "Flujo de carga - Reporte sumario por red",
    "Flujo de carga - Transformadores",
    "Flujo de carga - Transformadores en los limites de la toma",
    "Flujo de carga - Transformadores sobrecargados",
)


def _reports_dir(settings):
    out_base = settings.get("output_dir") or os.path.join(
        "data", "output", "feeders", str(settings.get("feeder_id") or "feeder")
    )
    if not os.path.isabs(out_base):
        from core.common import p
        return p(*(out_base.replace("\\", "/").split("/") + ["informe_reportes"]))
    return os.path.join(out_base, "informe_reportes")


def _discover_report_api(app):
    """Enumera miembros COM/cympy relacionados con 'report' (solo lectura)."""
    found = {"app_members": [], "cympy_study_members": [], "errors": []}
    try:
        found["app_members"] = sorted(
            m for m in dir(app) if "report" in m.lower()
        )
    except Exception as ex:
        found["errors"].append("dir(app): %s" % ex)
    try:
        from pipeline.capture_informe_color_views import _run_python_in_cyme
        script = (
            "import cympy\n"
            "_members = [m for m in dir(cympy.study) if 'report' in m.lower()]\n"
            "_log('study_report_members=' + ' | '.join(_members))\n"
            "_app_members = [m for m in dir(cympy) if 'report' in m.lower()]\n"
            "_log('cympy_report_members=' + ' | '.join(_app_members))\n"
        )
        _ok, notes, text = _run_python_in_cyme(app, script)
        found["in_process_notes"] = notes
        for line in (text or "").splitlines():
            if line.startswith("study_report_members="):
                val = line.split("=", 1)[1]
                found["cympy_study_members"] = [x for x in val.split(" | ") if x]
            elif line.startswith("cympy_report_members="):
                val = line.split("=", 1)[1]
                found["cympy_members"] = [x for x in val.split(" | ") if x]
    except Exception as ex:
        found["errors"].append("in_process discover: %s" % ex)
    return found


def _capture_color_views_for_scenario(settings, scenario):
    """Corre LoadFlow + coloreo nativo VoltageLevel/LoadingLevel para `scenario`.

    Reusa la misma rutina de 3.4 (backup/commit del estudio, verificacion de
    color real contra la escala ElectroDunas). En "proyectado" la carga nueva
    de §4 ya debe estar conectada (5.1 la conecta antes de correr el LF).
    """
    from pipeline.run_load_flow import run_load_flow
    from pipeline.capture_informe_color_views import capture_native_pair_with_restore

    run_id = "reportes-%s" % uuid.uuid4().hex
    lf = run_load_flow(dict(settings, skip_db_project_save=True), scenario=scenario)
    if lf.get("status") not in ("ok", "dry_run"):
        return {"ok": False, "error_code": "LOADFLOW_NOT_CONVERGED", "loadflow": lf}
    pair = capture_native_pair_with_restore(settings, scenario, run_id, force=True)
    pair["loadflow"] = lf
    return pair


def generate_reports(settings, selection_name=None, scenario="situacional", with_captures=None):
    """
    Intenta ejecutar la seleccion de reportes guardada y exportarla a Excel.

    scenario: "situacional" (sin carga nueva de §4 · boton en §3, alimenta el
    informe sin proyecto) | "proyectado" (con carga nueva §4 conectada · boton
    en §5.1b). Solo afecta el nombre del archivo de salida; CYMDIST reporta
    el estado del estudio tal como este en ese momento.

    with_captures (default: True solo para "proyectado"): ademas corre LF +
    captura nativa de VoltageLevel/LoadingLevel (coloreo) para ese escenario,
    igual que hace 3.4 para "situacional" — en "proyectado" esto evidencia el
    estado de tension/cargabilidad con la carga nueva ya conectada.

    Retorna dict con "ok", "discovery" (API real encontrada) y, si se logro
    disparar algun reporte, "xlsx_path". Mientras no se confirme el metodo
    COM real, "ok" queda en False con la info de descubrimiento para decidir
    el siguiente paso (ver docstring del modulo).
    """
    from core.cymdist_com import acquire_cymdist_app, sync_cymdist_binding

    name = str(selection_name or REPORT_SELECTION_NAME)
    scen = str(scenario or "situacional").strip().lower()
    if scen not in ("situacional", "proyectado"):
        scen = "situacional"
    if with_captures is None:
        with_captures = scen == "proyectado"

    captures = None
    if with_captures:
        captures = _capture_color_views_for_scenario(settings, scen)

    app, mode = acquire_cymdist_app(settings, show_window=True)
    try:
        sync_cymdist_binding(app, settings, save_before=False, register_db=True)
    except Exception as ex:
        print("AVISO sync antes de reportes:", ex)

    discovery = _discover_report_api(app)

    out_dir = _reports_dir(settings)
    mkdir(out_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, "reportes_cymdist_%s_%s.xlsx" % (scen, stamp))

    return {
        "ok": False,
        "error_code": "REPORT_API_NOT_CONFIRMED",
        "error": (
            "No se encontro aun el metodo COM/cympy real para disparar la "
            "seleccion de reportes '%s'. Revise discovery.app_members / "
            "discovery.cympy_study_members abajo para identificarlo." % name
        ),
        "selection_name": name,
        "scenario": scen,
        "app_mode": mode,
        "discovery": discovery,
        "expected_reports": list(EXPECTED_REPORTS),
        "xlsx_target": out_path,
        "captures": captures,
    }
