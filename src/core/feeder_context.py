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
import re
from core.common import load_json, save_json, p, mkdir

# Estudio .zxst vacío o corrupto (p.ej. 0 bytes) no es usable por CYMDIST.
_MIN_STUDY_BYTES = 1024


def is_usable_study_file(path, min_bytes=None):
    """True si el .zxst/.sxst existe y tiene tamaño mínimo (no vacío/corrupto)."""
    if not path or not os.path.isfile(path):
        return False
    try:
        sz = os.path.getsize(path)
    except Exception:
        return False
    need = _MIN_STUDY_BYTES if min_bytes is None else int(min_bytes)
    return sz >= need


def feeder_family_code(fid):
    """PA217V2 / PA217_ALT → PA217."""
    u = str(fid or "").strip().upper()
    if not u:
        return ""
    m = re.match(r"^([A-Z]{1,3}\d{2,4})", u)
    return m.group(1) if m else u


def list_study_open_candidates(path, settings=None):
    """Candidatos para study.Open: path pedido y .zxst de la misma familia.

    CYMDIST/CymPy a menudo no abre .xst legacy; se prueba .zxst hermano.
    """
    settings = settings or {}
    projects = (
        (settings.get("projects_dir") or "").strip()
        or (os.path.dirname(path) if path else "")
    )
    out = []
    seen = set()

    def _add(p):
        if not p:
            return
        try:
            ap = os.path.normcase(os.path.abspath(p))
        except Exception:
            ap = p
        if ap in seen:
            return
        if is_usable_study_file(p):
            seen.add(ap)
            out.append(os.path.abspath(p))

    _add(path)
    if not path:
        return out
    stem = os.path.splitext(os.path.basename(path))[0]
    fam = feeder_family_code(stem) or stem
    names = []
    for st in (stem, fam):
        if not st:
            continue
        for ext in (".zxst", ".sxst", ".zsxst", ".xst"):
            names.append(st + ext)
    for name in names:
        if projects:
            _add(os.path.join(projects, name))
        parent = os.path.dirname(path)
        if parent:
            _add(os.path.join(parent, name))
    return out


def resolve_writable_study_path(path, settings=None, prefer_exact=True):
    """Estudio a abrir/guardar: preferir el archivo exacto elegido en la UI.

    Si el usuario seleccionó PA217v2.xst y existe, se usa ese (no redirigir en
    silencio a PA217.zxst). Solo si el path no es usable se prueba .zxst hermano.
    CymPy Open puede fallar con .xst: open_study usa list_study_open_candidates.
    """
    if prefer_exact and is_usable_study_file(path):
        try:
            return os.path.abspath(path)
        except Exception:
            return path
    cands = list_study_open_candidates(path, settings=settings)
    if not cands:
        return path
    # Preferir .zxst de la familia solo como fallback
    for c in cands:
        if c.lower().endswith(".zxst"):
            return c
    for c in cands:
        if c.lower().endswith((".sxst", ".zsxst")):
            return c
    return cands[0]


def resolve_com_engine_study_path(path, settings=None):
    """Estudio para motor COM (LoadAllocation / GetFeederDemand / SetKW).

    En Cyme 9.2 los .xst/.zsxst legacy suelen devolver GetFeederDemand=None
    (luego SetKW explota). El .zxst de la misma familia sí expone la demanda.
    Conservar ui_study_path aparte; este path es solo para el motor.
    """
    settings = settings or {}
    cands = list_study_open_candidates(path, settings=settings)
    if not cands and path and is_usable_study_file(path):
        try:
            return os.path.abspath(path)
        except Exception:
            return path
    for c in cands:
        if str(c).lower().endswith(".zxst"):
            return c
    for c in cands:
        if str(c).lower().endswith((".sxst", ".zsxst")):
            return c
    if cands:
        return cands[0]
    return path


def resolve_eld_study_path(settings=None):
    """Ruta del estudio ELD (96 redes) usable."""
    settings = settings or load_json("config/settings.json")
    eld = (settings.get("eld_study_path") or "").strip()
    if is_usable_study_file(eld):
        return eld
    projects = (settings.get("projects_dir") or "").strip()
    if projects:
        cand = os.path.join(projects, "ELD.zxst")
        if is_usable_study_file(cand):
            return cand
    return eld if eld else ""


def _parse_feeder_arg(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    for i, a in enumerate(argv):
        if a == "--feeder" and i + 1 < len(argv):
            return argv[i + 1].strip()
        if a.startswith("--feeder="):
            return a.split("=", 1)[1].strip()
    # Support positional argument (e.g. run_all.py PA217)
    for a in argv:
        candidate = a.strip()
        # Evitar interpretar selectores de unittest/pytest como alimentadores.
        if not candidate.startswith("-") and re.match(
            r"^[A-Za-z]{2,6}\d{2,4}$", candidate
        ):
            return candidate
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

def list_study_files(settings=None, all_files=False):
    """Lista estudios en projects_dir / studies_root.

    Extensiones: .zxst, .sxst, .zsxst, .xst (CYMDIST legacy).

    all_files=False (default): un archivo por stem (alimentador), prioriza
      .zxst > .sxst > .zsxst > .xst  (para enlazar feeder→estudio).
    all_files=True: todos los archivos usables (para el desplegable §1).
    """
    if settings is None:
        settings = load_json("config/settings.json")
    dirs = []
    for key in ("projects_dir", "studies_root"):
        d = (settings.get(key) or "").strip()
        if d and os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    # Preferir projects_dir; studies_root a veces es el padre y no debe
    # listar .mdb como estudio. Solo escanear projects_dir si existe.
    if settings.get("projects_dir") and os.path.isdir(settings.get("projects_dir")):
        dirs = [settings.get("projects_dir").strip()]
        # studies_root solo si es distinto y es carpeta de proyectos
        sr = (settings.get("studies_root") or "").strip()
        pd = settings.get("projects_dir").strip()
        if sr and sr != pd and os.path.isdir(sr):
            # No añadir studies_root si es el padre de proyectos (contaminación)
            try:
                if os.path.normcase(os.path.abspath(sr)) != os.path.normcase(
                    os.path.abspath(os.path.dirname(pd))
                ):
                    dirs.append(sr)
            except Exception:
                pass

    rank = {".zxst": 0, ".sxst": 1, ".zsxst": 2, ".xst": 3}
    exts = (".zxst", ".sxst", ".zsxst", ".xst")
    by_stem = {}
    all_items = []
    seen_paths = set()
    for root in dirs:
        try:
            names = os.listdir(root)
        except Exception:
            continue
        for name in names:
            low = name.lower()
            ext = None
            for e in exts:
                if low.endswith(e):
                    ext = e
                    break
            if not ext:
                continue
            full = os.path.join(root, name)
            try:
                key_path = os.path.normcase(os.path.abspath(full))
            except Exception:
                key_path = full
            if key_path in seen_paths:
                continue
            if not is_usable_study_file(full):
                continue
            seen_paths.add(key_path)
            stem = name[: -len(ext)]
            item = {
                "name": name,
                "path": full,
                "dir": root,
                "feeder_id": stem,
                "ext": ext,
                "size": os.path.getsize(full),
            }
            all_items.append(item)
            key = stem.upper()
            prev = by_stem.get(key)
            if prev is None or rank.get(ext, 9) < rank.get(prev.get("ext"), 9):
                by_stem[key] = item
    if all_files:
        all_items.sort(key=lambda x: str(x.get("name") or "").upper())
        return all_items
    out = [by_stem[k] for k in sorted(by_stem.keys())]
    return out


def lookup_bd_network_id(feeder_id, settings=None):
    """Resuelve NET_* real desde catálogo BD (bd_networks.json), sin hardcode."""
    fid = str(feeder_id or "").strip().upper()
    if not fid:
        return ""
    path = p("data", "output", "system", "bd_networks.json")
    items = []
    if os.path.isfile(path):
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                items = (_json.load(f) or {}).get("networks") or []
        except Exception:
            items = []
    for it in items:
        if str(it.get("feeder_id") or "").strip().upper() == fid:
            return str(it.get("network_id") or "").strip()
    try:
        if os.path.isfile(feeder_config_path(fid)):
            fc = load_feeder_config(fid)
            nid = str(fc.get("network_id") or "").strip()
            if nid and (nid.upper().endswith("_" + fid) or nid.upper().endswith(fid)):
                return nid
    except Exception:
        pass
    return ""


def list_bd_feeder_catalog(settings=None, networks=None, include_orphan_studies=True):
    """Catálogo de alimentadores de la BD + estudio local si existe.

    networks: lista opcional [{network_id, feeder_id, ...}] ya resuelta para
    una BD concreta (p.ej. tras refresh). Si None, lee bd_networks*.json.
    include_orphan_studies: si True, añade .zxst locales sin red en la BD.
    """
    settings = settings or load_json("config/settings.json")
    studies = {str(s.get("feeder_id") or "").upper(): s for s in list_study_files(settings)}
    if networks is None:
        path = None
        conn = (
            settings.get("database_connection_name")
            or (
                os.path.splitext(os.path.basename(settings.get("database_mdb") or ""))[0]
                if settings.get("database_mdb")
                else ""
            )
        )
        # Preferir catálogo de esa BD
        try:
            from pipeline.model_quality_gate import _load_networks_disk
            disk_items, _disk_conn = _load_networks_disk(conn)
            networks = disk_items or []
        except Exception:
            networks = []
        if not networks:
            path = p("data", "output", "system", "bd_networks.json")
            if os.path.isfile(path):
                try:
                    import json as _json
                    with open(path, "r", encoding="utf-8") as f:
                        networks = (_json.load(f) or {}).get("networks") or []
                except Exception:
                    networks = []
    out = []
    seen = set()
    for it in networks or []:
        fid = str(it.get("feeder_id") or "").strip()
        nid = str(it.get("network_id") or "").strip()
        if not fid or fid.upper() in seen:
            continue
        seen.add(fid.upper())
        st = studies.get(fid.upper())
        out.append({
            "feeder_id": fid,
            "network_id": nid,
            "has_study": bool(st),
            "study_path": (st or {}).get("path") or "",
            "study_file": (st or {}).get("name") or "",
            "has_config": os.path.isfile(feeder_config_path(fid)),
            "label": "%s · %s" % (fid, nid) if nid else fid,
        })
    # Estudios locales sin entrada en BD aún
    if include_orphan_studies:
        for key, st in studies.items():
            if key in seen or key == "ELD":
                continue
            nid = lookup_bd_network_id(key, settings) or ""
            # Si la familia ya tiene red BD (PA217), no duplicar como PA217V2 huérfano
            fam = key
            m = re.match(r"^([A-Z]{1,3}\d{2,4})", key)
            if m:
                fam = m.group(1)
            if fam in seen and fam != key:
                # Variante de estudio: no añadir alimentador fantasma; el estudio
                # sigue listado en studies y se vincula a la red BD de la familia.
                continue
            out.append({
                "feeder_id": st.get("feeder_id") or key,
                "network_id": nid,
                "has_study": True,
                "study_path": st.get("path") or "",
                "study_file": st.get("name") or "",
                "has_config": os.path.isfile(feeder_config_path(key)),
                "label": ("%s · %s" % (key, nid)) if nid else key,
            })
    out.sort(key=lambda x: str(x.get("feeder_id") or ""))
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


def quick_context_catalog(
    settings=None,
    selected_database=None,
    selected_study=None,
    discovery=None,
):
    """Build a filesystem-only catalog; never opens CymPy or infers networks."""
    from core.context_identity import canonical_file_path

    s = dict(settings or {})
    selected_database = str(selected_database or s.get("database_mdb") or "").strip()
    selected_study = str(
        selected_study or s.get("ui_study_path") or s.get("study_path") or ""
    ).strip()

    databases = list_database_files(s)
    studies = list_study_files(s, all_files=True)

    def add_external(rows, path, kind):
        path = str(path or "").strip()
        if not path or not os.path.isfile(path):
            return
        canonical = canonical_file_path(path)
        if any(row.get("canonical_path") == canonical for row in rows):
            return
        absolute = os.path.realpath(os.path.abspath(path))
        row = {
            "name": os.path.basename(absolute),
            "path": absolute,
            "dir": os.path.dirname(absolute),
            "canonical_path": canonical,
        }
        if kind == "database":
            row["connection_name"] = os.path.splitext(row["name"])[0]
        else:
            row["feeder_id"] = os.path.splitext(row["name"])[0]
            row["ext"] = os.path.splitext(row["name"])[1].lower()
            row["size"] = os.path.getsize(absolute)
        rows.append(row)

    for row in databases + studies:
        row["path"] = os.path.realpath(os.path.abspath(row["path"]))
        row["canonical_path"] = canonical_file_path(row["path"])
    add_external(databases, selected_database, "database")
    add_external(studies, selected_study, "study")

    def dedupe(rows):
        unique = {}
        for row in rows:
            unique.setdefault(row["canonical_path"], row)
        result = list(unique.values())
        counts = {}
        for row in result:
            key = row["name"].casefold()
            counts[key] = counts.get(key, 0) + 1
        for row in result:
            if counts[row["name"].casefold()] > 1:
                row["label"] = "%s — %s" % (
                    row["name"],
                    os.path.basename(os.path.dirname(row["path"])) or row["dir"],
                )
            else:
                row["label"] = row["name"]
        result.sort(key=lambda item: (item["label"].casefold(), item["canonical_path"]))
        return result

    feeders = []
    if isinstance(discovery, dict):
        discovered_db = canonical_file_path(discovery.get("database_mdb"))
        if discovered_db and discovered_db == canonical_file_path(selected_database):
            feeders = list(discovery.get("feeders") or discovery.get("networks") or [])

    return {
        "ok": True,
        "databases": dedupe(databases),
        "studies": dedupe(studies),
        "feeders": feeders,
        "current_database": (
            os.path.realpath(os.path.abspath(selected_database)) if selected_database else ""
        ),
        "current_study": (
            os.path.realpath(os.path.abspath(selected_study)) if selected_study else ""
        ),
    }


def apply_context_selection(
    database_mdb=None,
    study_path=None,
    feeder_id=None,
    network_id=None,
    allowed_networks=None,
    strict=False,
    persist=True,
):
    """Aplica BD y/o estudio elegidos en la UI al settings (y alimentador del estudio).

    Si el estudio es IN112.zxst → active_feeder=IN112 y study_path de ese feeder.
    Así «Guardar medición cabecera» escribe en ese estudio/alimentador.
    """
    global_s = load_json("config/settings.json")
    if strict:
        from core.context_identity import (
            ContextIdentityError,
            build_context_identity,
            canonical_file_path,
            context_fingerprint,
        )

        identity = build_context_identity(
            {
                "database_mdb": database_mdb,
                "study_path": study_path,
                "feeder_id": feeder_id,
                "network_id": network_id,
            },
            require_complete=True,
        )
        mdb = identity["database_mdb"]
        study = identity["study_path"]
        if not os.path.isfile(mdb):
            raise ContextIdentityError("FILE_NOT_FOUND", "Base MDB no encontrada: %s" % mdb)
        if os.path.splitext(mdb)[1].lower() != ".mdb":
            raise ContextIdentityError(
                "INVALID_FILE_EXTENSION", "La base seleccionada debe ser .mdb"
            )
        if not os.path.isfile(study):
            raise ContextIdentityError("FILE_NOT_FOUND", "Estudio no encontrado: %s" % study)
        if os.path.splitext(study)[1].lower() not in (".zxst", ".sxst", ".zsxst", ".xst"):
            raise ContextIdentityError(
                "INVALID_FILE_EXTENSION", "Extensión de estudio no admitida"
            )
        if not is_usable_study_file(study):
            raise ContextIdentityError("STUDY_FILE_INVALID", "Estudio vacío o inválido: %s" % study)

        allowed_payload = allowed_networks or []
        if isinstance(allowed_payload, dict):
            discovered_db = canonical_file_path(allowed_payload.get("database_mdb"))
            if discovered_db and discovered_db != identity["canonical_database_mdb"]:
                raise ContextIdentityError(
                    "CONTEXT_IDENTITY_MISMATCH",
                    "El catálogo descubierto pertenece a otra MDB",
                    different_fields=["database_mdb"],
                )
            allowed_payload = (
                allowed_payload.get("feeders") or allowed_payload.get("networks") or []
            )
        normalized = [
            (
                str(row.get("feeder_id") or "").strip().upper(),
                str(row.get("network_id") or "").strip().upper(),
            )
            for row in allowed_payload
            if isinstance(row, dict)
        ]
        requested_pair = (
            identity["canonical_feeder_id"],
            identity["canonical_network_id"],
        )
        if requested_pair not in normalized:
            different = []
            if not any(row[0] == requested_pair[0] for row in normalized):
                different.append("feeder_id")
            if not any(row[1] == requested_pair[1] for row in normalized):
                different.append("network_id")
            raise ContextIdentityError(
                "CONTEXT_IDENTITY_MISMATCH",
                "El alimentador/red no pertenece al catálogo descubierto de la MDB",
                different_fields=different or ["feeder_id", "network_id"],
                actual=identity,
            )

        global_s["database_mdb"] = mdb
        global_s["database_dir"] = os.path.dirname(mdb)
        global_s["database_connection_name"] = os.path.splitext(os.path.basename(mdb))[0]
        global_s["ui_study_path"] = study
        global_s["ui_study_file"] = os.path.basename(study)
        global_s["active_feeder"] = identity["feeder_id"]
        global_s["active_network_id"] = identity["network_id"]
        if persist:
            if os.path.isfile(feeder_config_path(identity["feeder_id"])):
                feeder_config = load_feeder_config(identity["feeder_id"])
            else:
                feeder_config = synthesize_feeder_config(
                    identity["feeder_id"],
                    network_id=identity["network_id"],
                    persist=False,
                    global_s=global_s,
                )
            feeder_config["network_id"] = identity["network_id"]
            feeder_config["study_path"] = study
            feeder_config["study_file"] = os.path.basename(study)
            feeder_config["ui_study_path"] = study
            feeder_config["ui_study_file"] = os.path.basename(study)
            save_json("config/feeders/%s.json" % identity["feeder_id"], feeder_config)
            save_json("config/settings.json", global_s)
        result = {
            "ok": True,
            "changed": ["database_mdb", "ui_study_path", "active_feeder", "network_id"],
            "database_mdb": mdb,
            "database_connection_name": global_s["database_connection_name"],
            "study_path": study,
            "ui_study_path": study,
            "study_file": os.path.basename(study),
            "active_feeder": identity["feeder_id"],
            "feeder_id": identity["feeder_id"],
            "network_id": identity["network_id"],
        }
        result["context_fingerprint"] = context_fingerprint(result)
        result["msg"] = "Contexto estricto OK · %s · red %s" % (
            result["feeder_id"], result["network_id"]
        )
        return result
    changed = []
    resolved_feeder = (feeder_id or "").strip() or None

    if database_mdb:
        mdb = str(database_mdb).strip()
        if not os.path.isfile(mdb):
            raise RuntimeError("Base de datos no encontrada: %s" % mdb)
        global_s["database_mdb"] = mdb
        global_s["database_dir"] = os.path.dirname(mdb)
        preferred = os.path.splitext(os.path.basename(mdb))[0]
        # Resolver nombre real en CYMDIST por ruta (evitar homónimos en otra carpeta)
        conn_name = preferred
        try:
            from core.cympy_adapter import (
                find_cymdist_connection_for_mdb,
                unique_connection_name,
            )
            found = find_cymdist_connection_for_mdb(mdb)
            if found and found.get("name"):
                conn_name = found["name"]
            else:
                conn_name = unique_connection_name(preferred, mdb)
        except Exception:
            conn_name = preferred
        global_s["database_connection_name"] = conn_name
        changed.append("database_mdb")
        if conn_name != preferred:
            changed.append("database_connection:%s" % conn_name)

    if study_path:
        sp = str(study_path).strip()
        if not os.path.isfile(sp):
            raise RuntimeError("Estudio/proyecto no encontrado: %s" % sp)
        if not is_usable_study_file(sp):
            raise RuntimeError(
                "Estudio inválido o vacío (0 bytes): %s. "
                "Use ELD.zxst + alimentador de BD, o un .zxst propio válido."
                % sp
            )
        # Conservar elección UI; estudio de escritura = el mismo archivo si es usable
        global_s["ui_study_path"] = sp
        global_s["ui_study_file"] = os.path.basename(sp)
        sp_write = resolve_writable_study_path(sp, global_s)  # exacto si existe
        stem = os.path.splitext(os.path.basename(sp))[0]
        explicit = (feeder_id or "").strip() or None
        # El alimentador elegido explícitamente en la UI es independiente del
        # nombre del estudio: un estudio puede contener varias redes.
        # Solo inferirlo desde el archivo cuando la UI no envió alimentador.
        if stem and stem.upper() != "ELD":
            if explicit:
                resolved_feeder = explicit
            else:
                # Preferir red BD de la familia si existe en catálogo
                fam = feeder_family_code(stem)
                nid_fam = lookup_bd_network_id(fam, global_s) if fam else ""
                if nid_fam and fam:
                    resolved_feeder = fam
                else:
                    resolved_feeder = stem
            global_s["active_feeder"] = resolved_feeder
            changed.append("active_feeder:%s" % resolved_feeder)
        elif stem.upper() == "ELD":
            global_s["eld_study_path"] = sp
            changed.append("eld_study_path")
            if not resolved_feeder:
                resolved_feeder = (global_s.get("active_feeder") or "").strip() or None

        fid = (resolved_feeder or global_s.get("active_feeder") or stem or "").strip()
        if fid and fid.upper() != "ELD":
            nid = lookup_bd_network_id(fid, global_s)
            if os.path.isfile(feeder_config_path(fid)):
                fc = load_feeder_config(fid)
            else:
                fc = synthesize_feeder_config(
                    fid, network_id=nid or None, persist=False, global_s=global_s
                )
            # Escritura CYMDIST: path usable (.zxst si .xst no abre)
            fc["study_file"] = os.path.basename(sp_write)
            fc["study_path"] = sp_write
            fc["ui_study_path"] = sp
            fc["ui_study_file"] = os.path.basename(sp)
            if sp_write != sp:
                fc["study_open_fallback"] = True
                changed.append(
                    "study_fallback:%s->%s"
                    % (os.path.basename(sp), os.path.basename(sp_write))
                )
            if nid:
                fc["network_id"] = nid
            if persist:
                save_json("config/feeders/%s.json" % fid, fc)
                mkdir(p("data", "output", "feeders", fid, "demand"))
            changed.append("feeder_study:%s" % fid)
        changed.append("ui_study_path")

    # Solo feeder_id (sin study): cualquier alimentador de la BD
    if resolved_feeder and not study_path:
        fid = resolved_feeder.strip()
        nid = lookup_bd_network_id(fid, global_s)
        if os.path.isfile(feeder_config_path(fid)):
            fc = load_feeder_config(fid)
        else:
            fc = synthesize_feeder_config(
                fid, network_id=nid or None, persist=False, global_s=global_s
            )
        if nid:
            fc["network_id"] = nid
        # Estudio propio válido o ELD compartido (96 redes)
        sp_own = ""
        projects = (global_s.get("projects_dir") or "").strip()
        for ext in (".zxst", ".sxst", ".zsxst"):
            cand = os.path.join(projects, fid + ext) if projects else ""
            if is_usable_study_file(cand):
                sp_own = cand
                break
        if sp_own:
            fc["study_path"] = sp_own
            fc["study_file"] = os.path.basename(sp_own)
            global_s["ui_study_path"] = sp_own
            global_s["ui_study_file"] = os.path.basename(sp_own)
            fc["via_eld"] = False
        else:
            eld = resolve_eld_study_path(global_s)
            if not is_usable_study_file(eld):
                raise RuntimeError(
                    "Alimentador %s sin estudio propio válido y ELD.zxst no disponible. "
                    "Coloque %s.zxst en proyectos o configure eld_study_path."
                    % (fid, fid)
                )
            fc["study_path"] = eld
            fc["study_file"] = os.path.basename(eld)
            fc["via_eld"] = True
            global_s["ui_study_path"] = eld
            global_s["ui_study_file"] = os.path.basename(eld)
        global_s["active_feeder"] = fid
        if persist:
            save_json("config/feeders/%s.json" % fid, fc)
            mkdir(p("data", "output", "feeders", fid, "demand"))
            changed.append("active_feeder:%s" % fid)
            changed.append("feeder_bd:%s" % fid)

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
        # study_path = archivo que CYMDIST abre (.zxst); ui_study_path = elección UI
        "study_path": effective.get("study_path") or global_s.get("ui_study_path"),
        "ui_study_path": global_s.get("ui_study_path") or effective.get("study_path"),
        "study_file": global_s.get("ui_study_file") or os.path.basename(
            global_s.get("ui_study_path") or effective.get("study_path") or ""
        ),
        "active_feeder": fid_out or global_s.get("active_feeder"),
        "feeder_id": effective.get("feeder_id") or fid_out,
        "network_id": effective.get("network_id"),
        "msg": "Contexto OK · %s · red %s" % (
            effective.get("feeder_id") or fid_out or "?",
            effective.get("network_id") or "—",
        ),
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
            os.path.join(projects, fid + ".zsxst"),
        ])
    eld = (global_s.get("eld_study_path") or "").strip()
    if eld:
        candidates.append(eld)
    elif projects:
        candidates.append(os.path.join(projects, "ELD.zxst"))
    for cand in candidates:
        if is_usable_study_file(cand):
            study_path = cand
            study_file = os.path.basename(cand)
            break
    # Si el candidato propio era vacío/corrupto, forzar ELD
    if not study_path:
        eld2 = resolve_eld_study_path(global_s)
        if is_usable_study_file(eld2):
            study_path = eld2
            study_file = os.path.basename(eld2)
    nid = str(network_id or "").strip() or lookup_bd_network_id(fid, global_s)
    if not nid:
        nid = "NET_" + fid
    via_eld = bool(study_path) and os.path.basename(study_path).upper().startswith("ELD.")
    data = {
        "name": fid,
        "description": "Auto desde BD/estudio (sin config/feeders previa)",
        "network_id": nid,
        "study_file": study_file,
        "study_path": study_path,
        "via_eld": via_eld,
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
    fid = (settings.get("active_feeder") or "").strip()
    if fid:
        return fid
    ui = (settings.get("ui_study_path") or "").strip()
    if ui:
        stem = os.path.splitext(os.path.basename(ui))[0]
        if stem and stem.upper() != "ELD":
            return stem
    raise RuntimeError(
        "Ningún alimentador fijo. Elija estudio/alimentador en la UI §1 o use --feeder ID / RECYM_FEEDER"
    )

def _default_paths(feeder_id):
    base = os.path.join("data", "input", "feeders", feeder_id)
    return {
        "control_workbook": os.path.join(base, "Control_Simulacion.xlsx"),
        "catalog_workbook": os.path.join(base, "Catalogo_Maestro.xlsx"),
        "output_dir": os.path.join("data", "output", "feeders", feeder_id),
    }

def resolve_study_path(merged, feeder):
    """Prioridad: study_path usable > projects_dir + study_file > <ID>.zxst > ELD."""
    sp = (merged.get("study_path") or "").strip()
    if is_usable_study_file(sp):
        return sp
    projects = (merged.get("projects_dir") or "").strip()
    study_file = (feeder.get("study_file") or merged.get("study_file") or "").strip()
    if not study_file:
        study_file = merged.get("feeder_id", "") + ".zxst"
    if projects and study_file:
        cand = os.path.join(projects, study_file)
        if is_usable_study_file(cand):
            return cand
        alt = os.path.splitext(cand)[0] + ".sxst"
        if is_usable_study_file(alt):
            return alt
    # Fallback ELD (cualquier alimentador de la BD sin .zxst propio)
    eld = resolve_eld_study_path(merged)
    if is_usable_study_file(eld):
        return eld
    return sp if sp else ""


def resolve_cymdist_binding(settings):
    """Enlace obligatorio: estudio usable + BD por ruta (importar/activar en CYMDIST).

    Universal: no hardcodea un alimentador. Usa settings del §1:
      - feeder_id / network_id
      - study_path / ui_study_path → .zxst usable (fallback familia)
      - database_mdb → conexión CYMDIST por ruta exacta (no homónimo en otra carpeta)

    Retorna dict listo para logs/jobs; lanza RuntimeError si falta estudio o BD.
    """
    s = settings or {}
    fid = str(s.get("feeder_id") or "").strip()
    nid = str(s.get("network_id") or "").strip()
    ui_study = str(s.get("ui_study_path") or "").strip()
    study = str(s.get("study_path") or ui_study or "").strip()
    mdb = str(s.get("database_mdb") or "").strip()
    conn = str(s.get("database_connection_name") or "").strip()

    if study:
        try:
            # Si hay ui_study_path distinto y usable, ese es el que el usuario ve
            if ui_study and is_usable_study_file(ui_study):
                study = os.path.abspath(ui_study)
            else:
                study = resolve_writable_study_path(study, s) or study
        except Exception:
            pass
    if not study:
        raise RuntimeError(
            "Falta study_path para alimentador %s. Elija estudio en §1." % (fid or "?")
        )
    if not is_usable_study_file(study):
        # Fallback familia (.zxst) si el elegido no abre
        alt = resolve_writable_study_path(study, s, prefer_exact=False)
        if alt and is_usable_study_file(alt):
            study = alt
        else:
            raise RuntimeError(
                "Estudio inválido/vacío para alimentador %s: %s. "
                "Use ELD.zxst (96 redes) o un .zxst/.xst propio con contenido."
                % (fid or "?", study)
            )
    if not mdb:
        raise RuntimeError(
            "Falta database_mdb. Elija la base .mdb en §1 y pulse 1.1 Aplicar."
        )
    if not os.path.isfile(mdb):
        raise RuntimeError("No existe la BD seleccionada: %s" % mdb)

    # Nombre real en CYMDIST por ruta (evitar 'BASE JUL25 1' → otra carpeta)
    try:
        from core.cympy_adapter import (
            find_cymdist_connection_for_mdb,
            unique_connection_name,
        )
        found = find_cymdist_connection_for_mdb(mdb)
        if found and found.get("name"):
            conn = found["name"]
        else:
            preferred = conn or os.path.splitext(os.path.basename(mdb))[0]
            conn = unique_connection_name(preferred, mdb)
    except Exception:
        if not conn:
            conn = os.path.splitext(os.path.basename(mdb))[0]

    open_name = os.path.basename(study)
    ui_name = os.path.basename(ui_study or study)
    bind_label = "%s · estudio=%s · BD=%s(%s)" % (
        fid or "?",
        open_name,
        conn,
        os.path.basename(mdb),
    )
    if ui_study and os.path.normcase(os.path.abspath(ui_study)) != os.path.normcase(
        os.path.abspath(study)
    ):
        bind_label += " · UI=%s" % ui_name

    return {
        "ok": True,
        "feeder_id": fid,
        "network_id": nid,
        "study_path": study,
        "ui_study_path": ui_study or study,
        "study_file": open_name,
        "database_mdb": mdb,
        "database_file": os.path.basename(mdb),
        "database_connection_name": conn,
        "binding": bind_label,
    }


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
    # Override UI solo si el estudio elegido corresponde a ESTE alimentador (o ELD).
    # Evita mezclar red IN112 con estudio PA217 por un ui_study_path global fijo.
    ui_sp = (global_s.get("ui_study_path") or "").strip()
    if ui_sp and os.path.isfile(ui_sp):
        ui_stem = os.path.splitext(os.path.basename(ui_sp))[0]
        if ui_stem.upper() in (str(fid).upper(), "ELD"):
            merged["study_path"] = ui_sp
            merged["study_file"] = os.path.basename(ui_sp)
        elif resolved:
            merged["study_path"] = resolved
        else:
            merged["study_path"] = ui_sp
            merged["study_file"] = os.path.basename(ui_sp)
    elif resolved:
        merged["study_path"] = resolved
    # Si network genérico NET_<ID>, intentar catálogo BD
    nid = str(merged.get("network_id") or "").strip()
    if (not nid) or nid.upper() == ("NET_" + str(fid).upper()):
        looked = lookup_bd_network_id(fid, global_s)
        if looked:
            merged["network_id"] = looked
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
