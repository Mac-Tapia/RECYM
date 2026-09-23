# -*- coding: utf-8 -*-
"""Carga de settings con overlay local y env (producción workstation)."""
from __future__ import print_function

import copy
import json
import os

from core.common import ROOT, mkdir, p

_SETTINGS_CACHE = None
_SETTINGS_CACHE_MTIME = None


def _deep_merge(base, overlay):
    """Fusiona overlay sobre base (dicts anidados). Mutates copy of base."""
    out = copy.deepcopy(base) if base is not None else {}
    if not isinstance(overlay, dict):
        return out
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _settings_paths():
    return {
        "base": p("config", "settings.json"),
        "local": p("config", "settings.local.json"),
        "example": p("config", "settings.example.json"),
    }


def invalidate_settings_cache():
    global _SETTINGS_CACHE, _SETTINGS_CACHE_MTIME
    _SETTINGS_CACHE = None
    _SETTINGS_CACHE_MTIME = None


def _paths_mtime(paths):
    total = 0
    for key in ("base", "local"):
        path = paths[key]
        try:
            if os.path.isfile(path):
                total += os.path.getmtime(path)
        except Exception:
            pass
    return total


def load_settings(force=False):
    """settings.json + settings.local.json (gana local) + overrides de entorno.

    Variables:
      RECYM_STUDIES_ROOT, RECYM_PROJECTS_DIR, RECYM_DATABASE_MDB,
      RECYM_ACTIVE_FEEDER, GOOGLE_MAPS_API_KEY, RECYM_DRY_RUN
    """
    global _SETTINGS_CACHE, _SETTINGS_CACHE_MTIME
    paths = _settings_paths()
    mtime = _paths_mtime(paths)
    if (
        not force
        and _SETTINGS_CACHE is not None
        and _SETTINGS_CACHE_MTIME == mtime
    ):
        return copy.deepcopy(_SETTINGS_CACHE)

    base_path = paths["base"]
    example_path = paths["example"]
    if os.path.isfile(base_path):
        data = _read_json_file(base_path)
    elif os.path.isfile(example_path):
        data = _read_json_file(example_path)
    else:
        data = {}

    local_path = paths["local"]
    if os.path.isfile(local_path):
        data = _deep_merge(data, _read_json_file(local_path))

    env_map = {
        "RECYM_STUDIES_ROOT": "studies_root",
        "RECYM_PROJECTS_DIR": "projects_dir",
        "RECYM_DATABASE_DIR": "database_dir",
        "RECYM_DATABASE_MDB": "database_mdb",
        "RECYM_ACTIVE_FEEDER": "active_feeder",
        "RECYM_UI_STUDY_PATH": "ui_study_path",
        "GOOGLE_MAPS_API_KEY": "google_maps_api_key",
    }
    for env_k, conf_k in env_map.items():
        val = os.environ.get(env_k)
        if val is not None and str(val).strip() != "":
            data[conf_k] = val.strip()

    dry = os.environ.get("RECYM_DRY_RUN")
    if dry is not None and str(dry).strip() != "":
        data["dry_run"] = str(dry).strip().lower() in ("1", "true", "yes", "si", "sí")

    _SETTINGS_CACHE = data
    _SETTINGS_CACHE_MTIME = mtime
    return copy.deepcopy(data)


def save_settings_local(data):
    """Persiste overlay local (no versionar)."""
    path = _settings_paths()["local"]
    mkdir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    invalidate_settings_cache()
    return path


def ensure_local_from_base_if_missing():
    """Si no hay settings.local.json y sí settings.json, no copia (compat).

    Solo crea local vacío de marcador si no existe base ni local.
    """
    paths = _settings_paths()
    if os.path.isfile(paths["local"]) or os.path.isfile(paths["base"]):
        return False
    if os.path.isfile(paths["example"]):
        mkdir(os.path.dirname(paths["local"]))
        with open(paths["example"], "r", encoding="utf-8") as src:
            raw = src.read()
        with open(paths["local"], "w", encoding="utf-8") as dst:
            dst.write(raw)
        invalidate_settings_cache()
        return True
    return False
