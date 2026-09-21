from __future__ import print_function
import os, sys, json, csv, datetime, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def p(*parts):
    return os.path.join(ROOT, *parts)

def load_json(rel):
    with open(p(*rel.split("/")), "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(rel, data):
    path = p(*rel.split("/"))
    mkdir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def resolve_python(settings=None):
    if settings is None:
        settings = load_json("config/settings.json")
    rel = settings.get("python_exe") or ".tools\\python37-win32\\python.exe"
    cand = rel if os.path.isabs(rel) else p(*rel.split("\\"))
    if os.path.isfile(cand):
        return cand
    legacy = r"C:\Program Files (x86)\CYME\CYME\Python37\python.exe"
    if os.path.isfile(legacy):
        return legacy
    return sys.executable

def require_cympy(settings):
    root = settings["cyme_root"]
    if root not in sys.path:
        sys.path.insert(0, root)
    import cympy
    return cympy

def ts():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def mkdir(path):
    if not os.path.isdir(path):
        os.makedirs(path)

def write_csv(path, rows, headers):
    mkdir(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def backup_file(path):
    if not path or not os.path.isfile(path):
        return None
    dest_dir = p("data", "output", "backups")
    mkdir(dest_dir)
    base = os.path.basename(path)
    dest = os.path.join(dest_dir, "%s_%s" % (ts(), base))
    shutil.copy2(path, dest)
    return dest

def truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "si", "sí", "y")

def is_cympy_exit_crash(rc):
    """True si el proceso murió con ACCESS_VIOLATION típico de teardown CymPy/COM."""
    if rc is None:
        return False
    try:
        return (int(rc) & 0xFFFFFFFF) == 0xC0000005
    except Exception:
        return False

def exit_ok():
    """Salida limpia evitando destructores nativos de CymPy (0xC0000005)."""
    os._exit(0)

def exit_fail(code=1):
    os._exit(int(code) if code else 1)

def run_cympy_main(main_fn):
    """Ejecuta main CymPy. El proceso debe terminar con os._exit antes del teardown.

    Si main_fn retorna con normalidad, se llama exit_ok(); preferible que main
    llame exit_ok() al final (antes de destruir handles CymPy locales).
    """
    try:
        main_fn()
    except SystemExit as e:
        code = e.code
        if code is None or code == 0:
            exit_ok()
        if isinstance(code, int):
            exit_fail(code)
        exit_fail(1)
    except Exception as ex:
        print("FALLO:", type(ex).__name__, ex)
        exit_fail(1)
    # Si main no llamó exit_ok, intentar aquí (puede no alcanzarse si ya crasheó).
    exit_ok()
