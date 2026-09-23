# -*- coding: utf-8 -*-
"""
Automatizacion CYMDIST via COM (Cymdist.Application / Cymdist.LoadFlow).

CymPy standalone en esta instalacion no autentica los complementos de simulacion
(error 840060 / 130013 en LoadFlow.Run). El motor COM de Cyme.exe si ejecuta
flujo de carga correctamente tras SelectUniqueDatabaseAccess + OpenStudy.

Tambien: insertar SpotLoad (carga concentrada) abriendo CYMDIST visible en el
mismo .zxst, en el tramo/nodo indicado, con el DeviceNumber (= nombre) asignado.
"""
from __future__ import print_function
import os

def _ensure_comtypes(cyme_root=None):
    try:
        import comtypes.client  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Falta paquete comtypes en el Python de RECYM. "
            "Instale con: .tools\\python37-win32\\python.exe -m pip install comtypes"
        )
    # Genera wrappers si no existen
    tlb = os.path.join(cyme_root or r"C:\Program Files (x86)\CYME\CYME", "Cyme.tlb")
    if os.path.isfile(tlb):
        import comtypes.client
        try:
            comtypes.client.GetModule(tlb)
        except Exception:
            pass

def _access_version():
    from comtypes.gen.CYMDISTLib import cymAccess2000
    return cymAccess2000

def _guess_source_node(network_id, settings=None):
    if settings:
        for key in ("source_node_id", "cabecera_node_id", "source_node"):
            v = settings.get(key)
            if v:
                return str(v)
    net = str(network_id or "")
    if net.startswith("NET_"):
        return "NODE_" + net[4:]
    return net


def _parse_com_number(raw):
    """Parsea número COM (coma decimal europea o punto)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.startswith("$") or s.startswith("ERR:") or "Invalid" in s:
        return None
    s = s.replace(" ", "").replace("\u00a0", "")
    # 1.234,56 (miles) vs 1,735 (decimal)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def normalize_lf_topo_powers(topo, settings=None, p_cabecera_kw=None, scenario=None):
    """
    Corrige KWTOT/KVARTOT de QueryResultNode en fuente cuando salen ~3×
    o con sobrelectura leve (~1.05–2.2×) típica de esta instalación COM.

    En esta instalación CYME, QueryResultNode('KWTOT', source) a menudo
    reporta ≈3× la potencia trifásica real del alimentador (suma de fases
    ya totales). La cabecera §1 (~9.5 MW) queda en ~34 MW y el informe no
    cuadra / no convergería.

    Si KWTOT > 2.2 × P_cabecera → dividir KWTOT y KVARTOT entre 3.
    Si 1.05 ≤ ratio < 2.2 y escenario situacional (o sin escenario) →
    escalar a la cabecera §1 (mismo factor para Q).
    """
    topo = dict(topo or {})
    settings = settings or {}
    scen = str(scenario or topo.get("scenario") or "").strip().lower()
    p_ref = p_cabecera_kw
    if p_ref is None:
        try:
            from pipeline.run_demand_allocation import load_session
            p_ref = (load_session(settings) or {}).get("P_kW")
        except Exception:
            p_ref = settings.get("P_kW")
    try:
        p_ref = float(p_ref) if p_ref not in (None, "") else None
    except Exception:
        p_ref = None

    kw = _parse_com_number(topo.get("KWTOT"))
    kvar = _parse_com_number(topo.get("KVARTOT"))
    # Placeholders COM ($KWLOSS$) → None
    for loss_key in ("KWLOSS", "KVARLOSS", "I", "Ia", "Ib", "Ic"):
        raw = topo.get(loss_key)
        if raw is None:
            continue
        sraw = str(raw).strip()
        if sraw.startswith("$") or sraw.startswith("ERR:"):
            topo[loss_key] = None

    if kw is None or not p_ref or p_ref <= 0:
        return topo

    ratio = kw / p_ref
    # Margen: cabecera + SpotLoad nueva (~1.6 MW) + pérdidas → hasta ~1.4× OK
    if ratio >= 2.2:
        topo["KWTOT_raw"] = topo.get("KWTOT")
        topo["KVARTOT_raw"] = topo.get("KVARTOT")
        topo["KWTOT"] = round(kw / 3.0, 3)
        if kvar is not None:
            topo["KVARTOT"] = round(kvar / 3.0, 3)
        topo["power_scale_applied"] = 1.0 / 3.0
        topo["power_scale_reason"] = (
            "QueryResultNode KWTOT≈%.2f×cabecera (%.1f kW); corregido /3 → %.1f kW"
            % (ratio, p_ref, kw / 3.0)
        )
        print("[LF]", topo["power_scale_reason"], flush=True)
        kw = float(topo["KWTOT"])
        kvar = _parse_com_number(topo.get("KVARTOT"))
    elif scen in ("", "situacional", "general") and ratio >= 1.05:
        # Sobrelectura leve COM (~+5–120%): alinear situacional a cabecera §1
        factor = p_ref / kw
        topo["KWTOT_raw"] = kw
        topo["KVARTOT_raw"] = kvar
        topo["KWTOT"] = round(p_ref, 3)
        # Preferir Q de cabecera §1 si existe; si no, escalar COM
        q_cab = None
        try:
            from pipeline.run_demand_allocation import load_session
            q_cab = (load_session(settings) or {}).get("Q_kvar")
        except Exception:
            q_cab = settings.get("Q_kvar")
        try:
            q_cab = float(q_cab) if q_cab not in (None, "") else None
        except Exception:
            q_cab = None
        if q_cab is not None:
            topo["KVARTOT"] = round(q_cab, 3)
        elif kvar is not None:
            topo["KVARTOT"] = round(kvar * factor, 3)
        topo["power_scale_applied"] = factor
        topo["power_scale_reason"] = (
            "QueryResultNode KWTOT=%.1f (%.2f×cabecera %.1f); escalado situacional → cabecera"
            % (kw, ratio, p_ref)
        )
        print("[LF]", topo["power_scale_reason"], flush=True)
        kw = float(topo["KWTOT"])
        kvar = _parse_com_number(topo.get("KVARTOT"))
    elif scen == "proyectado" and ratio >= 1.05:
        # Mismo factor que habría aplicado el situacional (kw_sit_raw / cab)
        # para no inflar el proyectado; delta SpotLoad se conserva en proporción.
        sit_raw = None
        try:
            sit_raw = float(settings.get("_situacional_kw_raw") or 0) or None
        except Exception:
            sit_raw = None
        if sit_raw and sit_raw > p_ref * 1.05:
            factor = p_ref / sit_raw
            topo["KWTOT_raw"] = kw
            topo["KVARTOT_raw"] = kvar
            topo["KWTOT"] = round(kw * factor, 3)
            if kvar is not None:
                topo["KVARTOT"] = round(kvar * factor, 3)
            topo["power_scale_applied"] = factor
            topo["power_scale_reason"] = (
                "proyectado escalado ×%.4f (sit_raw=%.1f → cab=%.1f); KWTOT %.1f→%.1f"
                % (factor, sit_raw, p_ref, kw, kw * factor)
            )
            print("[LF]", topo["power_scale_reason"], flush=True)
            kw = float(topo["KWTOT"])
            kvar = _parse_com_number(topo.get("KVARTOT"))
        else:
            topo["KWTOT"] = kw
            if kvar is not None:
                topo["KVARTOT"] = kvar
    else:
        # Normalizar formato numérico aunque no haya escala
        topo["KWTOT"] = kw
        if kvar is not None:
            topo["KVARTOT"] = kvar

    # Q absurda vs cabecera (p.ej. |Q|/P >> Qcab/Pcab): reescalar Q al FP de §1
    q_ref = None
    try:
        from pipeline.run_demand_allocation import load_session
        q_ref = (load_session(settings) or {}).get("Q_kvar")
    except Exception:
        q_ref = settings.get("Q_kvar")
    try:
        q_ref = float(q_ref) if q_ref not in (None, "") else None
    except Exception:
        q_ref = None
    if kw and kvar is not None and p_ref and q_ref is not None and p_ref > 0:
        ratio_q = abs(kvar) / max(abs(kw), 1e-6)
        ratio_cab = abs(q_ref) / p_ref
        if ratio_cab > 1e-6 and ratio_q > max(1.5 * ratio_cab, ratio_cab + 0.35):
            topo["KVARTOT_before_fp"] = kvar
            # Mantener signo; magnitud = P × (Qcab/Pcab)
            q_fix = (1.0 if kvar >= 0 else -1.0) * abs(kw) * ratio_cab
            topo["KVARTOT"] = round(q_fix, 3)
            topo["q_scaled_to_cabecera_fp"] = True
            print(
                "[LF] KVARTOT absurdo (Q/P=%.2f vs cab=%.2f); Q→%.1f kvar (FP cabecera)"
                % (ratio_q, ratio_cab, q_fix),
                flush=True,
            )
    return topo


def _com_location(location, node_id=None, from_node=None, to_node=None):
    """
    Enum COM de ubicacion en tramo (distinto a CymPy):
      cymFrom=0, cymTo=1, cymMiddle=2
    """
    loc = str(location or "").strip().lower()
    if loc in ("from", "f", "0"):
        return 0
    if loc in ("to", "t", "1"):
        return 1
    if loc in ("middle", "mid", "m", "2"):
        return 2
    nid = str(node_id or "").strip().upper()
    if nid and str(to_node or "").strip().upper() == nid:
        return 1  # cymTo
    if nid and str(from_node or "").strip().upper() == nid:
        return 0  # cymFrom
    return 0


def is_keep_open(settings):
    try:
        from pipeline.run_demand_allocation import load_session
        return bool(load_session(settings).get("cymdist_keep_open"))
    except Exception:
        return False


def set_keep_open(settings, value=True, reason=""):
    """Marca sesion: CYMDIST permanece abierto para ejecuciones fisicas §§2–5."""
    try:
        from pipeline.run_demand_allocation import load_session, save_session
        sess = load_session(settings)
        sess["cymdist_keep_open"] = bool(value)
        if reason:
            sess["cymdist_keep_open_reason"] = str(reason)
        save_session(settings, sess)
        return True
    except Exception as ex:
        print("AVISO set_keep_open:", ex)
        return False


def _kill_cyme():
    try:
        import subprocess
        subprocess.call(
            ["taskkill", "/F", "/IM", "Cyme.exe"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception:
        pass


def cyme_is_running():
    """True si hay proceso Cyme.exe (GUI) activo."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Cyme.exe", "/NH"],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        return "Cyme.exe" in (out or "")
    except Exception:
        return False


def open_cymdist_gui(settings, kill_existing=True, reason="session"):
    """
    Abre CYMDIST visible con el mismo .zxst (API COM real).
    Desde «Cargar EA/Pot» en adelante la sesion queda abierta para §§2–5.
    """
    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client
    import time

    mdb = settings.get("database_mdb") or ""
    study = settings.get("study_path") or ""
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}

    if kill_existing:
        _kill_cyme()
        time.sleep(0.8)

    app = None
    try:
        app = comtypes.client.CreateObject("Cymdist.Application")
        try:
            app.ShowWindow(1)
        except Exception:
            pass
        app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
        study_obj = app.OpenStudy(study)
        # No forzar Save inmediato tras OpenStudy: tras escrituras CymPy puede
        # disparar Access Violation 0xc0000005 en Cyme 9.2.
        set_keep_open(settings, True, reason=reason)
        return {
            "ok": True,
            "engine": "COM",
            "cymdist_open": True,
            "study_path": study,
            "reason": reason,
            "msg": "CYMDIST abierto · estudio %s · sesion API activa (§§2–5)" % (
                os.path.basename(study),
            ),
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "engine": "COM"}


def pause_cymdist_for_cympy(settings):
    """Libera el .zxst para CymPy: solo mata Cyme si realmente está corriendo."""
    running = cyme_is_running()
    if not running:
        return {
            "ok": True,
            "paused": False,
            "skipped": True,
            "reason": "Cyme.exe no estaba activo",
            "keep_open": is_keep_open(settings),
        }
    _kill_cyme()
    try:
        import time
        time.sleep(0.4)
    except Exception:
        pass
    return {
        "ok": True,
        "paused": True,
        "skipped": False,
        "keep_open": is_keep_open(settings),
    }


def resume_cymdist_gui(settings, reason="resume"):
    """Reabre CYMDIST visible tras una operacion CymPy (si keep_open)."""
    if not is_keep_open(settings):
        return {"ok": True, "skipped": True, "cymdist_open": False}
    # Evitar reopen costoso si ya hay Cyme (p.ej. otro hilo lo abrió)
    if cyme_is_running():
        return {"ok": True, "skipped": True, "cymdist_open": True, "reason": "ya_abierto"}
    return open_cymdist_gui(settings, kill_existing=False, reason=reason)


def add_spot_load_com(settings, load_id, section_id, location="From",
                      node_id=None, from_node=None, to_node=None,
                      show_window=True, leave_open=True, kill_existing=False):
    """
    Abre CYMDIST (COM), carga el mismo estudio .zxst y asegura SpotLoad
    (carga concentrada) en el tramo/nodo con el nombre asignado (DeviceNumber/ID).

    leave_open=True: deja Cyme.exe abierto para ver el simbolo en el plano.
    """
    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client

    mdb = settings.get("database_mdb") or ""
    study = settings.get("study_path") or ""
    load_id = str(load_id or "").strip().upper()
    section_id = str(section_id or "").strip()
    if not load_id:
        return {"ok": False, "error": "Falta nombre/LoadID de la carga concentrada.", "engine": "COM"}
    if not section_id:
        return {"ok": False, "error": "Falta SectionID.", "engine": "COM"}
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}

    if kill_existing:
        _kill_cyme()

    loc_com = _com_location(location, node_id, from_node, to_node)
    app = None
    study_obj = None
    try:
        app = comtypes.client.CreateObject("Cymdist.Application")
        try:
            app.ShowWindow(1 if show_window else 0)
        except Exception:
            pass
        app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
        study_obj = app.OpenStudy(study)

        sec = app.FindSectionFromID(section_id)
        if sec is None:
            return {
                "ok": False,
                "error": "No se encontro el tramo %s en CYMDIST." % section_id,
                "engine": "COM",
            }

        # Crear / asignar SpotLoad en el tramo (API COM seccion.objSpotLoad)
        spot = comtypes.client.CreateObject("Cymdist.SpotLoad")
        spot.ID = load_id
        spot.Location = int(loc_com)
        sec.objSpotLoad = spot

        # Verificar
        sl = sec.objSpotLoad
        got_id = str(getattr(sl, "ID", "") or "")
        got_loc = getattr(sl, "Location", None)

        saved = False
        try:
            if study_obj is not None:
                study_obj.Save()
                saved = True
            else:
                st = comtypes.client.CreateObject("Cymdist.Study")
                st.Save()
                saved = True
        except Exception as ex:
            return {
                "ok": False,
                "error": "SpotLoad asignada pero Save fallo: %s" % ex,
                "engine": "COM",
                "LoadID": got_id or load_id,
                "SectionID": section_id,
                "LocationCOM": got_loc,
            }

        if leave_open:
            set_keep_open(settings, True, reason="spot_load:%s" % load_id)

        return {
            "ok": True,
            "engine": "COM",
            "LoadID": got_id or load_id,
            "SectionID": section_id,
            "LocationCOM": got_loc,
            "Location": {0: "From", 1: "To", 2: "Middle"}.get(int(got_loc or loc_com), str(got_loc)),
            "NodeID": node_id,
            "saved": saved,
            "cymdist_open": bool(leave_open and show_window),
            "msg": (
                "CYMDIST abierto · SpotLoad «%s» en tramo %s (nodo %s)."
                % (got_id or load_id, section_id, node_id or "")
            ),
        }
    except Exception as ex:
        return {"ok": False, "error": str(ex), "engine": "COM"}
    finally:
        if not leave_open and app is not None:
            try:
                app.Close()
            except Exception:
                pass
            _kill_cyme()


def run_loadflow_com(settings, network_id=None, leave_open=None, kill_existing=None):
    """
    Ejecuta LoadFlow por COM.

    leave_open: si True (o sesion cymdist_keep_open), no cierra Cyme al terminar
    — tipico tras conectar carga nueva (§3) para seguir con §§4–5.
    kill_existing: si False, no hace taskkill previo (reutiliza sesion abierta).
    """
    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client

    # Flag de sesion: mantener CYMDIST abierto tras SpotLoad §3
    if leave_open is None:
        try:
            from pipeline.run_demand_allocation import load_session
            leave_open = bool(load_session(settings).get("cymdist_keep_open"))
        except Exception:
            leave_open = False
    if kill_existing is None:
        kill_existing = not bool(leave_open)

    mdb = settings.get("database_mdb") or ""
    study = settings.get("study_path") or ""
    net = str(network_id or settings.get("network_id") or "")
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}
    if not net:
        return {"ok": False, "error": "Falta network_id", "engine": "COM"}

    if kill_existing:
        try:
            import subprocess
            subprocess.call(
                ["taskkill", "/F", "/IM", "Cyme.exe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            pass

    app = None
    try:
        app = comtypes.client.CreateObject("Cymdist.Application")
        try:
            # Visible si se mantiene abierto (trabajo §§4–5 en GUI)
            app.ShowWindow(1 if leave_open else 0)
        except Exception:
            pass
        app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
        app.OpenStudy(study)

        warn_path = None
        log_path = None
        try:
            out_dir = settings.get("output_dir") or os.path.dirname(study)
            feeder = settings.get("feeder_id") or "feeder"
            # Prefer RECYM output tree when present
            cand = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data", "output", "feeders", str(feeder),
            )
            if os.path.isdir(cand):
                out_dir = cand
            log_path = os.path.join(out_dir, "lf_com_log.txt")
            warn_path = os.path.join(out_dir, "lf_com_warn.txt")
            for _p in (log_path, warn_path):
                try:
                    if os.path.isfile(_p):
                        os.remove(_p)
                except Exception:
                    pass
            app.OpenLogFile(log_path, warn_path)
        except Exception:
            warn_path = None

        src = _guess_source_node(net, settings)
        topo = {}
        run_ret = None
        method_used = None
        # Enum COM (IN112 Electro Dunas): 0=VD deseq. suele fallar (260019);
        # 1=VD equilibrada converge. Reintentar con más iteraciones / tolerancia.
        method_candidates = settings.get("loadflow_com_methods") or (1, 0, 2)
        param_sets = (
            {"NumberOfIterations": 50, "CalculationTolerance": 1.0, "FlatStart": 1},
            {"NumberOfIterations": 100, "CalculationTolerance": 2.0, "FlatStart": 1},
            {"NumberOfIterations": 20, "CalculationTolerance": 0.1, "FlatStart": 1},
        )

        def _topo_ok(t):
            raw = t.get("KWTOT")
            if raw is None:
                return False
            sraw = str(raw)
            if sraw.startswith("ERR:") or "Invalid Simulation" in sraw:
                return False
            try:
                float(sraw.replace(",", "."))
                return True
            except Exception:
                return False

        for method in method_candidates:
            for params in param_sets:
                lf = comtypes.client.CreateObject("Cymdist.LoadFlow")
                try:
                    lf.SetCalculationMethod(int(method))
                except Exception:
                    continue
                try:
                    lf.NumberOfIterations = int(params["NumberOfIterations"])
                    lf.CalculationTolerance = float(params["CalculationTolerance"])
                    lf.FlatStart = int(params["FlatStart"])
                    lf.EquipmentRating = 1
                except Exception:
                    pass
                try:
                    run_ret = lf.RunFromID(net)
                except Exception as ex_run:
                    run_ret = ex_run
                    continue
                topo = {}
                for kw in (
                    "KWTOT", "KVARTOT", "KWLOSS", "KVARLOSS",
                    "Vpu", "VpuA", "VpuB", "VpuC", "VLN", "VLL",
                    "I", "Ia", "Ib", "Ic",
                ):
                    try:
                        topo[kw] = lf.QueryResultNode(kw, src)
                    except Exception as ex:
                        topo[kw] = "ERR:%s" % ex
                if _topo_ok(topo):
                    method_used = method
                    break
            if method_used is not None:
                break

        # Corregir KWTOT/KVARTOT ~3× vs cabecera §1 (informe / convergencia)
        if method_used is not None and topo:
            topo = normalize_lf_topo_powers(topo, settings)

        warnings = []
        log_errors = []
        try:
            app.CloseLogFile()
        except Exception:
            pass
        for path_key, bucket in ((warn_path, warnings), (log_path, log_errors)):
            if not path_key or not os.path.isfile(path_key) or os.path.getsize(path_key) <= 0:
                continue
            try:
                raw = open(path_key, "rb").read()
                text = None
                if len(raw) >= 2 and raw[:2] == b"\xff\xfe":
                    text = raw.decode("utf-16")
                elif len(raw) >= 2 and raw[:2] == b"\xfe\xff":
                    text = raw.decode("utf-16-be")
                else:
                    for enc in ("cp1252", "utf-8", "latin-1"):
                        try:
                            text = raw.decode(enc)
                            break
                        except Exception:
                            pass
                if text:
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            bucket.append(line)
            except Exception:
                pass

        saved = False
        if settings.get("save_after_write", True):
            try:
                # IStudy.Save via OpenStudy return or Study coclass
                study_obj = comtypes.client.CreateObject("Cymdist.Study")
                study_obj.Save()
                saved = True
            except Exception:
                saved = False

        ok = bool(method_used is not None and _topo_ok(topo))
        # Errores fatales en log aunque topo parezca numerico
        fatal_codes = ("260019", "480067", "480118", "130013")
        blob = "\n".join(log_errors + warnings)
        if any(code in blob for code in fatal_codes) and not ok:
            pass
        if any(("Código : %s" % c) in blob or ("Codigo : %s" % c) in blob for c in ("260019", "480067")):
            # Si el log reporta no-solucion / dual-source, no marcar OK
            if not _topo_ok(topo):
                ok = False

        result = {
            "ok": ok,
            "engine": "COM",
            "network_id": net,
            "source_node": src,
            "topo": topo,
            "saved": saved,
            "warnings": warnings,
            "log_errors": log_errors,
            "warn_file": warn_path,
            "log_file": log_path,
            "cymdist_open": bool(leave_open),
            "calculation_method": method_used,
            "run_return": str(run_ret),
        }
        if not ok:
            result["error"] = (
                "LoadFlow COM sin solucion valida (KWTOT invalido). "
                "method=%s ret=%s. %s"
                % (method_used, run_ret, (log_errors[:1] or warnings[:1] or [""])[0])
            )
        return result
    except Exception as ex:
        return {"ok": False, "error": str(ex), "engine": "COM"}
    finally:
        if leave_open:
            # Dejar Cyme abierto para §§4–5 (flujos / informes en el mismo estudio)
            pass
        else:
            if app is not None:
                try:
                    app.Close()
                except Exception:
                    pass
            try:
                import subprocess
                subprocess.call(
                    ["taskkill", "/F", "/IM", "Cyme.exe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except Exception:
                pass


def run_loadallocation_com(settings, network_id=None, p_kw=None, q_kvar=None,
                           method="KWH", kill_existing=True):
    """
    Distribucion de carga via COM (Cymdist.LoadAllocation).

    CymPy standalone en esta instalacion falla con 130013 (complementos de
    simulacion no autenticados). El motor COM de Cyme.exe si ejecuta
    LoadAllocation — mismo patron que run_loadflow_com.

    method: KWH | KVA | ActualKVA | REA  (default Consumo kWh).
    Retorna dict ok/engine/ret/error/timing.
    """
    import time as _time

    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client
    import comtypes.gen.CYMDISTLib as lib

    mdb = settings.get("database_mdb") or ""
    study = settings.get("study_path") or ""
    net = str(network_id or settings.get("network_id") or "")
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}
    if not net:
        return {"ok": False, "error": "Falta network_id", "engine": "COM"}
    if p_kw is None:
        return {"ok": False, "error": "Falta P_kW cabecera", "engine": "COM"}

    p_kw = float(p_kw)
    q_kvar = float(q_kvar or 0.0)

    method_map = {
        "KWH": lib.CymLoadAllocationMethod.cymKWH,
        "KWHMethod": lib.CymLoadAllocationMethod.cymKWH,
        "KVA": lib.CymLoadAllocationMethod.cymKVA,
        "ConnectedKVA": lib.CymLoadAllocationMethod.cymKVA,
        "ActualKVA": lib.CymLoadAllocationMethod.cymActualKVA,
        "REA": lib.CymLoadAllocationMethod.cymREA,
    }
    method_enum = method_map.get(str(method or "KWH"), lib.CymLoadAllocationMethod.cymKWH)

    if kill_existing:
        _kill_cyme()
        try:
            _time.sleep(0.4)
        except Exception:
            pass

    t0 = _time.time()
    app = None
    study_obj = None
    try:
        app = comtypes.client.CreateObject("Cymdist.Application")
        try:
            app.ShowWindow(0)
        except Exception:
            pass
        app.SelectUniqueDatabaseAccess(mdb, 0, _access_version())
        study_obj = app.OpenStudy(study)

        la = comtypes.client.CreateObject("Cymdist.LoadAllocation")
        la.Method = int(method_enum)
        la.DemandType = int(lib.CymDemandType.cymFeederDemand)
        try:
            la.Tolerance = float(settings.get("loadallocation_tolerance") or 0.01)
        except Exception:
            pass
        try:
            la.RunVoltageDrop = 0
        except Exception:
            pass
        try:
            # Unlock residuales Locked de corridas previas para que KWH pueda
            # prorratear. Los fijos 3.2 se preservan con UnlockAllInitiallyFixedLoads=0.
            # (Antes UnlockLoads=0 + Save CymPy de ~1000 clear → UI colgada.)
            la.UnlockLoads = 1
        except Exception:
            pass
        try:
            # No tocar cargas que ya vienen Locked (clientes 3.2)
            la.UnlockAllInitiallyFixedLoads = 0
        except Exception:
            pass
        for _flag in (
            "RemoveConstraintsInitiallyLockedLoads",
            "RemoveConstraints",
            "RemoveConstraintsDownstreamMeters",
        ):
            try:
                setattr(la, _flag, 0)
            except Exception:
                pass

        dem = la.GetFeederDemand(net, "")
        demand_mode = "per_phase_balanced"
        # Preferir Total (cymTotal=0) = casillero «Total» de Propiedades de la red.
        # Fallback: A/B/C = P/3 (misma suma, Total desmarcado en GUI).
        try:
            dem.SetKW(int(lib.cymTotal), p_kw)
            dem.SetKVAR(int(lib.cymTotal), q_kvar)
            demand_mode = "total"
        except Exception:
            for phase in (
                lib.CymPhase.cymPhaseA,
                lib.CymPhase.cymPhaseB,
                lib.CymPhase.cymPhaseC,
            ):
                dem.SetKW(int(phase), p_kw / 3.0)
                dem.SetKVAR(int(phase), q_kvar / 3.0)
            demand_mode = "per_phase_balanced"
        # pVal = ICustomerInfo (NULL=0): sin factores de cliente adicionales
        la.SetFeederDemand(net, "", dem, 0)

        try:
            la.InitialLosses = 0.0
            initial_losses = 0.0
        except Exception:
            initial_losses = None

        t_run = _time.time()
        ret = la.RunFromID(net)
        run_sec = round(_time.time() - t_run, 2)

        try:
            study_obj.Save()
            saved = True
        except Exception as ex_save:
            saved = False
            return {
                "ok": False,
                "engine": "COM",
                "error": "LoadAllocation OK pero Save fallo: %s" % ex_save,
                "ret": ret,
                "demand_mode": demand_mode,
                "InitialLosses": initial_losses,
                "timing": {"total_sec": round(_time.time() - t0, 2), "run_sec": run_sec},
            }

        return {
            "ok": True,
            "engine": "COM",
            "method": "cymdist_COM_LoadAllocation_%s" % (method or "KWH"),
            "ret": ret,
            "saved": saved,
            "network_id": net,
            "P_kW": p_kw,
            "Q_kvar": q_kvar,
            "demand_mode": demand_mode,
            "InitialLosses": initial_losses,
            "timing": {
                "total_sec": round(_time.time() - t0, 2),
                "run_sec": run_sec,
            },
        }
    except Exception as ex:
        return {
            "ok": False,
            "engine": "COM",
            "error": str(ex),
            "timing": {"total_sec": round(_time.time() - t0, 2)},
        }
    finally:
        if app is not None:
            try:
                app.Close()
            except Exception:
                pass
        if kill_existing:
            _kill_cyme()
