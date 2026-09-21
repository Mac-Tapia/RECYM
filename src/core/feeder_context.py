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
    """Lista estudios (.zxst/.sxst/.zsxst) en projects_dir (y studies_root si aplica)."""
    if settings is None:
        settings = load_json("config/settings.json")
    dirs = []
    for key in ("projects_dir", "studies_root"):
        d = (settings.get(key) or "").strip()
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    out = []
    seen = set()
    for root in dirs:
        try:
            names = os.listdir(root)
        except Exception:
            continue
        for name in sorted(names):
            low = name.lower()
            if not low.endswith((".zxst", ".sxst", ".zsxst")):
                continue
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "path": full, "dir": root})
    return out


def list_database_files(settings=None):
    """Lista bases .mdb en database_dir (y projects_dir / studies_root por si están juntas)."""
    if settings is None:
        settings = load_json("config/settings.json")
    dirs = []
    for key in ("database_dir", "projects_dir", "studies_root"):
        d = (settings.get(key) or "").strip()
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    out = []
    seen = set()
    for root in dirs:
        try:
            names = os.listdir(root)
        except Exception:
            continue
        for name in sorted(names):
            low = name.lower()
            if not low.endswith(".mdb"):
                continue
            full = os.path.join(root, name)
            if not os.path.isfile(full):
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            stem = os.path.splitext(name)[0]
            out.append({
                "name": name,
                "path": full,
                "dir": root,
                "connection_name": stem,
            })
    return out


def apply_context_selection(database_mdb=None, study_path=None, feeder_id=None, persist=True):
    """Aplica BD y/o estudio elegidos en la UI al settings (y alimentador del estudio).

    Si el estudio es IN112.zxst → active_feeder=IN112 y study_path de ese feeder.
    Así «Guardar medición cabecera» escribe en ese estudio/alimentador.
    """
    global_s = load_json("config/settings.json")
    changed = []
    resolved_feeder = (feeder_id or "").strip() or None

    if database_mdb:
        mdb = str(database_mdb).strip()
        if not os.path.isfile(mdb):
            raise RuntimeError("Base de datos no encontrada: %s" % mdb)
        global_s["database_mdb"] = mdb
        global_s["database_dir"] = os.path.dirname(mdb)
        global_s["database_connection_name"] = os.path.splitext(os.path.basename(mdb))[0]
        changed.append("database_mdb")

    if study_path:
        sp = str(study_path).strip()
        if not os.path.isfile(sp):
            raise RuntimeError("Estudio/proyecto no encontrado: %s" % sp)
        global_s["ui_study_path"] = sp
        global_s["ui_study_file"] = os.path.basename(sp)
        stem = os.path.splitext(os.path.basename(sp))[0]
        # El alimentador lo define el estudio (IN112.zxst → IN112), no el default PA217.
        if stem and stem.upper() != "ELD":
            resolved_feeder = stem
            global_s["active_feeder"] = stem
            changed.append("active_feeder:%s" % stem)
        elif stem.upper() == "ELD":
            global_s["eld_study_path"] = sp
            changed.append("eld_study_path")
            if not resolved_feeder:
                resolved_feeder = (global_s.get("active_feeder") or "").strip() or None

        fid = (resolved_feeder or global_s.get("active_feeder") or stem or "").strip()
        if fid and fid.upper() != "ELD":
            # Crear/actualizar config del alimentador con este estudio
            if os.path.isfile(feeder_config_path(fid)):
                fc = load_feeder_config(fid)
            else:
                fc = synthesize_feeder_config(fid, persist=False, global_s=global_s)
            fc["study_file"] = os.path.basename(sp)
            fc["study_path"] = sp
            if persist:
                save_json("config/feeders/%s.json" % fid, fc)
                mkdir(p("data", "output", "feeders", fid, "demand"))
            changed.append("feeder_study:%s" % fid)
        changed.append("ui_study_path")

    if persist and changed:
        save_json("config/settings.json", global_s)

    # Resolver settings efectivos del alimentador activo
    fid_out = resolved_feeder or global_s.get("active_feeder")
    try:
        effective = load_settings(feeder_id=fid_out, synthesize=True) if fid_out else load_settings()
    except Exception:
        effective = global_s

    return {
        "ok": True,
        "changed": changed,
        "database_mdb": global_s.get("database_mdb"),
        "database_connection_name": global_s.get("database_connection_name"),
        "study_path": effective.get("study_path") or global_s.get("ui_study_path"),
        "study_file": global_s.get("ui_study_file") or os.path.basename(effective.get("study_path") or ""),
        "active_feeder": fid_out or global_s.get("active_feeder"),
        "feeder_id": effective.get("feeder_id") or fid_out,
        "network_id": effective.get("network_id"),
    }


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


def synthesize_feeder_config(feeder_id, network_id=None, persist=False, global_s=None):
    """Config efímera (o persistida) para redes de BD sin config/feeders/<ID>.json.

    Prioridad de estudio: <ID>.zxst → <ID>.sxst → eld_study_path / ELD.zxst.
    """
    fid = str(feeder_id or "").strip()
    if not fid:
        raise RuntimeError("feeder_id vacío para sintetizar config")
    global_s = global_s or load_json("config/settings.json")
    projects = (global_s.get("projects_dir") or "").strip()
    study_file = fid + ".zxst"
    study_path = ""
    candidates = []
    if projects:
        candidates.extend([
            os.path.join(projects, fid + ".zxst"),
            os.path.join(projects, fid + ".sxst"),
        ])
    eld = (global_s.get("eld_study_path") or "").strip()
    if eld:
        candidates.append(eld)
    elif projects:
        candidates.append(os.path.join(projects, "ELD.zxst"))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            study_path = cand
            study_file = os.path.basename(cand)
            break
    nid = str(network_id or "").strip()
    if not nid:
        nid = "NET_" + fid
    data = {
        "name": fid,
        "description": "Auto desde BD/estudio (sin config/feeders previa)",
        "network_id": nid,
        "study_file": study_file,
        "study_path": study_path,
        "voltage_ll_kv": float(global_s.get("default_voltage_ll_kv") or 22.9),
        "region": "",
        "substation": "",
        "enabled": True,
        "control_workbook": "",
        "catalog_workbook": "",
        "output_dir": "",
        "notes": "Sintetizado automáticamente para diagnóstico de red BD",
        "synthesized": True,
    }
    if persist:
        save_json("config/feeders/%s.json" % fid, data)
        mkdir(p("data", "output", "feeders", fid, "diagnostics"))
    return data

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

def load_settings(feeder_id=None, argv=None, network_id=None, synthesize=True, persist_synth=True):
    """Fusiona settings globales + config del alimentador activo.

    Si no hay config/feeders/<ID>.json y synthesize=True, construye una desde el
    estudio en projects_dir / ELD (útil para diagnosticar los ~96 de la BD).
    network_id opcional: fuerza NET_* cuando viene del selector UI.
    """
    global_s = load_json("config/settings.json")
    fid = resolve_feeder_id(_parse_feeder_arg(argv) if feeder_id is None else feeder_id, global_s)
    path = feeder_config_path(fid)
    synthesized = False
    if os.path.isfile(path):
        feeder = load_feeder_config(fid)
    elif synthesize:
        feeder = synthesize_feeder_config(
            fid, network_id=network_id, persist=bool(persist_synth), global_s=global_s
        )
        synthesized = True
    else:
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
    if network_id:
        merged["network_id"] = str(network_id).strip()
    merged["feeder_id"] = fid
    merged["feeder_name"] = feeder.get("name") or fid
    merged["utility_name"] = global_s.get("utility_name") or "Electro Dunas"
    merged["config_synthesized"] = synthesized or bool(feeder.get("synthesized"))
    resolved = resolve_study_path(merged, feeder)
    # Override UI: estudio elegido en §1 (si existe en disco)
    ui_sp = (global_s.get("ui_study_path") or "").strip()
    if ui_sp and os.path.isfile(ui_sp):
        merged["study_path"] = ui_sp
        merged["study_file"] = os.path.basename(ui_sp)
    elif resolved:
        merged["study_path"] = resolved
    if not merged.get("study_path"):
        # Último recurso: estudio ELD compartido (redes cargadas desde MDB)
        eld = (global_s.get("eld_study_path") or "").strip()
        if eld and os.path.isfile(eld):
            merged["study_path"] = eld
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
