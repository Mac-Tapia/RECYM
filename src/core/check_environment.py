from __future__ import print_function
import os, sys
from core.common import require_cympy, resolve_python
from core.feeder_context import load_settings, list_feeders, list_study_files

s = load_settings()
print("Utility:", s.get("utility_name"))
print("Alimentador activo:", s.get("feeder_id"), "-", s.get("feeder_name"))
print("Alimentadores RECYM:", ", ".join(list_feeders()))
print("Estudios en projects_dir:", ", ".join(list_study_files(s)) or "(ninguno)")
print("studies_root:", s.get("studies_root"))
print("projects_dir:", s.get("projects_dir"))
print("database_dir:", s.get("database_dir"))
print("database_mdb:", s.get("database_mdb"))
print("study_path:", s.get("study_path") or "(vacío)")
print("Python:", sys.version)
print("Ejecutable:", sys.executable)
print("Resolver settings python_exe:", resolve_python(s))
print("CYME_ROOT:", s["cyme_root"])
print("Existe CYME_ROOT:", os.path.isdir(s["cyme_root"]))
print("dry_run:", s.get("dry_run"))
c = require_cympy(s)
print("CYMPY OK:", getattr(c, "version", c))
