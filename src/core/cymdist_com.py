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


def _resolve_com_paths(settings):
    """Rutas BD + estudio motor COM (§1).

    UI puede elegir .xst/.zsxst; el motor COM (GetFeederDemand/SetKW) requiere
    .zxst de la familia o falla con NoneType.SetKW.
    """
    mdb = (settings.get("database_mdb") or "").strip()
    ui = (settings.get("ui_study_path") or settings.get("study_path") or "").strip()
    study_hint = ui or (settings.get("study_path") or "").strip()
    study = study_hint
    try:
        from core.feeder_context import resolve_com_engine_study_path
        engine = resolve_com_engine_study_path(study_hint, settings)
        if engine and os.path.isfile(engine):
            study = engine
    except Exception as ex:
        print("AVISO resolve_com_engine_study_path:", ex)
    return mdb, study


def acquire_cymdist_app(settings, show_window=True, kill_existing=False):
    """
    Obtiene Cymdist.Application ligado al Cyme de la GUI.

    En esta instalacion GetActiveObject falla, pero CreateObject reutiliza el
    mismo Cyme.exe ya abierto (mismo PID). Matar Cyme rompe la sesion visible
    del usuario: por defecto NO se mata.
    """
    _ensure_comtypes(settings.get("cyme_root") if settings else None)
    import comtypes.client
    import time

    if kill_existing:
        _kill_cyme()
        time.sleep(0.8)

    app = None
    mode = "create"
    try:
        app = comtypes.client.GetActiveObject("Cymdist.Application")
        mode = "attach_active"
    except Exception:
        app = comtypes.client.CreateObject("Cymdist.Application")
        mode = "create_or_reuse"

    if show_window and app is not None:
        try:
            app.ShowWindow(1)
        except Exception:
            pass
    return app, mode


def _norm_mdb_path(path):
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(str(path).strip()))
    except Exception:
        return str(path).strip()


def ensure_database_in_cymdist(settings):
    """
    Asegura que la .mdb del §1 exista en el catálogo CYMDIST y quede lista.

    - Si ya hay conexión con la misma ruta → no crear; devolver su nombre real
      (p.ej. BASE JUL25 1_1).
    - Si no está → importar/crear conexión (nombre único) y vincular Network/
      Equipment/Project a esa .mdb.

    No abre estudio; eso lo hace sync_cymdist_binding / open_cymdist_gui.
    """
    mdb = (settings.get("database_mdb") or "").strip()
    if not mdb or not os.path.isfile(mdb):
        raise RuntimeError("database_mdb no existe: %s" % mdb)
    path_abs = os.path.abspath(mdb)
    preferred = (
        (settings.get("database_connection_name") or "").strip()
        or os.path.splitext(os.path.basename(path_abs))[0]
        or "RECYM"
    )

    # 1) ¿Ya registrada por ruta exacta?
    try:
        from core.cympy_adapter import (
            find_cymdist_connection_for_mdb,
            unique_connection_name,
        )
    except Exception as ex:
        return {
            "ok": True,
            "existed": None,
            "created": False,
            "activated_via": "com_path_only",
            "database_mdb": path_abs,
            "connection_name": preferred,
            "warning": "Sin catálogo CymPy (%s); se activará por ruta COM" % ex,
        }

    found = find_cymdist_connection_for_mdb(path_abs)
    if found and found.get("name"):
        cname = str(found["name"])
        if settings is not None:
            settings["database_connection_name"] = cname
            settings["database_mdb"] = path_abs
        return {
            "ok": True,
            "existed": True,
            "created": False,
            "database_mdb": path_abs,
            "connection_name": cname,
            "path": found.get("path") or path_abs,
            "action": "use_existing",
            "msg": "BD ya en CYMDIST: %s -> %s" % (cname, path_abs),
        }

    # 2) No está → crear/importar conexión nombrada y vincular a la .mdb
    cname = unique_connection_name(preferred, path_abs)
    try:
        import cympy.db as db

        try:
            if db.IsConnected():
                try:
                    cur = db.GetCurrentConnection()
                    cur_path = ""
                    try:
                        from core.cympy_adapter import _extract_mdb_path
                        cur_path = _extract_mdb_path(getattr(cur, "Network", None))
                    except Exception:
                        cur_path = ""
                    if cur_path and _norm_mdb_path(cur_path) != _norm_mdb_path(path_abs):
                        db.DisconnectDatabase()
                except Exception:
                    try:
                        db.DisconnectDatabase()
                    except Exception:
                        pass
        except Exception:
            pass

        mdb_src = db.MDBDataSource(path_abs)
        ci = db.ConnectionInformation()
        ci.Name = cname
        ci.Network = mdb_src
        ci.Equipment = mdb_src
        ci.Project = mdb_src
        try:
            db.ConnectDatabase(ci)
        except Exception:
            db.Connect(ci)

        if settings is not None:
            settings["database_connection_name"] = cname
            settings["database_mdb"] = path_abs

        # Verificar que quedó en catálogo
        found2 = find_cymdist_connection_for_mdb(path_abs)
        real_name = (found2 or {}).get("name") or cname
        return {
            "ok": True,
            "existed": False,
            "created": True,
            "database_mdb": path_abs,
            "connection_name": real_name,
            "path": path_abs,
            "action": "created_and_linked",
            "msg": "BD creada en CYMDIST: %s -> %s" % (real_name, path_abs),
        }
    except Exception as ex:
        # Fallback: COM puede trabajar por ruta aunque el catálogo no se actualice
        return {
            "ok": True,
            "existed": False,
            "created": False,
            "database_mdb": path_abs,
            "connection_name": preferred,
            "action": "com_path_fallback",
            "warning": "No se pudo registrar BD en catálogo: %s" % ex,
            "msg": "Activación por ruta COM (sin registro nombrado): %s" % path_abs,
        }


def activate_database_com(app, mdb_path, access_version=None):
    """Activa la .mdb en la sesión COM (GUI). Prefiere Unique por ruta."""
    ver = access_version if access_version is not None else _access_version()
    path = os.path.abspath(mdb_path)
    errors = []
    # 1) Unique por ruta (activa o crea acceso único a esa .mdb)
    try:
        ret = app.SelectUniqueDatabaseAccess(path, 0, ver)
        return {"ok": True, "method": "SelectUniqueDatabaseAccess", "ret": ret, "path": path}
    except Exception as ex:
        errors.append("SelectUniqueDatabaseAccess: %s" % ex)
    # 2) Access con Network=Equipment=path
    try:
        ret = app.SelectDatabaseAccess(path, path, ver)
        return {"ok": True, "method": "SelectDatabaseAccess", "ret": ret, "path": path}
    except Exception as ex:
        errors.append("SelectDatabaseAccess: %s" % ex)
    raise RuntimeError("No se pudo activar BD en CYMDIST: " + " | ".join(errors))


def _save_current_study_com(app=None):
    """Guarda el estudio activo en Cyme para evitar diálogos al cambiar BD/estudio."""
    import comtypes.client
    try:
        st = comtypes.client.CreateObject("Cymdist.Study")
        st.Save()
        return True
    except Exception as ex:
        print("AVISO Save estudio activo antes de sync:", ex)
        return False


def sync_cymdist_binding(app, settings, save_before=True, register_db=True):
    """
    Fuerza en Cyme la misma BD + estudio del numeral 1.

    Flujo:
      0) Guardar estudio activo (evita modal * sin guardar al cambiar).
         Omitir si Cyme acaba de arrancar (Save sin estudio → AV 0xc0000005).
      1) Si la BD no está en el catálogo CYMDIST → crearla/vincularla
         (omitible: register_db=False evita CymPy+COM a la vez).
      2) Activar BD por ruta COM.
      3) Abrir el estudio motor (.zxst de la familia).
    """
    mdb, study = _resolve_com_paths(settings or {})
    if not mdb or not os.path.isfile(mdb):
        raise RuntimeError("database_mdb no existe: %s" % mdb)
    if not study or not os.path.isfile(study):
        raise RuntimeError("study_path no existe: %s" % study)

    saved_before = False
    if save_before:
        # Solo si ya hay Cyme con estudio; Save en Cyme recien creado provoca AV
        saved_before = _save_current_study_com(app)

    db_info = {"connection_name": (settings or {}).get("database_connection_name"),
               "database_mdb": mdb, "existed": True, "created": False,
               "action": "skipped_register", "msg": "BD por ruta COM"}
    if register_db:
        try:
            db_info = ensure_database_in_cymdist(settings or {})
        except Exception as ex_reg:
            print("AVISO ensure_database (sigo por ruta COM):", ex_reg)
            db_info["warning"] = str(ex_reg)

    conn_name = db_info.get("connection_name") or (settings or {}).get("database_connection_name")
    if settings is not None and conn_name:
        settings["database_connection_name"] = conn_name
        settings["database_mdb"] = db_info.get("database_mdb") or mdb

    act = activate_database_com(app, db_info.get("database_mdb") or mdb)
    study_obj = app.OpenStudy(study)

    if db_info.get("created"):
        db_action = "created_and_linked"
    elif db_info.get("existed"):
        db_action = "activated_existing"
    else:
        db_action = db_info.get("action") or "activated_by_path"

    return {
        "database_mdb": db_info.get("database_mdb") or mdb,
        "study_path": study,
        "study_obj": study_obj,
        "database_connection_name": conn_name,
        "network_id": (settings or {}).get("network_id"),
        "db_existed": db_info.get("existed"),
        "db_created": bool(db_info.get("created")),
        "db_action": db_action,
        "db_activate_method": act.get("method"),
        "db_msg": db_info.get("msg"),
        "db_warning": db_info.get("warning"),
        "saved_before_switch": saved_before,
    }


def set_feeder_demand_phases(la, network_id, p_kw, q_kvar, lib=None, app=None):
    """
    Escribe demanda de red = Propiedades > Demanda (casilleros P/Q).

    En Cyme 9.2 la GUI muestra la suma de fases A/B/C. SetKW(Total) «acepta»
    pero NO actualiza esos casilleros; hay que setear fases (y Total).

    Si GetFeederDemand es None (tipico en .xst/.zsxst), intenta LoadFeeder y
    falla con mensaje accionable — nunca SetKW sobre None.
    """
    if lib is None:
        import comtypes.gen.CYMDISTLib as lib

    net = str(network_id or "").strip()
    if not net:
        raise RuntimeError("Falta network_id para SetFeederDemand")
    p_kw = float(p_kw)
    q_kvar = float(q_kvar or 0.0)

    dem = None
    get_err = None
    try:
        dem = la.GetFeederDemand(net, "")
    except Exception as ex:
        get_err = ex
        dem = None

    if dem is None:
        # Asegurar red cargada en el estudio activo
        try:
            import comtypes.client
            st = comtypes.client.CreateObject("Cymdist.Study")
            try:
                st.LoadFeederFromID(net)
            except Exception:
                try:
                    st.LoadNetworkFromID(net, 0)
                except Exception:
                    pass
            dem = la.GetFeederDemand(net, "")
        except Exception as ex2:
            get_err = get_err or ex2

    if dem is None:
        raise RuntimeError(
            "GetFeederDemand=None para red %s (estudio sin demanda COM). "
            "Use el .zxst de la familia del alimentador (no .xst/.zsxst). "
            "Detalle: %s" % (net, get_err or "sin objeto ILoadValue")
        )

    pa = p_kw / 3.0
    qa = q_kvar / 3.0
    for phase in (
        lib.CymPhase.cymPhaseA,
        lib.CymPhase.cymPhaseB,
        lib.CymPhase.cymPhaseC,
    ):
        dem.SetKW(int(phase), pa)
        dem.SetKVAR(int(phase), qa)
    try:
        dem.SetKW(int(lib.cymTotal), p_kw)
        dem.SetKVAR(int(lib.cymTotal), q_kvar)
    except Exception:
        pass
    la.SetFeederDemand(net, "", dem, 0)
    # Verificar lectura inmediata
    dem2 = la.GetFeederDemand(net, "")
    phases = []
    for phase in (
        lib.CymPhase.cymPhaseA,
        lib.CymPhase.cymPhaseB,
        lib.CymPhase.cymPhaseC,
    ):
        try:
            phases.append(float(dem2.GetKW(int(phase))) if dem2 is not None else None)
        except Exception:
            phases.append(None)
    return {
        "P_kW": p_kw,
        "Q_kvar": q_kvar,
        "P_phase_kW": phases,
        "P_sum_kW": sum(x for x in phases if isinstance(x, float)),
        "mode": "per_phase_balanced",
    }


def set_network_demand_com(settings, p_kw, q_kvar, leave_open=True, kill_existing=False):
    """
    SetDemand en la sesion Cyme viva (misma GUI): sync §1 + fases + Save.
    """
    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client

    net = str(settings.get("network_id") or "").strip()
    if not net:
        return {"ok": False, "error": "Falta network_id", "engine": "COM"}

    app = None
    try:
        app, mode = acquire_cymdist_app(
            settings, show_window=True, kill_existing=bool(kill_existing)
        )
        binding = sync_cymdist_binding(app, settings)
        la = comtypes.client.CreateObject("Cymdist.LoadAllocation")
        demand = set_feeder_demand_phases(la, net, p_kw, q_kvar)
        saved = False
        study_obj = binding.get("study_obj")
        try:
            if study_obj is not None:
                study_obj.Save()
                saved = True
            else:
                st = comtypes.client.CreateObject("Cymdist.Study")
                st.Save()
                saved = True
        except Exception as ex_save:
            return {
                "ok": False,
                "engine": "COM",
                "error": "SetDemand OK pero Save fallo: %s" % ex_save,
                "attach_mode": mode,
                "demand": demand,
                "study_path": binding.get("study_path"),
                "database_mdb": binding.get("database_mdb"),
            }
        if leave_open:
            set_keep_open(settings, True, reason="set_demand_com")
        return {
            "ok": True,
            "engine": "COM",
            "api": "LoadAllocation.SetFeederDemand(phases)+Save",
            "attach_mode": mode,
            "saved": saved,
            "cymdist_open": bool(leave_open),
            "network_id": net,
            "study_path": binding.get("study_path"),
            "database_mdb": binding.get("database_mdb"),
            "database_connection_name": binding.get("database_connection_name"),
            "P_kW": demand["P_kW"],
            "Q_kvar": demand["Q_kvar"],
            "P_sum_kW": demand.get("P_sum_kW"),
            "msg": (
                "Demanda en Cyme vivo · %s · P=%.2f (fases) · BD %s"
                % (
                    os.path.basename(binding.get("study_path") or ""),
                    float(demand["P_kW"]),
                    os.path.basename(binding.get("database_mdb") or ""),
                )
            ),
        }
    except Exception as ex:
        return {"ok": False, "engine": "COM", "error": str(ex)}
    finally:
        # Nunca cerrar/matar: la GUI debe seguir mostrando el estudio §1
        pass


def open_cymdist_gui(settings, kill_existing=False, reason="session", fresh=False):
    """
    Abre o reutiliza CYMDIST visible con la BD + estudio del numeral 1.

    fresh=True: mata Cyme, espera, arranca limpio (post CymPy / anti AV 0xc0000005).
      No Save previo ni registro CymPy concurrente.
    """
    import time

    mdb, study = _resolve_com_paths(settings or {})
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}

    do_kill = bool(kill_existing or fresh)
    if do_kill:
        _kill_cyme()
        time.sleep(1.5)
        for _ in range(12):
            if not cyme_is_running():
                break
            time.sleep(0.25)

    try:
        app, mode = acquire_cymdist_app(
            settings, show_window=True, kill_existing=False
        )
        # Tras kill/fresh: no Save (no hay estudio) ni CymPy register (evita AV)
        binding = sync_cymdist_binding(
            app,
            settings,
            save_before=not do_kill,
            register_db=not do_kill,
        )
        set_keep_open(settings, True, reason=reason)

        # Persistir nombre real de conexión si se creó/resolvió
        try:
            from core.common import load_json, save_json
            if binding.get("database_connection_name"):
                gs = load_json("config/settings.json")
                gs["database_connection_name"] = binding["database_connection_name"]
                gs["database_mdb"] = binding.get("database_mdb") or mdb
                save_json("config/settings.json", gs)
        except Exception as ex_p:
            print("AVISO persist connection_name:", ex_p)

        db_action = binding.get("db_action") or "activated"
        if db_action == "created_and_linked":
            db_txt = "BD creada y vinculada"
        elif db_action == "activated_existing":
            db_txt = "BD existente activada"
        else:
            db_txt = "BD activada"

        ui_study = (settings or {}).get("ui_study_path") or ""
        engine_study = binding.get("study_path") or study
        study_note = os.path.basename(engine_study)
        if ui_study and os.path.normcase(os.path.abspath(ui_study)) != os.path.normcase(
            os.path.abspath(engine_study)
        ):
            study_note = "%s (motor; UI %s)" % (
                os.path.basename(engine_study),
                os.path.basename(ui_study),
            )

        return {
            "ok": True,
            "engine": "COM",
            "cymdist_open": True,
            "attach_mode": mode,
            "fresh": bool(fresh or do_kill),
            "study_path": engine_study,
            "ui_study_path": ui_study or engine_study,
            "database_mdb": binding.get("database_mdb") or mdb,
            "database_connection_name": binding.get("database_connection_name"),
            "db_action": db_action,
            "db_created": bool(binding.get("db_created")),
            "db_existed": binding.get("db_existed"),
            "db_msg": binding.get("db_msg"),
            "reason": reason,
            "msg": (
                "CYMDIST sync §1 · %s «%s» · estudio %s · modo %s"
                % (
                    db_txt,
                    binding.get("database_connection_name")
                    or os.path.basename(mdb),
                    study_note,
                    mode,
                )
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


def _find_spotload_com(app, load_id):
    """Localiza SpotLoad por DeviceNumber/ID (FindDevice* o seccion.objSpotLoad)."""
    lid = str(load_id or "").strip()
    if not lid or app is None:
        return None
    for getter in ("FindDeviceFromID", "FindDevice", "GetDevice"):
        fn = getattr(app, getter, None)
        if not callable(fn):
            continue
        try:
            spot = fn(lid)
        except TypeError:
            try:
                spot = fn(lid, 0)
            except Exception:
                spot = None
        except Exception:
            spot = None
        if spot is not None:
            return spot
    try:
        sec = app.FindSectionFromID(lid)
        if sec is not None:
            return getattr(sec, "objSpotLoad", None)
    except Exception:
        pass
    return None


def _set_spotload_connection_com(spot, connected):
    """ConnectionStatus Connected/Disconnected en SpotLoad COM."""
    if spot is None:
        return False
    primary = "Connected" if connected else "Disconnected"
    for attr, val in (
        ("ConnectionStatus", primary),
        ("ConnectionStatus", 1 if connected else 0),
        ("Status", primary),
    ):
        try:
            setattr(spot, attr, val)
            return True
        except Exception:
            try:
                spot.SetValue(val, attr)
                return True
            except Exception:
                pass
    return False


def apply_scenario_spot_loads_com(app, settings, scenario, spot_loads=None):
    """
    Conmuta SpotLoad §4 via COM (sin CymPy) para escenarios §5.

    situacional → Disconnected; proyectado/general → Connected.
    Devuelve (touched, notes).
    """
    scen = (scenario or "").strip().lower() or None
    if spot_loads is None:
        try:
            from pipeline.add_spot_load import list_connected_spot_loads
            spot_loads = list_connected_spot_loads(settings or {})
        except Exception:
            spot_loads = []
    loads = list(spot_loads or [])
    touched = [
        {"LoadID": r.get("LoadID"), "P_kW": r.get("P_kW"), "Q_kvar": r.get("Q_kvar")}
        for r in loads
    ]
    notes = []
    if not loads:
        return touched, notes
    want_connected = scen != "situacional"
    for r in loads:
        lid = str(r.get("LoadID") or "").strip()
        if not lid:
            continue
        row = {
            "LoadID": lid,
            "P_kW": r.get("P_kW"),
            "Q_kvar": r.get("Q_kvar"),
            "role": scen or "proyectado",
            "Fuente": r.get("Fuente"),
            "connected": want_connected,
        }
        try:
            spot = _find_spotload_com(app, lid)
            if spot is None and r.get("SectionID"):
                try:
                    sec = app.FindSectionFromID(str(r.get("SectionID")))
                    if sec is not None:
                        spot = getattr(sec, "objSpotLoad", None)
                except Exception:
                    pass
            if spot is None:
                row["error"] = "SIN_DEVICE"
                notes.append(row)
                print("[COM-LF] AVISO no hallo SpotLoad", lid)
                continue
            ok_set = _set_spotload_connection_com(spot, want_connected)
            row["ConnectionStatus"] = "Connected" if want_connected else "Disconnected"
            if not ok_set:
                row["error"] = "NO_STATUS_FIELD"
            notes.append(row)
            print(
                "[COM-LF]",
                lid,
                "->",
                row["ConnectionStatus"],
                ("OK" if ok_set else "FAIL"),
            )
        except Exception as ex:
            row["error"] = str(ex)
            notes.append(row)
            print("[COM-LF] ERROR", lid, ex)
    return touched, notes


def run_loadflow_com(settings, network_id=None, leave_open=None, kill_existing=None,
                     scenario=None, spot_loads=None):
    """
    Ejecuta LoadFlow por COM (mismo patron anti-AV que §3.3 LoadAllocation).

    leave_open: si True (o sesion cymdist_keep_open), no cierra Cyme al terminar.
    kill_existing: False por defecto (reutiliza sesion GUI §1).
    scenario: None | situacional | proyectado — conmuta SpotLoad §4 via COM.
    """
    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client
    import time as _time

    if leave_open is None:
        try:
            from pipeline.run_demand_allocation import load_session
            leave_open = bool(load_session(settings).get("cymdist_keep_open"))
        except Exception:
            leave_open = True
    if kill_existing is None:
        kill_existing = False

    mdb, study = _resolve_com_paths(settings or {})
    net = str(network_id or settings.get("network_id") or "")
    if not mdb or not os.path.isfile(mdb):
        return {"ok": False, "error": "database_mdb no existe: %s" % mdb, "engine": "COM"}
    if not study or not os.path.isfile(study):
        return {"ok": False, "error": "study_path no existe: %s" % study, "engine": "COM"}
    if not net:
        return {"ok": False, "error": "Falta network_id", "engine": "COM"}

    if kill_existing:
        _kill_cyme()
        try:
            _time.sleep(0.4)
        except Exception:
            pass

    app = None
    attach_mode = None
    scen = (scenario or "").strip().lower() or None
    if scen and scen not in ("situacional", "proyectado"):
        scen = None
    scen_notes = []
    touched = []
    t0 = _time.time()
    try:
        app, attach_mode = acquire_cymdist_app(
            settings, show_window=bool(leave_open), kill_existing=False
        )
        # LoadFlow: no Save previo ni registro CymPy (AV 0xC0000005 en .sxst/
        # sesion GUI ya abierta tras §1–§3). Solo activar BD+estudio.
        binding = sync_cymdist_binding(
            app, settings, save_before=False, register_db=False
        )
        mdb = binding.get("database_mdb") or mdb
        study = binding.get("study_path") or study
        study_obj = binding.get("study_obj")

        # Escenario §5: conmutar SpotLoad nuevas sin CymPy (anti AV 0xC0000005).
        # §4 es opcional: sin cargas nuevas → escenario vacio, solo corre LF.
        if scen in ("situacional", "proyectado") or spot_loads:
            target = scen or "proyectado"
            touched, scen_notes = apply_scenario_spot_loads_com(
                app, settings, target, spot_loads=spot_loads
            )
            if touched:
                print(
                    "[COM-LF] Cargas §4 escenario %s: %d (%s)"
                    % (
                        target,
                        len(touched),
                        "DESCONECTADAS" if target == "situacional" else "CONECTADAS",
                    )
                )
            else:
                print(
                    "[COM-LF] Sin SpotLoad §4 — escenario %s solo LoadFlow (OK)"
                    % (target,)
                )

        warn_path = None
        log_path = None
        try:
            out_dir = settings.get("output_dir") or os.path.dirname(study)
            feeder = settings.get("feeder_id") or "feeder"
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
                # KWLOSS/KVARLOSS a menudo no existen en nodo fuente → red / keywords alt.
                for loss_kw, alts in (
                    ("KWLOSS", ("KWLOSS", "TotalKWLoss", "KWLosses", "PLOSS")),
                    ("KVARLOSS", ("KVARLOSS", "TotalKVARLoss", "KVARLosses", "QLOSS")),
                ):
                    cur = topo.get(loss_kw)
                    cur_s = str(cur or "").strip()
                    if cur is not None and not cur_s.startswith(("$", "ERR:")):
                        continue
                    for alt in alts:
                        for getter_name in ("QueryResultNetwork", "QueryResult"):
                            getter = getattr(lf, getter_name, None)
                            if getter is None:
                                continue
                            try:
                                if getter_name == "QueryResultNetwork":
                                    val = getter(alt, net)
                                else:
                                    val = getter(alt)
                            except Exception:
                                continue
                            vs = str(val or "").strip()
                            if vs and not vs.startswith(("$", "ERR:")):
                                topo[loss_kw] = val
                                topo["%s_source" % loss_kw] = "%s:%s" % (getter_name, alt)
                                break
                        if topo.get(loss_kw) not in (None, cur) and not str(
                            topo.get(loss_kw) or ""
                        ).startswith(("$", "ERR:")):
                            break
                if _topo_ok(topo):
                    method_used = method
                    break
            if method_used is not None:
                break

        # Corregir KWTOT/KVARTOT ~3× vs cabecera §1 (informe / convergencia)
        if method_used is not None and topo:
            topo = normalize_lf_topo_powers(topo, settings, scenario=scen)

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
        # Solo persistir si se conmuto SpotLoad §4. Study.Save sobre .sxst con
        # GUI abierta provoca AV 0xC0000005 (Cyme.exe crash dump) tras LF OK.
        need_save = bool(touched) and bool(settings.get("save_after_write", True))
        if need_save:
            try:
                if study_obj is not None:
                    study_obj.Save()
                    saved = True
                else:
                    st = comtypes.client.CreateObject("Cymdist.Study")
                    st.Save()
                    saved = True
            except Exception as ex_sv:
                print("[COM-LF] AVISO Save tras escenario:", ex_sv)
                saved = False
        elif not touched and scen:
            print("[COM-LF] Save omitido (sin SpotLoad §4 que persistir)")

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
            "attach_mode": attach_mode,
            "elapsed_sec": round(_time.time() - t0, 2),
            "scenario": scen or "general",
            "new_loads_scenario": scen_notes,
            "n_new_loads": len(touched),
            "new_loads_connected": (
                None if not scen else (scen != "situacional")
            ),
            "study_path": study,
            "database_mdb": mdb,
        }
        if not ok:
            result["error"] = (
                "LoadFlow COM sin solucion valida (KWTOT invalido). "
                "method=%s ret=%s. %s"
                % (method_used, run_ret, (log_errors[:1] or warnings[:1] or [""])[0])
            )
        # Dejar GUI visible/estable tras LF (el worker aislado puede soltar Cyme)
        if leave_open and ok:
            try:
                app.ShowWindow(1)
            except Exception:
                pass
            try:
                from pipeline.run_demand_allocation import load_session, save_session
                sess = load_session(settings) or {}
                sess["cymdist_keep_open"] = True
                sess["cymdist_keep_open_reason"] = "post_loadflow_%s" % (scen or "general")
                save_session(settings, sess)
            except Exception:
                pass
        return result
    except Exception as ex:
        return {"ok": False, "error": str(ex), "engine": "COM"}
    finally:
        if leave_open:
            # Dejar Cyme abierto (misma sesion GUI §1 / post-3.3)
            pass
        else:
            if app is not None:
                try:
                    app.Close()
                except Exception:
                    pass
            _kill_cyme()


def run_loadallocation_com(settings, network_id=None, p_kw=None, q_kvar=None,
                           method="KWH", kill_existing=False,
                           disconnect_load_ids=None, leave_open=True):
    """
    Distribucion de carga via COM (Cymdist.LoadAllocation).

    CymPy standalone en esta instalacion falla con 130013 (complementos de
    simulacion no autenticados). El motor COM de Cyme.exe si ejecuta
    LoadAllocation — mismo patron que run_loadflow_com.

    sync §1: SelectUniqueDatabaseAccess + OpenStudy del contexto UI.
    Demanda: siempre por fases (la GUI Propiedades>Demanda no refleja Total).
    leave_open=True (default): no cierra ni mata Cyme — la GUI queda con el resultado.

    disconnect_load_ids: SpotLoad a poner ConnectionStatus=Disconnected antes
    del Run (cargas Incluir=off) para que no reciban demanda al repartir.

    method: KWH | KVA | ActualKVA | REA  (default Consumo kWh).
    Retorna dict ok/engine/ret/error/timing.
    """
    import time as _time

    _ensure_comtypes(settings.get("cyme_root"))
    import comtypes.client
    import comtypes.gen.CYMDISTLib as lib

    mdb, study = _resolve_com_paths(settings or {})
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
    disc_ids = [str(x).strip() for x in (disconnect_load_ids or []) if str(x).strip()]

    method_map = {
        "KWH": lib.CymLoadAllocationMethod.cymKWH,
        "KWHMethod": lib.CymLoadAllocationMethod.cymKWH,
        "KVA": lib.CymLoadAllocationMethod.cymKVA,
        "ConnectedKVA": lib.CymLoadAllocationMethod.cymKVA,
        "ActualKVA": lib.CymLoadAllocationMethod.cymActualKVA,
        "REA": lib.CymLoadAllocationMethod.cymREA,
    }
    method_enum = method_map.get(str(method or "KWH"), lib.CymLoadAllocationMethod.cymKWH)

    # Solo matar si el caller lo pide explicitamente (rompe sync GUI)
    if kill_existing:
        _kill_cyme()
        try:
            _time.sleep(0.4)
        except Exception:
            pass

    t0 = _time.time()
    app = None
    study_obj = None
    attach_mode = None
    disconnected = {"n_ok": 0, "n_err": 0, "load_ids": [], "report": []}
    try:
        app, attach_mode = acquire_cymdist_app(
            settings, show_window=bool(leave_open), kill_existing=False
        )
        binding = sync_cymdist_binding(app, settings)
        study_obj = binding.get("study_obj")
        mdb = binding.get("database_mdb") or mdb
        study = binding.get("study_path") or study

        # Desconectar no-Incluir antes del modulo (evita que les asignen carga)
        for lid in disc_ids:
            row = {"LoadID": lid, "Estado": "SKIP"}
            try:
                spot = None
                for getter in ("FindDeviceFromID", "FindDevice", "GetDevice"):
                    fn = getattr(app, getter, None)
                    if not callable(fn):
                        continue
                    try:
                        spot = fn(lid)
                    except TypeError:
                        try:
                            spot = fn(lid, 0)
                        except Exception:
                            spot = None
                    except Exception:
                        spot = None
                    if spot is not None:
                        break
                if spot is None:
                    # Intento via seccion SpotLoad en red
                    try:
                        for sec_id in (lid,):
                            sec = app.FindSectionFromID(sec_id)
                            if sec is not None:
                                spot = getattr(sec, "objSpotLoad", None)
                                break
                    except Exception:
                        pass
                if spot is None:
                    row["Estado"] = "SIN_DEVICE"
                    disconnected["n_err"] += 1
                    disconnected["report"].append(row)
                    print("[COM] AVISO no hallo SpotLoad", lid)
                    continue
                # ConnectionStatus / Status
                ok_set = False
                for attr, val in (
                    ("ConnectionStatus", "Disconnected"),
                    ("ConnectionStatus", 0),
                    ("Status", "Disconnected"),
                ):
                    try:
                        setattr(spot, attr, val)
                        ok_set = True
                        break
                    except Exception:
                        try:
                            # algunos wrappers usan SetValue
                            spot.SetValue(val, attr)
                            ok_set = True
                            break
                        except Exception:
                            pass
                if ok_set:
                    row["Estado"] = "DISCONNECTED"
                    disconnected["n_ok"] += 1
                    disconnected["load_ids"].append(lid)
                    print("[COM] EXCLUIDO", lid, "-> Disconnected")
                else:
                    row["Estado"] = "NO_STATUS_FIELD"
                    disconnected["n_err"] += 1
                    print("[COM] AVISO no pudo set ConnectionStatus", lid)
            except Exception as ex_d:
                row["Estado"] = "ERROR"
                row["Detalle"] = str(ex_d)
                disconnected["n_err"] += 1
                print("[COM] ERROR desconectar", lid, ex_d)
            disconnected["report"].append(row)
        disconnected["msg"] = (
            "COM desconecto %d/%d excluidas" % (disconnected["n_ok"], len(disc_ids))
            if disc_ids else "Sin excluidas a desconectar"
        )

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
            la.UnlockLoads = 1
        except Exception:
            pass
        try:
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

        # Siempre fases: SetKW(Total) no actualiza Propiedades>Demanda en Cyme 9.2
        demand_info = set_feeder_demand_phases(la, net, p_kw, q_kvar, lib=lib)
        demand_mode = demand_info.get("mode") or "per_phase_balanced"

        try:
            la.InitialLosses = 0.0
            initial_losses = 0.0
        except Exception:
            initial_losses = None

        t_run = _time.time()
        ret = la.RunFromID(net)
        run_sec = round(_time.time() - t_run, 2)

        try:
            if study_obj is not None:
                study_obj.Save()
            else:
                comtypes.client.CreateObject("Cymdist.Study").Save()
            saved = True
        except Exception as ex_save:
            saved = False
            return {
                "ok": False,
                "engine": "COM",
                "error": "LoadAllocation OK pero Save fallo: %s" % ex_save,
                "ret": ret,
                "demand_mode": demand_mode,
                "P_sum_kW": demand_info.get("P_sum_kW"),
                "InitialLosses": initial_losses,
                "disconnected": disconnected,
                "attach_mode": attach_mode,
                "study_path": study,
                "database_mdb": mdb,
                "timing": {"total_sec": round(_time.time() - t0, 2), "run_sec": run_sec},
            }

        if leave_open:
            set_keep_open(settings, True, reason="loadallocation_com")

        return {
            "ok": True,
            "engine": "COM",
            "method": "cymdist_COM_LoadAllocation_%s" % (method or "KWH"),
            "ret": ret,
            "saved": saved,
            "network_id": net,
            "P_kW": p_kw,
            "Q_kvar": q_kvar,
            "P_sum_kW": demand_info.get("P_sum_kW"),
            "demand_mode": demand_mode,
            "InitialLosses": initial_losses,
            "disconnected": disconnected,
            "attach_mode": attach_mode,
            "study_path": study,
            "database_mdb": mdb,
            "cymdist_open": bool(leave_open),
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
            "disconnected": disconnected,
            "attach_mode": attach_mode,
            "timing": {"total_sec": round(_time.time() - t0, 2)},
        }
    finally:
        # Dejar Cyme abierto = misma sesion GUI con BD/estudio §1
        if not leave_open and app is not None:
            try:
                app.Close()
            except Exception:
                pass
            if kill_existing:
                _kill_cyme()
