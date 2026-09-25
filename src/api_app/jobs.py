# -*- coding: utf-8 -*-
"""Job runner en memoria + SSE para operaciones CYMDIST largas."""
from __future__ import print_function

import json
import os
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional

router = APIRouter()

_LOCK = threading.Lock()
_JOBS = {}  # type: Dict[str, dict]


class JobCreate(BaseModel):
    action: str = ""
    payload: Optional[Dict[str, Any]] = None
    feeder: Optional[str] = None

    class Config:
        extra = "allow"


def _set_job(job_id, **kwargs):
    with _LOCK:
        job = _JOBS.setdefault(job_id, {})
        job.update(kwargs)
        job["updated_at"] = time.time()
        return dict(job)


def get_job(job_id):
    with _LOCK:
        return dict(_JOBS.get(job_id) or {})


def _run_action(action, payload, feeder, job_id=None):
    """Ejecuta acciones conocidas reutilizando pipeline / Flask helpers."""
    payload = payload or {}
    from core.feeder_context import (
        load_settings,
        resolve_writable_study_path,
        apply_context_selection,
        feeder_family_code,
    )
    from pipeline.model_quality_gate import with_cympy_lock

    # Contexto §1 dinámico: BD + estudio del payload (no un alimentador fijo)
    fid = (feeder or "").strip() or (
        (payload.get("feeder") or payload.get("feeder_id") or "")
    )
    fid = str(fid or "").strip() or None
    db = (payload.get("database_mdb") or "").strip() or None
    st = (
        (payload.get("study_path") or payload.get("ui_study_path") or "")
    ).strip() or None
    if db or st or fid:
        try:
            ctx = apply_context_selection(
                database_mdb=db,
                study_path=st,
                feeder_id=fid,
                persist=True,
            )
            if ctx.get("feeder_id"):
                fid = ctx.get("feeder_id")
        except Exception as ex_ctx:
            print("AVISO apply_context job:", ex_ctx)

    s = load_settings(feeder_id=fid, synthesize=True) if fid else load_settings()
    # Overrides explicitos del job (estudio/BD/red de esta ejecucion)
    if db:
        s["database_mdb"] = db
        try:
            from core.cympy_adapter import find_cymdist_connection_for_mdb
            found = find_cymdist_connection_for_mdb(db)
            if found and found.get("name"):
                s["database_connection_name"] = found["name"]
        except Exception:
            pass
    if st:
        s["ui_study_path"] = st
        s["study_path"] = resolve_writable_study_path(st, s)
        s["study_file"] = os.path.basename(s["study_path"])
    elif s.get("study_path"):
        s["study_path"] = resolve_writable_study_path(s.get("study_path"), s)
    if payload.get("network_id"):
        s["network_id"] = payload.get("network_id")
    if fid:
        s["feeder_id"] = fid
        fam = feeder_family_code(fid)
        if fam and not s.get("network_id"):
            try:
                from core.feeder_context import lookup_bd_network_id
                nid = lookup_bd_network_id(fam, s)
                if nid:
                    s["network_id"] = nid
            except Exception:
                pass

    # Acciones que modifican / analizan CYMDIST: exigir BD + estudio del §1
    if action in (
        "calidad_diagnosticar",
        "calidad_proponer",
        "calidad_aplicar",
        "calidad_convergencia",
        "calidad_hasta_limpio",
        "distribucion",
        "flujo",
    ):
        if not (s.get("database_mdb") or "").strip():
            return {
                "ok": False,
                "error": "Falta base de datos (§1). Elija .mdb y pulse 1.1 Aplicar.",
            }
        if not (s.get("study_path") or "").strip():
            return {
                "ok": False,
                "error": "Falta estudio (§1). Elija estudio y pulse 1.1 Aplicar.",
            }
        try:
            from core.feeder_context import resolve_cymdist_binding
            bind = resolve_cymdist_binding(s)
            s["study_path"] = bind["study_path"]
            s["ui_study_path"] = bind.get("ui_study_path") or s.get("ui_study_path")
            s["database_mdb"] = bind["database_mdb"]
            s["database_connection_name"] = bind["database_connection_name"]
            s["_cymdist_binding"] = bind
        except Exception as ex_bind:
            return {"ok": False, "error": "Enlace estudio/BD CYMDIST: %s" % ex_bind}

    def _annotate_study(result):
        """Adjunta BD/estudio §1 al resultado de cualquier acción §2."""
        if not isinstance(result, dict):
            return result
        result.setdefault("feeder_id", s.get("feeder_id"))
        result.setdefault("network_id", s.get("network_id"))
        result["study_path"] = s.get("study_path") or result.get("study_path") or ""
        result["ui_study_path"] = (
            s.get("ui_study_path") or result.get("ui_study_path") or result["study_path"]
        )
        result["study_file"] = os.path.basename(
            result.get("ui_study_path") or result.get("study_path") or ""
        )
        result["database_mdb"] = s.get("database_mdb") or result.get("database_mdb") or ""
        result["database_connection_name"] = (
            s.get("database_connection_name") or result.get("database_connection_name") or ""
        )
        return result

    def _spa_system_diag_payload(result, label):
        """Normaliza 2.7/2.8 para la SPA (panel sistema/ELD, no tablero feeder)."""
        out = dict(result or {}) if isinstance(result, dict) else {"ok": False}
        summary = out.get("summary") if isinstance(out.get("summary"), dict) else {}
        n_prob = int(summary.get("n_problems") or 0)
        n_err = int(summary.get("n_errors") or 0)
        n_warn = int(summary.get("n_warnings") or 0)
        n_hint = int(summary.get("n_hints") or 0)
        n_ok = summary.get("n_networks_ok")
        n_fail = summary.get("n_networks_fail")
        n_req = summary.get("n_networks_requested") or summary.get("n_networks_loaded")
        if n_prob == 0 and not (summary.get("errors_by_net") or []):
            msg = (
                "%s · DiagnosticTool limpio (0 Error/Warning/Hint) · redes OK=%s/%s"
                % (label, n_ok, n_req)
            )
        else:
            msg = (
                "%s · problemas=%s · E=%s W=%s H=%s · redes OK=%s fail=%s"
                % (label, n_prob, n_err, n_warn, n_hint, n_ok, n_fail)
            )
        # per_feeder llega como dict {feeder_id: {...}} → lista ordenada para tablas SPA
        raw_pf = summary.get("per_feeder") or {}
        if isinstance(raw_pf, dict):
            per_feeder_list = []
            for fid, info in sorted(raw_pf.items(), key=lambda kv: (-int((kv[1] or {}).get("n_problems") or 0), str(kv[0]))):
                row = dict(info or {})
                row.setdefault("feeder_id", fid)
                row.setdefault("NetworkID", row.get("NetworkID") or row.get("network_id"))
                per_feeder_list.append(row)
        elif isinstance(raw_pf, list):
            per_feeder_list = list(raw_pf)
        else:
            per_feeder_list = []
        top = summary.get("top_errors") or []
        out["ok"] = bool(out.get("ok", True))
        out["msg"] = msg
        out["summary"] = summary
        # Alias tipados para Step2CalidadTablero (no usar tablero.json del feeder)
        out["system_diag"] = {
            "scope": summary.get("scope") or ("ELD_study" if "ELD" in label else "system"),
            "label": label,
            "n_problems": n_prob,
            "n_errors": n_err,
            "n_warnings": n_warn,
            "n_hints": n_hint,
            "n_networks_ok": n_ok,
            "n_networks_fail": n_fail,
            "n_networks_requested": n_req,
            "by_code": summary.get("by_code") or {},
            "per_feeder": per_feeder_list,
            "top_errors": top,
            "errors_by_net": summary.get("errors_by_net") or [],
            "csv": summary.get("csv") or out.get("csv"),
            "json": summary.get("json") or out.get("json"),
            "timestamp": summary.get("timestamp"),
            "ready": bool(
                summary.get("ready_model_system")
                if "ready_model_system" in summary
                else summary.get("ready_model_eld")
            ),
        }
        return out

    def _calidad(fn, timeout_sec=180.0):
        def _wrapped():
            print(
                "§2 %s · feeder=%s · estudio=%s · BD=%s"
                % (
                    action,
                    s.get("feeder_id"),
                    os.path.basename(s.get("ui_study_path") or s.get("study_path") or ""),
                    os.path.basename(s.get("database_mdb") or ""),
                )
            )
            return _annotate_study(fn())

        return with_cympy_lock(action, _wrapped, timeout_sec=float(timeout_sec))

    if action == "calidad_diagnosticar":
        from pipeline.model_quality_gate import run_network_diagnostic
        from core.feeder_context import output_path
        import shutil

        def _diag_and_tablero():
            result = run_network_diagnostic(s, suffix="")
            # 2.1 = estado actual: actualizar «antes» y alinear «después»
            summary = (result.get("summary") or {}) if isinstance(result, dict) else {}
            if isinstance(summary, dict):
                summary = dict(summary)
                summary["empty"] = False
                summary.setdefault("phase", "before")
            try:
                from pipeline.voltage_opt_recommendations import (
                    attach_recommendations_to_summary,
                )
                summary = attach_recommendations_to_summary(summary, settings=s)
            except Exception as ex_rec:
                print("AVISO recomendaciones tensión §7:", ex_rec)
            after_summary = dict(summary)
            after_summary["phase"] = "after"
            after_summary["empty"] = False
            before_path = output_path(s, "diagnostics", "dashboard_summary.json")
            after_path = output_path(s, "diagnostics", "dashboard_summary_after.json")
            after_csv = output_path(s, "diagnostics", "cymdist_diagnostic_errors_after.csv")
            before_csv = output_path(s, "diagnostics", "cymdist_diagnostic_errors.csv")
            try:
                os.makedirs(os.path.dirname(before_path), exist_ok=True)
                with open(before_path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, ensure_ascii=False)
                with open(after_path, "w", encoding="utf-8") as f:
                    json.dump(after_summary, f, indent=2, ensure_ascii=False)
                if os.path.isfile(before_csv):
                    shutil.copy2(before_csv, after_csv)
            except Exception as ex_w:
                print("AVISO persist summary tablero:", ex_w)
            try:
                from analysis.build_dashboard import main as build_tablero
                build_tablero(s)
                if isinstance(result, dict):
                    result["tablero_updated"] = True
            except Exception as ex_t:
                if isinstance(result, dict):
                    result["tablero_error"] = str(ex_t)
            if isinstance(result, dict):
                result["ok"] = True
                result["summary"] = summary
                result["voltage_opt"] = summary.get("voltage_opt")
                result["tablero"] = {
                    "before": summary,
                    "after": after_summary,
                    "total_messages": summary.get("total_messages"),
                    "by_code": summary.get("by_code"),
                    "top_errors": summary.get("top_errors"),
                    "n_problems": summary.get("n_problems"),
                    "has_diagnostic": True,
                    "voltage_opt": summary.get("voltage_opt"),
                }
                msg_base = (
                    "Diagnóstico OK · %s msgs · problemas=%s · tablero actualizado"
                    % (summary.get("total_messages"), summary.get("n_problems"))
                )
                if int(summary.get("n_problems") or 0) == 0:
                    msg_base = (
                        "Diagnóstico OK · DiagnosticTool limpio (0 Error/Warning/Hint) · tablero actualizado"
                    )
                vopt = summary.get("voltage_opt") or {}
                if vopt.get("triggered"):
                    msg_base += " · " + str(vopt.get("msg") or "")
                result["msg"] = msg_base
            return result

        return _calidad(_diag_and_tablero)

    if action == "calidad_proponer":
        from pipeline.model_quality_gate import propose_corrections
        return _calidad(lambda: propose_corrections(s))

    if action == "calidad_aplicar":
        from pipeline.model_quality_gate import apply_corrections, run_network_diagnostic
        from analysis.build_dashboard import main as build_tablero

        def _aplicar_y_tablero():
            applied = apply_corrections(s, fix_voltages=True)
            d = run_network_diagnostic(s, suffix="")
            summary = dict((d or {}).get("summary") or {})
            summary["empty"] = False
            summary.setdefault("phase", "after")
            try:
                from core.feeder_context import output_path
                import json, os, shutil
                path = output_path(s, "diagnostics", "dashboard_summary.json")
                after_path = output_path(s, "diagnostics", "dashboard_summary_after.json")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                shutil.copyfile(path, after_path)
                build_tablero(s)
            except Exception as ex_t:
                if isinstance(applied, dict):
                    applied["tablero_error"] = str(ex_t)
            if isinstance(applied, dict):
                applied["ok"] = applied.get("n_error", 1) == 0
                applied["summary"] = summary
                applied["tablero"] = {
                    "before": summary,
                    "after": summary,
                    "n_problems": summary.get("n_problems"),
                    "by_code": summary.get("by_code"),
                    "top_errors": summary.get("top_errors"),
                    "total_messages": summary.get("total_messages"),
                }
                n_prob = int(summary.get("n_problems") or 0)
                if n_prob == 0:
                    applied["msg"] = (
                        "Aplicado OK=%s ERR=%s · DiagnosticTool limpio (0 Error/Warning/Hint) · estudio guardado"
                        % (applied.get("n_ok"), applied.get("n_error"))
                    )
                else:
                    applied["msg"] = (
                        "Aplicado OK=%s ERR=%s · diag problemas=%s · estudio guardado"
                        % (applied.get("n_ok"), applied.get("n_error"), n_prob)
                    )
            return applied

        return _calidad(_aplicar_y_tablero)

    if action == "calidad_convergencia":
        from pipeline.model_quality_gate import check_convergence

        def _conv():
            r = check_convergence(s, run_lf=True)
            if not isinstance(r, dict):
                return r
            # Asegurar mensaje visible en SPA aunque check_convergence sea viejo
            if not r.get("msg"):
                conv = r.get("converge")
                fid = r.get("feeder_id") or s.get("feeder_id") or "?"
                if conv == "SI":
                    r["ok"] = True
                    r["msg"] = "2.4 · Converge = SI · alimentador %s" % fid
                elif conv == "NO":
                    r["ok"] = False
                    r["msg"] = "2.4 · Converge = NO · %s · %s" % (
                        fid, r.get("error") or "sin resultados válidos"
                    )
                else:
                    r["msg"] = "2.4 · Converge = %s · %s" % (conv or "—", fid)
            return r

        return _calidad(_conv)

    if action == "calidad_hasta_limpio":
        from pipeline.model_quality_gate import run_until_converges, run_network_diagnostic
        from analysis.build_dashboard import main as build_tablero

        def _hasta_limpio_tablero():
            result = run_until_converges(
                s,
                max_iters=int(payload.get("max_iters") or 4),
                skip_initial_lf=bool(payload.get("skip_initial_lf")),
            )
            try:
                d = run_network_diagnostic(s, suffix="")
                summary = dict((d or {}).get("summary") or {})
                summary["empty"] = False
                summary.setdefault("phase", "after")
                from core.feeder_context import output_path
                import json, os, shutil
                path = output_path(s, "diagnostics", "dashboard_summary.json")
                after_path = output_path(s, "diagnostics", "dashboard_summary_after.json")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
                shutil.copyfile(path, after_path)
                build_tablero(s)
                if isinstance(result, dict):
                    result["summary"] = summary
                    result["tablero"] = {
                        "before": summary,
                        "after": summary,
                        "n_problems": summary.get("n_problems"),
                        "by_code": summary.get("by_code"),
                        "top_errors": summary.get("top_errors"),
                        "ready_model": summary.get("ready_model"),
                        "total_messages": summary.get("total_messages"),
                    }
                    if summary.get("ready_model") or int(summary.get("n_problems") or 0) == 0:
                        result["ok"] = True
                        result["ready"] = True
                        result["msg"] = (
                            "Modelo limpio tras correcciones · DiagnosticTool limpio (0 Error/Warning/Hint) · estudio guardado"
                        )
                        result.pop("error", None)
                    elif not result.get("msg"):
                        result["msg"] = (
                            "2.6 · problemas=%s · msgs=%s · estudio guardado"
                            % (summary.get("n_problems"), summary.get("total_messages"))
                        )
            except Exception as ex_t:
                if isinstance(result, dict):
                    result["tablero_error"] = str(ex_t)
            return result

        return _calidad(_hasta_limpio_tablero)

    if action == "calidad_sistema":
        from pipeline.model_quality_gate import run_system_network_diagnostic

        def _sistema():
            result = run_system_network_diagnostic(
                s,
                limit=int(payload.get("limit") or 0),
                network_ids=payload.get("networks") or None,
            )
            return _annotate_study(_spa_system_diag_payload(result, "2.7 Sistema"))

        return _calidad(_sistema, timeout_sec=3600.0)

    if action == "calidad_eld":
        from pipeline.model_quality_gate import run_eld_network_diagnostic

        def _eld():
            result = run_eld_network_diagnostic(
                s,
                limit=int(payload.get("limit") or 0),
                network_ids=payload.get("networks") or None,
            )
            return _annotate_study(_spa_system_diag_payload(result, "2.8 ELD"))

        return _calidad(_eld, timeout_sec=3600.0)

    if action == "distribucion":
        from pipeline.run_demand_allocation import seed_session_from_excel, run_load_allocation_module

        def _run():
            if s.get("dry_run"):
                return {"ok": True, "dry_run": True}
            sess = seed_session_from_excel(s)
            if sess.get("P_kW") in (None, ""):
                return {"ok": False, "error": "Defina y guarde la demanda de cabecera (§1)."}
            # Progreso parcial al job SSE
            def _prog(msg):
                try:
                    jid = job_id or payload.get("_job_id")
                    if jid:
                        _set_job(jid, message="3.3 · %s" % msg)
                except Exception:
                    pass
            s2 = dict(s)
            s2["_job_progress"] = _prog
            s2["skip_db_project_save"] = True
            # Mapas de selección §3 (Incluir / Restar cab.) desde la SPA
            if payload.get("activo") is not None:
                s2["_activo_map"] = payload.get("activo")
            if payload.get("restar_cabecera") is not None:
                s2["_restar_map"] = payload.get("restar_cabecera")
            # Forzar enlace estudio+BD del alimentador activo (cualquier radial)
            try:
                from core.feeder_context import resolve_cymdist_binding
                bind = resolve_cymdist_binding(s2)
                s2["study_path"] = bind["study_path"]
                s2["database_mdb"] = bind["database_mdb"]
                s2["database_connection_name"] = bind["database_connection_name"]
            except Exception as ex_bind:
                return {"ok": False, "error": "Enlace estudio/BD: %s" % ex_bind}
            result = run_load_allocation_module(
                s2,
                sess,
                activo_map=payload.get("activo"),
                restar_map=payload.get("restar_cabecera"),
            )
            summary = {k: result[k] for k in result if k not in ("scaled", "applied")}
            summary["n_scaled"] = len(result.get("scaled") or [])
            summary["n_applied"] = len(result.get("applied") or [])
            if result.get("cymdist_binding"):
                summary["cymdist_binding"] = result["cymdist_binding"]
            val = result.get("validation") or {}
            # Incluir resumen de validacion (sin todas las filas en SSE)
            if isinstance(val, dict) and val:
                fails = [r for r in (val.get("rows") or []) if r.get("Estado") == "FAIL"][:30]
                summary["validation"] = {
                    "ok": val.get("ok"),
                    "msg": val.get("msg") or val.get("error"),
                    "n_ok": val.get("n_ok"),
                    "n_warn": val.get("n_warn"),
                    "n_fail": val.get("n_fail"),
                    "n_zero_fixed": val.get("n_zero_fixed"),
                    "n_zero_residual": val.get("n_zero_residual"),
                    "sum_kw": val.get("sum_kw"),
                    "P_cabecera_kW": val.get("P_cabecera_kW"),
                    "balance_ok": val.get("balance_ok"),
                    "balance_msg": val.get("balance_msg"),
                    "fails": fails,
                }
            ok = result.get("status") in (
                "ok", "ok_with_warnings", "ok_validation_fail", "dry_run"
            )
            if result.get("status") == "error" or result.get("allocation_ok") is False:
                ok = False
            method = str(result.get("method") or "")
            if method.startswith("cymdist_COM") or result.get("engine") == "COM":
                prefix = "LoadAllocation CYMDIST (COM) OK"
            elif method.startswith("cymdist_"):
                prefix = "LoadAllocation CYMDIST (API) OK"
            elif result.get("status") == "error":
                prefix = "LoadAllocation CYMDIST FALLO (sin redistribuir en RECYM)"
            else:
                prefix = "LoadAllocation CYMDIST"
            return {
                "ok": ok,
                "result": summary,
                "validation_ok": result.get("validation_ok"),
                "error": None if ok else (result.get("allocation_error") or result.get("aviso")),
                "msg": (
                    prefix + " · " + str((val or {}).get("msg") or (val or {}).get("balance_msg") or "sin validacion")
                    if ok else None
                ),
            }

        return _calidad(_run, timeout_sec=300.0)

    if action == "flujo":
        from pipeline.run_load_flow import run_load_flow
        from pipeline.deliver_informe import deliver_informe
        scenario = (payload.get("scenario") or "").strip().lower() or None
        update_informe = payload.get("update_informe", True)
        # Tras proyectado (o si piden captura) la entrega incluye coloreo §5.
        deliver_complete = payload.get("deliver_complete")
        if deliver_complete is None:
            deliver_complete = (scenario == "proyectado") or (not scenario)

        def _run():
            def _prog(msg):
                try:
                    jid = job_id or payload.get("_job_id")
                    if jid:
                        label = "5.1" if scenario == "situacional" else (
                            "5.2" if scenario == "proyectado" else "5"
                        )
                        _set_job(jid, message="%s · %s" % (label, msg))
                except Exception:
                    pass
            s2 = dict(s)
            s2["_job_progress"] = _prog
            s2["skip_db_project_save"] = True
            # Forzar enlace estudio+BD del §1 (misma BD/estudio que cabecera)
            try:
                from core.feeder_context import resolve_cymdist_binding
                bind = resolve_cymdist_binding(s2)
                s2["study_path"] = bind["study_path"]
                s2["ui_study_path"] = bind.get("ui_study_path") or s2.get("ui_study_path")
                s2["database_mdb"] = bind["database_mdb"]
                s2["database_connection_name"] = bind["database_connection_name"]
            except Exception as ex_bind:
                return {"ok": False, "error": "Enlace estudio/BD: %s" % ex_bind}
            result = run_load_flow(s2, scenario=scenario)
            ok = result.get("status") in ("ok", "dry_run")
            informe = None
            if ok and update_informe:
                try:
                    if deliver_complete:
                        _prog("entregando informe completo (capturas §5 + Word/Excel)…")
                        informe = deliver_informe(
                            s2,
                            ensure_lf=False,
                            force_captures=bool(payload.get("force_captures", False)),
                            require_delivery=bool(payload.get("require_delivery", False)),
                            informe_mode=payload.get("informe_mode")
                            or payload.get("mode")
                            or ("situacional" if scenario == "situacional" else "completo"),
                        )
                    else:
                        # Tras 5.1: actualizar cuadros sin re-capturar el par completo
                        # (la captura viva se hace en 5.2 / §6 armar).
                        _prog("actualizando cuadros informe (sin recaptura completa)…")
                        from pipeline.fill_informe import fill_informe
                        s2["informe_auto_cymdist_capture"] = False
                        s2["force_cymdist_captures"] = False
                        informe = fill_informe(
                            s2, overwrite_copy=True, require_delivery=False
                        )
                except Exception as ex_inf:
                    informe = {"ok": False, "error": str(ex_inf)}
            study_name = os.path.basename(
                s2.get("ui_study_path") or s2.get("study_path") or ""
            )
            return {
                "ok": ok,
                "result": result,
                "error": None if ok else (result.get("error") or "LoadFlow fallo"),
                "informe": informe,
                "study_path": s2.get("study_path"),
                "ui_study_path": s2.get("ui_study_path"),
                "database_mdb": s2.get("database_mdb"),
                "msg": (
                    ("LoadFlow %s OK · %s · estudio %s" % (
                        scenario or "general",
                        result.get("engine") or "",
                        study_name or "—",
                    )) if ok else None
                ),
            }

        # LF + capturas CYMDIST + Word puede superar 5 min
        return _calidad(_run, timeout_sec=720.0 if (update_informe and deliver_complete) else 300.0)

    if action == "build_tablero":
        from analysis.build_dashboard import main as build_tablero
        build_tablero()
        return {"ok": True, "msg": "tablero regenerado"}

    raise ValueError("Acción desconocida: %s" % action)


def run_action_inprocess(action, payload, feeder, job_id=None):
    """API pública para el worker CLI (siempre in-process en el hijo)."""
    return _run_action(action, payload, feeder, job_id=job_id)


def _worker(job_id, action, payload, feeder):
    _set_job(job_id, status="running", message="Ejecutando %s…" % action)
    try:
        payload = dict(payload or {})
        payload["_job_id"] = job_id

        # Ledger campaña v7 (best-effort)
        try:
            from app.orchestrator import register_legacy_job, complete_legacy_job
            register_legacy_job(feeder or "", action, payload, job_id)
        except Exception as ex_led:
            print("AVISO campaign ledger:", ex_led)

        use_iso = False
        try:
            from core.cympy_isolation import should_isolate_action, run_job_action_isolated

            use_iso = should_isolate_action(action)
        except Exception as ex_iso:
            print("AVISO isolation:", ex_iso)
            use_iso = False

        if use_iso:
            def _prog(msg):
                try:
                    _set_job(job_id, message=msg)
                except Exception:
                    pass

            timeout = 600.0
            if action in ("distribucion", "flujo", "calidad_hasta_limpio", "calidad_sistema", "calidad_eld"):
                timeout = 900.0
            result = run_job_action_isolated(
                action,
                payload=payload,
                feeder=feeder,
                timeout=timeout,
                progress_cb=_prog,
            )
        else:
            result = _run_action(action, payload, feeder, job_id=job_id)

        ok = True
        if isinstance(result, dict) and result.get("ok") is False:
            ok = False
        msg = "Listo"
        if isinstance(result, dict):
            msg = result.get("msg") or result.get("error") or ("Listo" if ok else "Error")
            if result.get("isolated") and ok:
                msg = (msg or "Listo") + " · aislado"
        _set_job(
            job_id,
            status="ok" if ok else "error",
            message=msg,
            result=result,
        )
        try:
            from app.orchestrator import complete_legacy_job
            complete_legacy_job(
                job_id,
                ok=ok,
                result=result,
                error=None if ok else (
                    (result or {}).get("error") if isinstance(result, dict) else str(result)
                ),
                message=msg,
            )
        except Exception as ex_done:
            print("AVISO complete ledger:", ex_done)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        _set_job(job_id, status="error", message=str(ex), result={"ok": False, "error": str(ex)})
        try:
            from app.orchestrator import complete_legacy_job
            complete_legacy_job(job_id, ok=False, error=str(ex), message=str(ex))
        except Exception:
            pass


@router.post("")
def create_job(body: JobCreate):
    action = (body.action or "").strip()
    if not action:
        raise HTTPException(400, "action requerido")
    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id,
        id=job_id,
        action=action,
        status="queued",
        message="En cola",
        result=None,
        created_at=time.time(),
    )
    t = threading.Thread(
        target=_worker,
        args=(job_id, action, body.payload, body.feeder),
        name="job-%s" % job_id,
        daemon=True,
    )
    t.start()
    return {"ok": True, "job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "job no encontrado")
    return {"ok": True, "job": job}


@router.get("/{job_id}/events")
def job_events(job_id: str):
    if not get_job(job_id):
        raise HTTPException(404, "job no encontrado")

    def event_stream():
        last = None
        while True:
            job = get_job(job_id)
            payload = json.dumps(job, ensure_ascii=False, default=str)
            if payload != last:
                last = payload
                yield "data: %s\n\n" % payload
            if job.get("status") in ("ok", "error"):
                yield "event: done\ndata: %s\n\n" % payload
                break
            time.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
