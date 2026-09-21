from __future__ import print_function
"""
Contexto multi-alimentador para Electro Dunas / RECYM.

Uso:
  - settings.json define utility + active_feeder + rutas globales de estudios/BD
  - config/feeders/<ID>.json define datos por alimentador
  - Override: variable de entorno RECYM_FEEDER o --feeder ID

Rutas Electro Dunas:
  studies_root = D:\\BaseDatosElectroDunas\\260919BaseDatos
  projects_dir = ...\\proyectos          (archivos .zxst)
  database_dir = ...\\202603             (archivos .mdb)
"""
import os
import sys
import copy
from core.common import load_json, save_json, p, mkdir

def _parse_feeder_arg(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    for i, a in enumerate(argv):
        if a == "--feeder" and i + 1 < len(argv):
            return argv[i + 1].strip()
        if a.startswith("--feeder="):
            return a.split("=", 1)[1].strip()
    return None

def list_feeders():
    root = p("config", "feeders")
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".json") and not name.startswith("_"):
            out.append(name[:-5])
    return out

def list_study_files(settings=None):
    """Lista .zxst en projects_dir (estudios disponibles en disco)."""
    if settings is None:
        settings = load_json("config/settings.json")
    proj = settings.get("projects_dir") or ""
    if not proj or not os.path.isdir(proj):
        return []
    return sorted([f for f in os.listdir(proj) if f.lower().endswith((".zxst", ".sxst"))])

def feeder_config_path(feeder_id):
    return p("config", "feeders", feeder_id + ".json")

def load_feeder_config(feeder_id):
    path = feeder_config_path(feeder_id)
    if not os.path.isfile(path):
        raise RuntimeError(
            "No existe config del alimentador '%s'. Esperado: %s. Disponibles: %s"
            % (feeder_id, path, ", ".join(list_feeders()) or "(ninguno)")
        )
    return load_json("config/feeders/%s.json" % feeder_id)

def resolve_feeder_id(cli_feeder=None, settings=None):
    if cli_feeder:
        return cli_feeder
    env = os.environ.get("RECYM_FEEDER") or os.environ.get("FEEDER")
    if env:
        return env.strip()
    if settings is None:
        settings = load_json("config/settings.json")
    fid = settings.get("active_feeder")
    if not fid:
        raise RuntimeError("Defina active_feeder en config/settings.json o use --feeder ID")
    return fid

def _default_paths(feeder_id):
    base = os.path.join("data", "input", "feeders", feeder_id)
    return {
        "control_workbook": os.path.join(base, "Control_Simulacion.xlsx"),
        "catalog_workbook": os.path.join(base, "Catalogo_Maestro.xlsx"),
        "output_dir": os.path.join("data", "output", "feeders", feeder_id),
    }

def resolve_study_path(merged, feeder):
    """Prioridad: study_path absoluto > projects_dir + study_file > projects_dir + <ID>.zxst."""
    sp = (merged.get("study_path") or "").strip()
    if sp and os.path.isfile(sp):
        return sp
    projects = (merged.get("projects_dir") or "").strip()
    study_file = (feeder.get("study_file") or merged.get("study_file") or "").strip()
    if not study_file:
        study_file = merged.get("feeder_id", "") + ".zxst"
    if projects and study_file:
        cand = os.path.join(projects, study_file)
        if os.path.isfile(cand):
            return cand
        alt = os.path.splitext(cand)[0] + ".sxst"
        if os.path.isfile(alt):
            return alt
    return sp

def load_settings(feeder_id=None, argv=None):
    """Fusiona settings globales + config del alimentador activo."""
    global_s = load_json("config/settings.json")
    fid = resolve_feeder_id(_parse_feeder_arg(argv) if feeder_id is None else feeder_id, global_s)
    feeder = load_feeder_config(fid)
    merged = copy.deepcopy(global_s)
    for k, v in _default_paths(fid).items():
        merged.setdefault(k, v)
    for k, v in feeder.items():
        if k.startswith("_"):
            continue
        merged[k] = v
    defaults = _default_paths(fid)
    for k, v in defaults.items():
        if not merged.get(k):
            merged[k] = v
    merged["feeder_id"] = fid
    merged["feeder_name"] = feeder.get("name") or fid
    merged["utility_name"] = global_s.get("utility_name") or "Electro Dunas"
    resolved = resolve_study_path(merged, feeder)
    if resolved:
        merged["study_path"] = resolved
    return merged

def ensure_feeder_dirs(settings):
    mkdir(p(*settings["output_dir"].split("\\") if "\\" in settings["output_dir"] else settings["output_dir"].split("/")))
    preview = os.path.join(settings["output_dir"], "preview_changes.csv")
    diag = os.path.join(settings["output_dir"], "diagnostics")
    mkdir(p(*diag.replace("\\", "/").split("/")) if not os.path.isabs(diag) else diag)
    return preview

def output_path(settings, *parts):
    base = settings.get("output_dir") or os.path.join("data", "output", "feeders", settings.get("feeder_id", "UNKNOWN"))
    rel = os.path.join(base, *parts)
    full = rel if os.path.isabs(rel) else p(*rel.replace("\\", "/").split("/"))
    mkdir(os.path.dirname(full))
    return full

def control_path(settings):
    rel = settings["control_workbook"]
    return rel if os.path.isabs(rel) else p(*rel.replace("\\", "/").split("/"))

def catalog_path(settings):
    rel = settings["catalog_workbook"]
    return rel if os.path.isabs(rel) else p(*rel.replace("\\", "/").split("/"))

def create_feeder_from_template(feeder_id, name=None, network_id="", study_path="", study_file="", voltage_kv=22.9):
    """Crea config + carpetas de un alimentador nuevo a partir de _TEMPLATE."""
    if feeder_id in list_feeders():
        raise RuntimeError("El alimentador ya existe: " + feeder_id)
    tmpl = load_json("config/feeders/_TEMPLATE.json")
    data = copy.deepcopy(tmpl)
    data["name"] = name or feeder_id
    data["network_id"] = network_id or ("NET_" + feeder_id)
    data["study_file"] = study_file or (feeder_id + ".zxst")
    data["study_path"] = study_path
    data["voltage_ll_kv"] = voltage_kv
    data.pop("_comment", None)
    save_json("config/feeders/%s.json" % feeder_id, data)
    dest = p("data", "input", "feeders", feeder_id)
    mkdir(dest)
    mkdir(p("data", "output", "feeders", feeder_id, "diagnostics"))
    src_dir = p("data", "input", "feeders", "_TEMPLATE")
    for fname in ("Control_Simulacion.xlsx", "Catalogo_Maestro.xlsx"):
        src = os.path.join(src_dir, fname)
        if os.path.isfile(src):
            import shutil
            shutil.copy2(src, os.path.join(dest, fname))
    return feeder_config_path(feeder_id)
