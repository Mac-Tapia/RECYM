# -*- coding: utf-8 -*-
"""Smoke P0: readiness + isolation metadata (sin abrir estudio CYMDIST)."""
from __future__ import print_function

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    from api_app.readiness import check_ready
    from core.cympy_isolation import describe_isolation, should_isolate_action

    ready = check_ready()
    iso = describe_isolation()
    sample = {
        "calidad_diagnosticar": should_isolate_action("calidad_diagnosticar"),
        "distribucion": should_isolate_action("distribucion"),
        "flujo": should_isolate_action("flujo"),
        "build_tablero": should_isolate_action("build_tablero"),
    }
    out = {
        "ready": ready,
        "isolation": iso,
        "should_isolate": sample,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    if not ready.get("ok"):
        print("SMOKE FAIL · not ready:", "; ".join(ready.get("errors") or []))
        return 1
    if not iso.get("enabled"):
        print("SMOKE WARN · isolation disabled (RECYM_ISOLATE_JOBS=0?)")
    print("SMOKE OK · ready + isolation enabled=%s" % iso.get("enabled"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
