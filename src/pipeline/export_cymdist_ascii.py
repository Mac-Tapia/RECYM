#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Exporta la BD CYMDIST a archivos ASCII (Red / Equipos / Cargas).

Error CYME 530014: "No puede exportar a ASCII. Favor de cargar sus redes
y actualizarlas en primer lugar."

Causa: ExportASCII exige un estudio abierto con TODAS las redes de la BD
cargadas y un db.Update() previo. Conectar la BD o usar el Utilitario sin
ese paso falla siempre.

Uso:
  python -u src/pipeline/export_cymdist_ascii.py
  python -u src/pipeline/export_cymdist_ascii.py --out D:\\ruta\\exportarTXT --prefix 260921
"""
from __future__ import print_function

import argparse
import os
import sys
import time
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))


def _load_settings():
    from core.common import load_json

    return load_json(os.path.join(ROOT, "config", "settings.json"))


def export_ascii(settings, out_dir, prefix, connection_name=None, study_path=None):
    """Exporta ASCII. Si study_path (ELD.zxst) existe, lo abre; si no, study.New()+LoadNetworks."""
    import cympy
    import cympy.db as db
    import cympy.study as study

    conn = connection_name or settings.get("database_connection_name") or "20260919"
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    net_path = os.path.join(out_dir, "%sRed.txt" % prefix)
    eq_path = os.path.join(out_dir, "%sEquipos.txt" % prefix)
    ld_path = os.path.join(out_dir, "%sCargas.txt" % prefix)

    print("Conexion:", conn)
    print("Salida:", out_dir)
    db.ConnectDatabaseByName(conn)

    nets = [str(n) for n in list(db.ListNetworks())]
    print("Redes en BD:", len(nets))
    if not nets:
        raise RuntimeError("La BD no tiene redes. Verifique la conexion %s." % conn)

    study_path = study_path or settings.get("eld_study_path") or ""
    opt = cympy.enums.LoadNetworkOption.NoDependencies
    if study_path and os.path.isfile(study_path):
        print("Abrir estudio:", study_path)
        study.Open(study_path)
        loaded = [str(n) for n in list(study.ListNetworks())]
        if len(loaded) < len(nets):
            print("Cargar redes faltantes (%d → %d)..." % (len(loaded), len(nets)))
            study.LoadNetworks(nets, opt)
    else:
        print("Crear estudio vacio + LoadNetworks...")
        study.New()
        study.LoadNetworks(nets, opt)

    loaded = list(study.ListNetworks())
    print("Cargadas:", len(loaded))
    if len(loaded) < len(nets):
        raise RuntimeError(
            "Solo se cargaron %d/%d redes. ExportASCII fallaria (530014)."
            % (len(loaded), len(nets))
        )

    print("Actualizar BD (db.Update)...")
    db.Update()

    print("ExportASCII...")
    t0 = time.time()
    db.ExportASCII(net_path, eq_path, ld_path)
    print("ExportASCII OK en %.1fs" % (time.time() - t0))

    result = {}
    for label, path in (("Red", net_path), ("Equipos", eq_path), ("Cargas", ld_path)):
        if not os.path.isfile(path):
            raise RuntimeError("No se genero: %s" % path)
        size = os.path.getsize(path)
        if size < 100:
            raise RuntimeError("Archivo demasiado pequeno (posible fallo): %s (%d bytes)" % (path, size))
        print("  %s: %s (%d bytes)" % (label, path, size))
        result[label] = {"path": path, "bytes": size}
    return result


def main(argv=None):
    settings = _load_settings()
    default_out = os.path.join(
        settings.get("studies_root") or r"D:\BaseDatosElectroDunas\260919BaseDatos",
        "exportarTXT",
    )
    ap = argparse.ArgumentParser(description="Export CYMDIST ASCII (evita error 530014)")
    ap.add_argument("--out", default=default_out, help="Carpeta destino")
    ap.add_argument("--prefix", default="260921", help="Prefijo de archivos (ej. 260921)")
    ap.add_argument(
        "--connection",
        default="",
        help="Nombre conexion CYME (default: settings.database_connection_name)",
    )
    ap.add_argument(
        "--study",
        default="",
        help="Ruta .zxst (default: settings.eld_study_path / ELD.zxst)",
    )
    args = ap.parse_args(argv)

    try:
        try:
            from core.cymdist_com import pause_cymdist_for_cympy
            pause_cymdist_for_cympy(settings)
        except Exception as ex:
            print("AVISO pause CYMDIST:", ex)
        export_ascii(
            settings,
            out_dir=args.out,
            prefix=args.prefix,
            connection_name=args.connection or None,
            study_path=args.study or None,
        )
        print("EXPORT OK")
        return 0
    except Exception as e:
        print("EXPORT FAIL:", e)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # CymPy a veces termina con 0xC0000005 al cerrar; si los archivos existen, OK.
    code = main()
    sys.exit(code)
