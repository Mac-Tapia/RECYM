from __future__ import print_function
"""Smoke test conexion Electro Dunas + CymPy."""
from core.common import require_cympy, load_json, run_cympy_main
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, list_feeders, list_study_files
import os

def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    print("Utility:", s.get("utility_name"))
    print("Alimentador:", s.get("feeder_id"), "-", s.get("feeder_name"))
    print("Registrados RECYM:", ", ".join(list_feeders()))
    print("studies_root:", s.get("studies_root"))
    print("projects_dir:", s.get("projects_dir"))
    print("database_dir:", s.get("database_dir"))
    print("database_mdb:", s.get("database_mdb"))
    print("Estudios .zxst en disco:", ", ".join(list_study_files(s)) or "(ninguno)")
    print("study_path resuelto:", s.get("study_path") or "(vacío)")
    print("study exists:", os.path.isfile(s.get("study_path") or ""))
    print("mdb exists:", os.path.isfile(s.get("database_mdb") or ""))

    c = require_cympy(s)
    print("OK import cympy:", getattr(c, "version", "?"))
    a = CymPyAdapter(c, api, s)

    if s.get("database_mdb") and os.path.isfile(s["database_mdb"]):
        a.connect_database()

    if s.get("study_path") and os.path.isfile(s["study_path"]):
        a.open_study(connect_db=False)
        print("Conexion Electro Dunas OK")
    else:
        print("API OK pero falta study_path/.zxst para este alimentador")

if __name__ == "__main__":
    run_cympy_main(main)
