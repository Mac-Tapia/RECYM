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
        try:
            if study_obj is not None:
                study_obj.Save()
        except Exception:
            try:
                comtypes.client.CreateObject("Cymdist.Study").Save()
            except Exception:
                pass
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
    """Cierra Cyme temporalmente para que CymPy pueda abrir el .zxst en exclusiva."""
    _kill_cyme()
    try:
        import time
        time.sleep(0.6)
    except Exception:
        pass
    return {"ok": True, "paused": True, "keep_open": is_keep_open(settings)}


def resume_cymdist_gui(settings, reason="resume"):
    """Reabre CYMDIST visible tras una operacion CymPy (si keep_open)."""
    if not is_keep_open(settings):
        return {"ok": True, "skipped": True, "cymdist_open": False}
    return open_cymdist_gui(settings, kill_existing=True, reason=reason)


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
