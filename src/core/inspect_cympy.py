from __future__ import print_function
import os
from core.common import load_json, require_cympy, p, mkdir

settings = load_json("config/settings.json")
cympy = require_cympy(settings)
out = p("data", "output", "diagnostics", "cympy_introspection.txt")
mkdir(os.path.dirname(out))

with open(out, "w", encoding="utf-8") as f:
    f.write("CYME/CYMDIST 9.2 R1 - INTROSPECCION CYMPY\n")
    f.write("version: %s\n\n" % getattr(cympy, "version", "?"))
    for label, obj in [
        ("cympy", cympy),
        ("cympy.study", getattr(cympy, "study", None)),
        ("cympy.sim", getattr(cympy, "sim", None)),
        ("cympy.enums", getattr(cympy, "enums", None)),
        ("cympy.dm", getattr(cympy, "dm", None)),
    ]:
        f.write("=== %s ===\n" % label)
        if obj is None:
            f.write("NO DISPONIBLE\n\n")
            continue
        for n in sorted([x for x in dir(obj) if not x.startswith("_")]):
            f.write(n + "\n")
        f.write("\n")
    dt = getattr(getattr(cympy, "enums", None), "DeviceType", None)
    f.write("=== DeviceType ===\n")
    if dt:
        for n in sorted([x for x in dir(dt) if not x.startswith("_")]):
            try:
                f.write("%s = %r\n" % (n, getattr(dt, n)))
            except Exception:
                pass
print(out)
