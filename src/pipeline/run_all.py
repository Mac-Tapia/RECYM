from __future__ import print_function
import os, subprocess, sys
from core.common import resolve_python, truthy, load_json, is_cympy_exit_crash
from core.excel_io import read_kv
from core.feeder_context import load_settings, list_feeders, control_path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

STEP_MAP = {
    "validate_inputs": ("Validar entradas", "src/pipeline/validate_inputs.py"),
    "network_diagnostic": ("Diagnostico CYMDIST", "src/analysis/run_network_diagnostic.py"),
    "network_diagnostic_after": ("Diagnostico CYMDIST (post-correccion)", "src/analysis/run_network_diagnostic.py"),
    "build_corrections": ("Proponer correcciones", "src/pipeline/build_corrections_from_diagnostic.py"),
    "bulk_fix": ("Correccion masiva", "src/pipeline/bulk_fix.py"),
    "fix_base_voltages": ("Tensiones base 220052", "src/pipeline/fix_base_voltages.py"),
    "sync_equipment": ("Sync equipos Excel->CYMDIST", "src/pipeline/sync_equipment_from_excel.py"),
    "inventory_loads": ("Inventario de cargas", "src/pipeline/inventory_loads.py"),
    "build_clientes": ("Tabla clientes SED+EA/Pot", "src/pipeline/build_clientes_table.py"),
    "apply_clientes": ("Cargar EA/Pot en CYMDIST", "src/pipeline/apply_clientes_to_cymdist.py"),
    "verify_precision": ("Prueba precision EA/Pot", "src/analysis/verify_clientes_precision.py"),
    "demand_allocation": ("Distribucion demanda", "src/pipeline/run_demand_allocation.py"),
    "apply_fixed_large_customers": ("Clientes grandes fijos", "src/pipeline/apply_fixed_large_customers.py"),
    "load_allocation": ("Distribucion de carga", "src/pipeline/load_allocation.py"),
    "load_flow": ("Flujo de carga", "src/pipeline/run_load_flow.py"),
    "diagnose": ("Diagnostico tecnico", "src/analysis/diagnose_current.py"),
    "optimization_reclosers": ("Optimizar reconectadores", "src/optimization/optimize_reclosers.py"),
    "optimization_regulators": ("Optimizar reguladores", "src/optimization/optimize_regulators.py"),
    "optimization_capacitors": ("Optimizar capacitores", "src/optimization/optimize_capacitors.py"),
    "final_load_flow": ("Flujo final", "src/pipeline/run_load_flow.py"),
    "report": ("Reporte tablero", "src/analysis/build_dashboard.py"),
}

def _wants_all(argv):
    return "--all-feeders" in argv or "--all" in argv

def run_one(feeder_id, extra_args=None):
    s = load_settings(feeder_id=feeder_id)
    py = resolve_python(s)
    print("=" * 60, flush=True)
    print("Utility:", s.get("utility_name"), flush=True)
    print("Alimentador:", s["feeder_id"], "-", s.get("feeder_name"), flush=True)
    print("Python:", py, flush=True)
    print("dry_run:", s.get("dry_run"), flush=True)
    print("study_path:", s.get("study_path") or "(vacio)", flush=True)

    book = control_path(s)
    if not os.path.isfile(book):
        print("FALLO: no existe control workbook:", book, flush=True)
        return 1
    ctrl = read_kv(book, "Control_Proyecto")
    seq = list(s.get("run_sequence") or [])

    if not truthy(ctrl.get("Ejecutar_Flujo", True)):
        seq = [x for x in seq if x not in ("load_flow", "final_load_flow")]
    if not truthy(ctrl.get("Ejecutar_Opt_Recloser")):
        seq = [x for x in seq if x != "optimization_reclosers"]
    if not truthy(ctrl.get("Ejecutar_Opt_Regulador")):
        seq = [x for x in seq if x != "optimization_regulators"]
    if not truthy(ctrl.get("Ejecutar_Opt_Capacitor")):
        seq = [x for x in seq if x != "optimization_capacitors"]

    child_env = os.environ.copy()
    child_env["RECYM_FEEDER"] = feeder_id

    for key in seq:
        if key not in STEP_MAP:
            print("Paso desconocido en run_sequence:", key, flush=True)
            continue
        title, rel = STEP_MAP[key]
        print("\n===", title, "===", flush=True)
        cmd = [py, "-u", os.path.join(ROOT, rel.replace("/", os.sep)), "--feeder", feeder_id]
        env = dict(child_env)
        if key == "network_diagnostic_after":
            env["RECYM_DIAG_SUFFIX"] = "after"
            cmd.append("--suffix=after")
        rc = subprocess.call(cmd, cwd=ROOT, env=env)
        if rc != 0:
            # CymPy a menudo aborta al destruir COM tras éxito real (0xC0000005).
            if is_cympy_exit_crash(rc):
                print("AVISO: teardown CymPy (ACCESS_VIOLATION) tras", title,
                      "- se trata como OK si el paso genero salida.", flush=True)
                continue
            print("FALLO:", title, "rc=", rc, flush=True)
            if s.get("stop_on_error", True):
                return rc
    print("\nPIPELINE OK:", feeder_id, flush=True)
    return 0

def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    global_s = load_json("config/settings.json")

    if _wants_all(argv):
        feeders = list_feeders()
        if not feeders:
            print("No hay alimentadores en config/feeders/")
            raise SystemExit(1)
        print("Ejecutando todos los alimentadores:", ", ".join(feeders), flush=True)
        failed = []
        for fid in feeders:
            fc = load_json("config/feeders/%s.json" % fid)
            if fc.get("enabled") is False:
                print("Omitido (enabled=false):", fid, flush=True)
                continue
            rc = run_one(fid)
            if rc != 0:
                failed.append(fid)
                if global_s.get("stop_on_error", True):
                    raise SystemExit(rc)
        if failed:
            print("FALLARON:", ", ".join(failed), flush=True)
            raise SystemExit(1)
        print("\nTODOS LOS ALIMENTADORES TERMINADOS", flush=True)
        return

    # Un solo alimentador (active / --feeder / env)
    s = load_settings(argv=argv)
    rc = run_one(s["feeder_id"])
    raise SystemExit(rc)

if __name__ == "__main__":
    main()
