# -*- coding: utf-8 -*-
"""
Entrega autonoma del informe tecnico RECYM (sin intervencion manual).

Punto unico usado por UI, API jobs y CLI:

  1) (opcional) LoadFlow situacional + proyectado si faltan o estan rotos
  2) Capturas CYMDIST de coloreo tension/cargabilidad desde §5
  3) fill_informe: Excel (formulas) + Word + PDF + preview

Uso CLI (desde raiz del repo, Python 32-bit CYME)::

  .tools\\python37-win32\\python.exe -m pipeline.deliver_informe --feeder AL209
  .tools\\python37-win32\\python.exe -m pipeline.deliver_informe --feeder AL209 --ensure-lf --force-captures
"""
from __future__ import print_function

import argparse
import json
import os
import sys


def _ensure_src_path():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    if os.getcwd() != root:
        try:
            os.chdir(root)
        except Exception:
            pass
    return root


def deliver_informe(
    settings=None,
    ensure_lf=False,
    force_captures=False,
    require_delivery=True,
    scenarios_lf=None,
    ocr_review=True,
    ocr_review_rounds=3,
    informe_mode=None,
):
    """
    Genera el informe listo para entrega.

    informe_mode: completo (default) | situacional
      situacional = diagnóstico estado situacional Electro Dunas (solo LF situacional).

    ensure_lf: si True, ejecuta LoadFlow de los escenarios del modo cuando falten.
    force_captures: fuerza recaptura CYMDIST (ignore PNG previos).
    require_delivery: gate estricto según modo.
    ocr_review: tras fill, revision OCR rigurosa (imagenes/cuadros) hasta N rondas.
    """
    from core.feeder_context import load_settings
    from core.report_provenance import assert_report_context, tag_context
    from pipeline.assemble_informe import informe_paths
    from pipeline.fill_informe import fill_informe, delivery_status, _normalize_informe_mode
    from pipeline.run_load_flow import run_load_flow

    s = dict(settings or load_settings())
    mode = _normalize_informe_mode(informe_mode or s.get("informe_mode"))
    s["informe_mode"] = mode
    # Entrega completa siempre integra capturas §5 (no depender de un agente).
    s["informe_auto_cymdist_capture"] = True
    s["informe_prefer_cymdist_captures"] = True
    if force_captures:
        s["force_cymdist_captures"] = True
    if ocr_review_rounds is not None:
        s["informe_ocr_review_rounds"] = int(ocr_review_rounds)

    notes = []
    lf_runs = []
    if ensure_lf:
        if scenarios_lf:
            want = tuple(scenarios_lf)
        elif mode == "situacional":
            want = ("situacional",)
        else:
            want = ("situacional", "proyectado")
        paths = informe_paths(s)
        for scen in want:
            key = "loadflow_%s" % scen
            path = paths.get(key)
            need = True
            if path and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f) or {}
                    assert_report_context(s, data)
                    need = str(data.get("status") or "").lower() not in ("ok", "dry_run")
                except Exception as ex_existing:
                    need = True
                    notes.append("LF %s no reutilizable: %s" % (scen, ex_existing))
            if not need:
                notes.append("LF %s ya OK → omitido" % scen)
                continue
            notes.append("ejecutando LoadFlow %s…" % scen)
            res = run_load_flow(s, scenario=scen)
            lf_runs.append({"scenario": scen, "status": res.get("status"), "engine": res.get("engine")})
            if str(res.get("status") or "").lower() not in ("ok", "dry_run"):
                return {
                    "ok": False,
                    "error": "LoadFlow %s fallo: %s" % (scen, res.get("error") or res.get("status")),
                    "lf_runs": lf_runs,
                    "notes": notes,
                    "feeder_id": s.get("feeder_id"),
                    "informe_mode": mode,
                }

    manifest = fill_informe(
        s, overwrite_copy=True, require_delivery=require_delivery, informe_mode=mode
    )
    if not isinstance(manifest, dict):
        manifest = {"ok": False, "error": "fill_informe sin manifest"}

    manifest.setdefault("notes", [])
    if isinstance(manifest["notes"], list):
        manifest["notes"] = list(notes) + list(manifest["notes"])
    else:
        manifest["pre_notes"] = notes
    manifest["lf_runs"] = lf_runs
    manifest["delivery_mode"] = "deliver_informe"
    manifest["informe_mode"] = mode

    # Revision OCR rigurosa (hasta 3 rondas con correccion definitiva)
    do_review = ocr_review
    if do_review is None:
        do_review = bool(s.get("informe_ocr_review", True))
    else:
        do_review = bool(do_review)
    if do_review and manifest.get("ok"):
        try:
            from pipeline.review_informe_pdf import review_and_correct_informe
            notes.append("revision OCR del PDF (hasta %s rondas)…" % (
                s.get("informe_ocr_review_rounds") or ocr_review_rounds or 3
            ))
            ocr = review_and_correct_informe(s, max_rounds=int(s.get("informe_ocr_review_rounds") or ocr_review_rounds or 3))
            if isinstance(ocr, dict):
                ocr = tag_context(s, ocr)
            manifest["ocr_review"] = ocr
            manifest["notes"].append(
                "ocr_review: passed=%s rounds=%s errors_final=%s"
                % (
                    ocr.get("passed"),
                    ocr.get("rounds_done"),
                    (ocr.get("final") or {}).get("n_errors"),
                )
            )
            if not ocr.get("passed"):
                manifest["ok"] = False
                manifest["error"] = (
                    "Revision OCR no aprobada tras %s rondas (ver review_ocr.json)"
                    % ocr.get("rounds_done")
                )
                manifest["delivery_ready"] = False
            else:
                manifest["delivery_ready"] = True
                manifest.setdefault("notes", []).append("ocr_review PASSED")
        except Exception as ex:
            manifest["ocr_review"] = {"ok": False, "passed": False, "error": str(ex)}
            manifest["notes"].append("ocr_review error: %s" % ex)
            # No tumbar entrega por fallo de dependencia OCR si fill OK;
            # marcar warning en delivery
            manifest["ocr_review_failed"] = True

    try:
        st = delivery_status(s, mode=mode)
        manifest["delivery_status"] = st
        if st.get("delivery_ready") and manifest.get("ok") and manifest.get("ocr_review", {}).get("passed", True):
            manifest["delivery_ready"] = True
    except Exception as ex:
        manifest.setdefault("notes", []).append("aviso delivery_status: %s" % ex)
    return tag_context(s, manifest)


def main(argv=None):
    _ensure_src_path()
    ap = argparse.ArgumentParser(description="Entrega autonoma informe RECYM")
    ap.add_argument("--feeder", default=None, help="Alimentador (ej. AL209)")
    ap.add_argument("--ensure-lf", action="store_true", help="Correr LF §5 si faltan")
    ap.add_argument("--force-captures", action="store_true", help="Forzar capturas CYMDIST")
    ap.add_argument("--no-gate", action="store_true", help="No exigir gate de entrega")
    ap.add_argument("--no-ocr-review", action="store_true", help="Omitir revision OCR post-fill")
    ap.add_argument("--ocr-rounds", type=int, default=3, help="Rondas max revision OCR (1-3)")
    ap.add_argument(
        "--mode",
        choices=("completo", "situacional"),
        default="completo",
        help="completo=sit+proy; situacional=informe técnico estado situacional ED",
    )
    ap.add_argument("--json", action="store_true", help="Salida JSON completa")
    args = ap.parse_args(argv)

    from core.feeder_context import load_settings

    s = load_settings(feeder_id=args.feeder) if args.feeder else load_settings()
    res = deliver_informe(
        settings=s,
        ensure_lf=bool(args.ensure_lf),
        force_captures=bool(args.force_captures),
        require_delivery=not bool(args.no_gate),
        ocr_review=not bool(args.no_ocr_review),
        ocr_review_rounds=int(args.ocr_rounds or 3),
        informe_mode=args.mode,
    )
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        ok = bool(res.get("ok"))
        print("feeder:", res.get("feeder_id") or s.get("feeder_id"))
        print("ok:", ok)
        print("delivery_ready:", res.get("delivery_ready") or (res.get("delivery_status") or {}).get("delivery_ready"))
        ocr = res.get("ocr_review") or {}
        if ocr:
            print("ocr_passed:", ocr.get("passed"), "rounds:", ocr.get("rounds_done"))
        for n in (res.get("notes") or [])[:14]:
            try:
                print("-", n)
            except Exception:
                print("-", repr(n))
        if res.get("error"):
            print("error:", res.get("error"))
        paths = res.get("paths") or {}
        if paths.get("informe_doc") or paths.get("doc_informe"):
            print("docx:", paths.get("informe_doc") or paths.get("doc_informe"))
    raise SystemExit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
