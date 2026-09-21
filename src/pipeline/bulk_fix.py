# -*- coding: utf-8 -*-
from __future__ import print_function
"""Aplica correcciones de la tabla Correcciones / correcciones_propuestas.csv.

Despacha por Accion_Sugerida segun config/diagnostic_corrections_catalog.json
(cymdist.cymsg DiagnosticTool + LoadFlow/Simulation). Cada codigo del diagnostico
tiene handler; los Activo=true se escriben en el estudio CYMDIST.
"""
import csv
import os
from core.common import require_cympy, write_csv, truthy, load_json, run_cympy_main
from core.excel_io import read_rows
from core.cympy_adapter import CymPyAdapter
from core.feeder_context import load_settings, catalog_path, output_path
from pipeline.diagnostic_registry import apply_action, _NeedsStudyRestart


def _load_corrections(s):
    if s.get("use_diagnostic_corrections", True):
        path = output_path(s, "diagnostics", "correcciones_propuestas.csv")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            print("Usando correcciones propuestas:", path)
            return rows
    catalog = catalog_path(s)
    return read_rows(catalog, "Correcciones")


def main():
    s = load_settings()
    api = load_json("config/cympy_api_map.json")
    rows = [r for r in _load_corrections(s) if truthy(r.get("Activo"))]
    limit = s.get("max_corrections")
    if limit:
        rows = rows[: int(limit)]
    preview = []
    print("[%s] Correcciones activas: %s | dry_run=%s" % (
        s["feeder_id"], len(rows), s.get("dry_run")))

    a = None
    if not s.get("dry_run"):
        c = require_cympy(s)
        a = CymPyAdapter(c, api, s)
        a.ensure_study()
        if not a._study_open:
            a.open_study()

    ok = err = skipped = 0
    lf_warnings_done = False
    base_voltages_done = False

    for r in rows:
        tipo_raw = str(r.get("Tipo") or "").strip()
        obj_id = r.get("ID_CYMDIST")
        action = (r.get("Accion_Sugerida") or "").strip() or "revisar"
        before = ""
        after = ""
        status = "OK"
        try:
            if action == "revisar":
                status = "SKIP"
                after = "Accion=revisar (manual segun manual CYME)"
                skipped += 1
            elif s.get("dry_run"):
                after = action
                status = "DRY_RUN"
                ok += 1
            elif action == "fix_lf_warnings":
                if lf_warnings_done:
                    status = "SKIP"
                    after = "fix_lf_warnings ya aplicado"
                    skipped += 1
                else:
                    if a is not None:
                        try:
                            if s.get("save_after_fix", True):
                                a.save_study()
                            a.close_study(save=False)
                        except Exception:
                            pass
                        a = None
                    from pipeline.fix_lf_warnings import run as fix_lf_warnings
                    fres = fix_lf_warnings(s)
                    after = "ok=%s notes=%s" % (
                        fres.get("ok"), len(fres.get("notes") or []))
                    if not fres.get("ok"):
                        raise RuntimeError(after)
                    lf_warnings_done = True
                    ok += 1
                    c = require_cympy(s)
                    a = CymPyAdapter(c, api, s)
                    a.open_study()
            elif action == "ensure_valid_base_voltages":
                if base_voltages_done:
                    status = "SKIP"
                    after = "ensure_valid_base_voltages ya aplicado"
                    skipped += 1
                else:
                    action, before, after = apply_action(a, s, r)
                    base_voltages_done = True
                    ok += 1
            else:
                try:
                    action, before, after = apply_action(a, s, r)
                    ok += 1
                except _NeedsStudyRestart:
                    # fallback por si apply_action lo lanza
                    if a is not None:
                        try:
                            a.close_study(save=False)
                        except Exception:
                            pass
                        a = None
                    from pipeline.fix_lf_warnings import run as fix_lf_warnings
                    fres = fix_lf_warnings(s)
                    after = str(fres.get("ok"))
                    lf_warnings_done = True
                    ok += 1
                    c = require_cympy(s)
                    a = CymPyAdapter(c, api, s)
                    a.open_study()

            if status == "OK":
                print("WRITE", action, tipo_raw, obj_id, before, "->", after)
            elif status == "DRY_RUN" and (ok <= 5 or ok % 200 == 0):
                print("DRY", action, tipo_raw, obj_id, "->", after)
            elif status == "SKIP":
                print("SKIP", tipo_raw, obj_id, after)
        except Exception as ex:
            status = "ERROR"
            after = str(ex)
            err += 1
            print("ERROR", action, tipo_raw, obj_id, ex)
            if s.get("abort_on_first_write_error"):
                raise

        preview.append({
            "Feeder": s["feeder_id"],
            "Activo": r.get("Activo"),
            "Tipo": tipo_raw,
            "ID_CYMDIST": obj_id,
            "Accion": action,
            "Codigo": r.get("Codigo") or "",
            "Antes": before,
            "Despues": after,
            "Estado": status,
            "Observacion": r.get("Observacion") or "",
        })

    out = output_path(s, "preview_changes.csv")
    write_csv(out, preview, [
        "Feeder", "Activo", "Tipo", "ID_CYMDIST", "Accion", "Codigo",
        "Antes", "Despues", "Estado", "Observacion",
    ])
    print("OK:", ok, "ERROR:", err, "SKIP:", skipped)
    print("Preview:", out)

    if not s.get("dry_run") and a is not None and s.get("save_after_fix", True):
        try:
            a.save_study()
            print("Estudio guardado.")
        except Exception as ex:
            print("AVISO save_study:", ex)


if __name__ == "__main__":
    run_cympy_main(main)
