from __future__ import print_function
"""Alta de un nuevo alimentador Electro Oriente."""
import argparse
import os
import shutil
from core.feeder_context import create_feeder_from_template, list_feeders
from core.common import p, mkdir

def main():
    ap = argparse.ArgumentParser(description="Crear alimentador RECYM / Electro Oriente")
    ap.add_argument("feeder_id", help="ID corto, ej. PA218, LO210, IQT01")
    ap.add_argument("--name", default="", help="Nombre descriptivo")
    ap.add_argument("--network-id", default="", help="NetworkID CYMDIST")
    ap.add_argument("--study-path", default="", help="Ruta .sxst/.mdb")
    ap.add_argument("--voltage", type=float, default=22.9, help="Tensión LL kV")
    ap.add_argument("--from-feeder", default="", help="Copiar Excels desde este alimentador (vacío = plantilla sola)")
    args = ap.parse_args()

    fid = args.feeder_id.strip().upper().replace(" ", "_")
    path = create_feeder_from_template(
        fid,
        name=args.name or fid,
        network_id=args.network_id,
        study_path=args.study_path,
        voltage_kv=args.voltage,
    )
    dest = p("data", "input", "feeders", fid)
    mkdir(dest)
    from_feeder = (args.from_feeder or "").strip()
    if not from_feeder:
        # Preferir active_feeder de settings si existe carpeta de input
        try:
            from core.common import load_json
            from_feeder = str((load_json("config/settings.json") or {}).get("active_feeder") or "").strip()
        except Exception:
            from_feeder = ""
    src = p("data", "input", "feeders", from_feeder) if from_feeder else ""
    if src and os.path.isdir(src):
        for fname in ("Control_Simulacion.xlsx", "Catalogo_Maestro.xlsx"):
            sfile = os.path.join(src, fname)
            dfile = os.path.join(dest, fname)
            if os.path.isfile(sfile) and not os.path.isfile(dfile):
                shutil.copy2(sfile, dfile)
                print("Copiado Excel:", dfile)
    print("Creado:", path)
    print("Datos:", dest)
    print("Alimentadores:", ", ".join(list_feeders()))
    print("Active: edite config/settings.json -> active_feeder o use --feeder", fid)

if __name__ == "__main__":
    main()
