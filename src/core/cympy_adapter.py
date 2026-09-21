from __future__ import print_function
import os
from core.common import backup_file

class CymPyAdapter(object):
    def __init__(self, cympy, api_map, settings=None):
        self.cympy = cympy
        self.api = api_map
        self.settings = settings or {}
        self._study_open = False
        self._db_connected = False

    def _resolve_callable(self, dotted):
        obj = self.cympy
        for part in dotted.split("."):
            obj = getattr(obj, part)
        return obj

    def command_cfg(self, name):
        cfg = self.api["commands"].get(name)
        if not cfg:
            raise RuntimeError("Comando CymPy desconocido: " + name)
        if not cfg.get("confirmed") or not cfg.get("callable"):
            note = cfg.get("note") or "complete mapeo en config/cympy_api_map.json"
            raise RuntimeError("Comando CymPy no mapeado/confirmado: %s (%s)" % (name, note))
        return cfg

    def command(self, name, *args, **kwargs):
        cfg = self.command_cfg(name)
        target = self._resolve_callable(cfg["callable"])
        method = cfg.get("method")
        if method:
            inst = target()
            fn = getattr(inst, method)
            return fn(*args, **kwargs)
        return target(*args, **kwargs)

    def obj_cfg(self, name):
        cfg = self.api["objects"][name]
        if not cfg.get("confirmed"):
            raise RuntimeError("Objeto CymPy no mapeado/confirmado: " + name)
        return cfg

    def device_type(self, name):
        cfg = self.obj_cfg(name)
        return getattr(self.cympy.enums.DeviceType, cfg["device_type"])

    def get_device(self, name, obj_id):
        d = self.cympy.study.GetDevice(str(obj_id), self.device_type(name))
        if d is None:
            raise RuntimeError("Dispositivo no encontrado: %s (%s)" % (obj_id, name))
        return d

    def set_equipment(self, name, obj_id, equipment_id):
        cfg = self.obj_cfg(name)
        d = self.get_device(name, obj_id)
        fld = cfg["equipment_field"]
        before = d.GetValue(fld)
        d.SetValue(str(equipment_id), fld)
        return before, d.GetValue(fld)

    def set_load_pq(self, obj_id, kw, kvar, lock=True):
        """
        Fija P/Q de SpotLoad.
        - Si CustomerLoadValues.Count == 1 (SED tipico Phase=ABC): escribe total en [0].
        - Si Count >= 3 (carga concentrada por fase A/B/C): reparte trifasico
          P/3 y Q/3 en cada fase monofasica (casilleros Potencia real / reactiva).
        """
        import math
        cfg = self.obj_cfg("Load")
        d = self.get_device("Load", obj_id)
        values_base = (
            "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues"
        )
        target_type = cfg.get("value_type") or "LoadValueKW_KVAR"
        kw = float(kw)
        kvar = float(kvar)

        n_values = 1
        try:
            n_values = int(float(str(d.GetValue(values_base + ".Count") or "1").replace(",", ".")))
        except Exception:
            n_values = 1
        if n_values < 1:
            n_values = 1

        # Indices a escribir: por-fase A/B/C o un solo Total
        if n_values >= 3:
            indices = list(range(3))
            kw_each = kw / 3.0
            kvar_each = kvar / 3.0
        else:
            indices = [0]
            kw_each = kw
            kvar_each = kvar

        before = (None, None)
        after = (None, None)
        written = []

        for i in indices:
            value_base = "%s[%d].LoadValue" % (values_base, i)

            def _type(vb=value_base):
                try:
                    return str(d.GetValue(vb + ".GetType()") or "")
                except Exception:
                    return ""

            cur = _type()
            if cur != target_type:
                for cmd in (
                    "%s.SetType(%s)" % (value_base, target_type),
                    "%s.Create(%s)" % (value_base, target_type),
                ):
                    try:
                        d.Execute(cmd)
                        if _type() == target_type:
                            break
                    except Exception:
                        continue
                cur = _type()

            if cur == "LoadValueKW_KVAR" or cur == target_type:
                p_field = value_base + ".KW"
                q_field = value_base + ".KVAR"
                try:
                    if i == indices[0]:
                        before = (d.GetValue(p_field), d.GetValue(q_field))
                except Exception:
                    pass
                d.SetValue(kw_each, p_field)
                d.SetValue(kvar_each, q_field)
                try:
                    after = (d.GetValue(p_field), d.GetValue(q_field))
                except Exception:
                    after = (kw_each, kvar_each)
                written.append({
                    "index": i,
                    "KW": kw_each,
                    "KVAR": kvar_each,
                    "after": after,
                })
            elif cur == "LoadValueKW_PF":
                s = math.sqrt(kw_each * kw_each + kvar_each * kvar_each) or 1.0
                pf = max(0.01, min(1.0, abs(kw_each) / s))
                p_field = value_base + ".KW"
                q_field = value_base + ".PF"
                d.SetValue(kw_each, p_field)
                d.SetValue(pf, q_field)
                after = (d.GetValue(p_field), d.GetValue(q_field))
                written.append({"index": i, "KW": kw_each, "PF": pf, "after": after})
            elif cur == "LoadValueKVA_PF":
                kva = math.sqrt(kw_each * kw_each + kvar_each * kvar_each)
                pf = max(0.01, min(1.0, abs(kw_each) / kva)) if kva else 1.0
                p_field = value_base + ".KVA"
                q_field = value_base + ".PF"
                d.SetValue(kva, p_field)
                d.SetValue(pf, q_field)
                after = (d.GetValue(p_field), d.GetValue(q_field))
                written.append({"index": i, "KVA": kva, "PF": pf, "after": after})
            else:
                raise RuntimeError(
                    "LoadValue type no soportado para %s[%d]: %s"
                    % (obj_id, i, cur or "(vacío)")
                )

        if lock and cfg.get("status_field"):
            lock_val = str(cfg.get("lock_value", "Locked"))
            try:
                d.SetValue(lock_val, cfg["status_field"])
            except Exception:
                try:
                    d.SetValue(True, cfg["status_field"])
                except Exception:
                    pass

        # before/after: totales equivalentes para reportes
        if n_values >= 3 and written:
            after = (kw, kvar)
        return before, after

    def set_load_kwh_and_pot(self, obj_id, kwh, pot_kw, fp=0.95, lock=True):
        """
        Carga consumo (kWh) y potencia real (kW) en SpotLoad.
        - KWH → CustomerLoadValues[0].KWH  (= casillero Consumo en CYMDIST)
        - Pot → LoadValue.KW / KVAR
        Verifica relectura de KWH tras escribir (precision).
        """
        import math
        cfg = self.obj_cfg("Load")
        d = self.get_device("Load", obj_id)
        kwh_field = cfg.get("kwh_field") or (
            "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].KWH"
        )
        before_kwh = None
        after_kwh = None
        kwh_ok = None
        if kwh is not None and kwh != "":
            target_kwh = float(kwh)
            try:
                before_kwh = d.GetValue(kwh_field)
            except Exception:
                before_kwh = None
            d.SetValue(target_kwh, kwh_field)
            # Releer y, si CYMDIST redondea/locale, reintentar una vez
            after_kwh = d.GetValue(kwh_field)
            got = self._parse_load_number(after_kwh)
            if got is None or abs(got - target_kwh) > max(0.5, abs(target_kwh) * 1e-6):
                d.SetValue(target_kwh, kwh_field)
                after_kwh = d.GetValue(kwh_field)
                got = self._parse_load_number(after_kwh)
            kwh_ok = got is not None and abs(got - target_kwh) <= max(0.5, abs(target_kwh) * 1e-6)

        pq_before = pq_after = None
        if pot_kw is not None and pot_kw != "":
            kw = float(pot_kw)
            kvar = kw * math.tan(math.acos(max(0.01, min(1.0, float(fp)))))
            pq_before, pq_after = self.set_load_pq(obj_id, kw, kvar, lock=lock)
        elif lock and cfg.get("status_field"):
            try:
                d.SetValue(str(cfg.get("lock_value", "Locked")), cfg["status_field"])
            except Exception:
                pass

        return {
            "kwh_before": before_kwh,
            "kwh_after": after_kwh,
            "kwh_ok": kwh_ok,
            "pq_before": pq_before,
            "pq_after": pq_after,
        }

    @staticmethod
    def _parse_load_number(v):
        """Parse CYMDIST GetValue numerics (locale comma decimals)."""
        if v is None or v == "":
            return None
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        try:
            s = str(v).strip().replace(" ", "").replace("\xa0", "")
            if not s:
                return None
            if "," in s and "." in s:
                if s.rfind(",") > s.rfind("."):
                    s = s.replace(".", "").replace(",", ".")
                else:
                    s = s.replace(",", "")
            elif "," in s:
                s = s.replace(",", ".")
            return float(s)
        except Exception:
            return None

    def set_load_lock(self, obj_id, locked=True):
        """Locked / Unlocked durante LoadAllocation."""
        cfg = self.obj_cfg("Load")
        field = cfg.get("status_field") or (
            "CustomerLoads[0].CustomerLoadModels[0].LockDuringLoadAllocation"
        )
        val = str(cfg.get("lock_value", "Locked") if locked else "Unlocked")
        d = self.get_device("Load", obj_id)
        d.SetValue(val, field)
        try:
            after = d.GetValue(field)
        except Exception:
            after = val
        return {"after": after, "locked": bool(locked)}

    def unlock_loads_except(self, network_id, keep_locked_ids):
        """
        Deja Unlocked todas las SpotLoad excepto keep_locked_ids (fijos / nuevas).
        Asi LoadAllocation (Consumo kWh) puede actualizar kW/kvar del residual.
        """
        keep = set(str(x) for x in (keep_locked_ids or set()))
        c = self.cympy
        unlocked = []
        kept = []
        devices = list(c.study.ListDevices(c.enums.DeviceType.SpotLoad, str(network_id or "")))
        field = (
            self.obj_cfg("Load").get("status_field")
            or "CustomerLoads[0].CustomerLoadModels[0].LockDuringLoadAllocation"
        )
        for d in devices:
            lid = str(getattr(d, "DeviceNumber", "") or "")
            if not lid:
                continue
            if lid in keep:
                try:
                    d.SetValue("Locked", field)
                except Exception:
                    pass
                kept.append(lid)
                continue
            try:
                d.SetValue("Unlocked", field)
                unlocked.append(lid)
            except Exception:
                pass
        return {"unlocked": unlocked, "kept_locked": kept}

    def snapshot_spot_loads_pq_kwh(self, network_id, exclude_ids=None):
        """Lee KWH/KW/KVAR de SpotLoads (para validar post-distribucion)."""
        exclude = set(str(x) for x in (exclude_ids or set()))
        cfg = self.obj_cfg("Load")
        base = (
            "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0]"
        )
        value_base = cfg.get("value_base") or (base + ".LoadValue")
        kwh_field = cfg.get("kwh_field") or (base + ".KWH")
        rows = []
        devices = list(
            self.cympy.study.ListDevices(
                self.cympy.enums.DeviceType.SpotLoad, str(network_id or "")
            )
        )
        for d in devices:
            lid = str(getattr(d, "DeviceNumber", "") or "")
            if not lid or lid in exclude:
                continue
            try:
                kwh = self._parse_load_number(d.GetValue(kwh_field))
            except Exception:
                kwh = None
            kw = kvar = None
            try:
                kw = self._parse_load_number(d.GetValue(value_base + ".KW"))
                kvar = self._parse_load_number(d.GetValue(value_base + ".KVAR"))
            except Exception:
                pass
            rows.append({"LoadID": lid, "KWH": kwh, "kW": kw, "kvar": kvar})
        return rows

    def set_load_connected(self, obj_id, connected=True):
        """
        Conecta o desconecta fisicamente la SpotLoad en el modelo CYMDIST
        (CustomerLoads[0].ConnectionStatus = Connected|Disconnected).
        Desconectada no entra en LoadAllocation ni LoadFlow.
        """
        cfg = self.obj_cfg("Load")
        field = cfg.get("connection_status_field") or "CustomerLoads[0].ConnectionStatus"
        on_val = str(cfg.get("connected_value") or "Connected")
        off_val = str(cfg.get("disconnected_value") or "Disconnected")
        target = on_val if connected else off_val
        d = self.get_device("Load", obj_id)
        before = None
        try:
            before = d.GetValue(field)
        except Exception:
            before = None
        d.SetValue(target, field)
        after = None
        try:
            after = d.GetValue(field)
        except Exception:
            after = target
        return {"before": before, "after": after, "connected": bool(connected)}

    def _device_exists(self, name, obj_id):
        """True solo si GetDevice devuelve un objeto real (CymPy retorna None si no existe)."""
        try:
            d = self.cympy.study.GetDevice(str(obj_id), self.device_type(name))
            return d is not None
        except Exception:
            return False

    def _ensure_customer_load(self, load_id):
        """Asegura CustomerLoad en SpotLoad recien creada (CymPy GetLoad/AddCustomerLoad)."""
        dtype = self.device_type("Load")
        load_obj = None
        for getter in ("GetDevice", "GetLoad"):
            try:
                fn = getattr(self.cympy.study, getter)
                load_obj = fn(str(load_id), dtype)
                if load_obj is not None:
                    break
            except Exception:
                load_obj = None
        if load_obj is None:
            return False
        # Si ya hay CustomerLoads[0] con LoadValue tipado, listo
        try:
            vtype = str(
                load_obj.GetValue(
                    "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue.GetType()"
                )
                or ""
            )
            if vtype:
                return True
        except Exception:
            pass
        for cust in ("1", "DEFAULT", "Spot", str(load_id)):
            try:
                load_obj.AddCustomerLoad(cust)
                break
            except Exception:
                continue
        # Tipar LoadValue si AddCustomerLoad dejo el polimorfico vacio
        value_base = (
            "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue"
        )
        for cmd in (
            value_base + ".SetType(LoadValueKW_KVAR)",
            value_base + ".Create(LoadValueKW_KVAR)",
        ):
            try:
                load_obj.Execute(cmd)
                break
            except Exception:
                continue
        try:
            load_obj.GetValue(value_base + ".KW")
            return True
        except Exception:
            return False

    def add_spot_load(self, load_id, section_id, kw, kvar, lock=True, phases="ABC",
                      location=None, node_id=None, from_node=None, to_node=None,
                      recreate=False, stub=False):
        """
        Crea SpotLoad (carga concentrada) en el esquema CYMDIST.

        Por defecto stub=False: coloca el simbolo SpotLoad en el tramo del nodo
        (From/To), sin lateral tipo SED (no confundir con transformador SED).
        SymbolSize>0 fuerza el dibujo del simbolo de carga concentrada.
        """
        load_id = str(load_id).strip().upper()
        section_id = str(section_id or "").strip()
        attach_node = str(node_id or "").strip()
        loc = self._resolve_spot_location(location, node_id, from_node, to_node)
        if not attach_node:
            attach_node = str(
                (to_node if loc == "To" else from_node) or ""
            ).strip()

        dtype = self.device_type("Load")
        Loc = self.cympy.enums.Location
        created = False
        stub_info = None

        # Limpiar SpotLoad previa y stubs SEC_SPOT_* (evitar confusion con SED)
        if recreate or self._device_exists("Load", load_id) or stub:
            self._cleanup_spot_artifacts(load_id)

        if stub:
            if not attach_node:
                raise RuntimeError("Indique el nodo donde dibujar la carga concentrada.")
            stub_info = self._ensure_spot_stub_section(load_id, attach_node, section_id)
            section_id = stub_info["SectionID"]
            loc = "To"
            loc_enum = Loc.To
            created = self._add_spot_device(load_id, dtype, section_id, loc_enum)
            try:
                self.get_device("Load", load_id).SetValue("To", "Location")
            except Exception:
                pass
        else:
            if not section_id:
                raise RuntimeError("Falta SectionID del tramo para la carga concentrada.")
            loc_enum = {
                "From": Loc.From,
                "To": Loc.To,
                "Middle": Loc.Middle,
            }.get(loc, Loc.From)
            created = self._add_spot_device(load_id, dtype, section_id, loc_enum)
            try:
                self.get_device("Load", load_id).SetValue(str(loc), "Location")
            except Exception:
                pass
            try:
                d = self.get_device("Load", load_id)
                cur = str(d.GetValue("Location") or "")
                if cur.lower() != loc.lower():
                    try:
                        self.cympy.study.MoveDevice(load_id, dtype, section_id, loc_enum, False)
                    except Exception:
                        self.cympy.study.MoveDevice(load_id, dtype, section_id, loc_enum, True)
            except Exception as ex:
                print("AVISO MoveDevice SpotLoad %s: %s" % (load_id, ex))

        self._ensure_customer_load(load_id)
        self._ensure_spot_symbol(load_id)

        try:
            d = self.get_device("Load", load_id)
            for fld, val in (
                ("Phase", str(phases or "ABC")),
                ("ConnectionConfiguration", "Yg"),
                ("ClosedPhase", "ABC"),
            ):
                try:
                    d.SetValue(val, fld)
                except Exception:
                    pass
        except Exception:
            pass

        before, after = self.set_load_pq(load_id, kw, kvar, lock=lock)
        loc_after = None
        try:
            loc_after = str(self.get_device("Load", load_id).GetValue("Location") or "")
        except Exception:
            try:
                loc_after = {0: "From", 1: "Middle", 2: "To"}.get(
                    int(self.get_device("Load", load_id).Location), loc
                )
            except Exception:
                loc_after = loc

        try:
            self.cympy.study.DisplayBestFit()
        except Exception:
            pass

        out = {
            "created": created,
            "LoadID": load_id,
            "SectionID": section_id,
            "Location": loc_after or loc,
            "phases": phases or "ABC",
            "pq_before": before,
            "pq_after": after,
            "kW": float(kw),
            "kvar": float(kvar),
            "recreated": bool(recreate),
            "stub": bool(stub),
            "symbol": "SpotLoad",
            "NodeID": attach_node,
        }
        if stub_info:
            out.update({
                "StubSectionID": stub_info.get("SectionID"),
                "StubNodeID": stub_info.get("ToNodeID"),
                "StubLineID": stub_info.get("LineID"),
                "ParentSectionID": stub_info.get("ParentSectionID"),
            })
        return out

    def _cleanup_spot_artifacts(self, load_id):
        """Borra SpotLoad y tramos stub SEC_SPOT_* (no confundir con SED)."""
        load_id = str(load_id).strip().upper()
        dtype = self.device_type("Load")
        try:
            self.cympy.study.DeleteDevice(load_id, dtype)
        except Exception:
            pass
        try:
            self.cympy.study.DeleteSection(("SEC_SPOT_" + load_id)[:64])
        except Exception:
            pass

    def _ensure_spot_symbol(self, load_id):
        """SymbolSize>0 para dibujar el simbolo de carga concentrada (SpotLoad)."""
        try:
            d = self.get_device("Load", load_id)
        except Exception:
            return False
        try:
            cur = str(d.GetValue("SymbolSize") or "0").replace(",", ".")
            nums = []
            for p in cur.replace(";", ",").split(","):
                p = p.strip()
                if not p:
                    continue
                try:
                    nums.append(float(p))
                except Exception:
                    pass
            if nums and max(abs(x) for x in nums) > 0:
                return True
        except Exception:
            pass
        for val in (1.0, "1", "1.0", "1,0"):
            try:
                d.SetValue(val, "SymbolSize")
                return True
            except Exception:
                continue
        return False

    def _pick_stub_line_equipment(self, parent_section_id):
        """Elige conductor del stub: prioriza XLPE (como SED) o el del tramo padre."""
        preferred = ("XLPE120", "XLPE70", "XLPE95", "XLPE185", "DEFAULT")
        # 1) Inventario SED tipico
        for eq in preferred:
            if eq == "DEFAULT":
                continue
            # no hay API barata de existencia; probar al AddSection y caer
            pass
        parent_eq = ""
        parent_dtype = None
        if parent_section_id:
            try:
                sec = self.cympy.study.GetSection(str(parent_section_id))
                for d in sec.ListDevices():
                    try:
                        dt = int(d.DeviceType)
                    except Exception:
                        continue
                    # 10=Underground, 11=OverheadLine
                    if dt in (10, 11):
                        parent_eq = str(d.EquipmentID or "").strip()
                        parent_dtype = dt
                        if parent_eq:
                            break
            except Exception:
                pass
        if parent_dtype == 10 and parent_eq:
            return "Underground", parent_eq
        if parent_eq:
            return "OverheadLine", parent_eq
        return "Underground", "XLPE120"

    def _ensure_spot_stub_section(self, load_id, attach_node, parent_section_id=None):
        """
        Crea (o reutiliza) un tramo corto desde el nodo de conexion hasta un nodo VIRTUAL,
        igual que las SED del modelo (SpotLoad en Location.To).
        """
        load_id = str(load_id).strip().upper()
        attach_node = str(attach_node).strip()
        net = str(self.settings.get("network_id") or "")
        stub_sec = ("SEC_SPOT_" + load_id)[:64]
        stub_line = ("LINE_SPOT_" + load_id)[:64]
        stub_node = ("NODE_" + load_id + "_VIRTUAL")[:64]

        # Si ya existe el stub, reutilizarlo
        try:
            sec = self.cympy.study.GetSection(stub_sec)
            if sec is not None:
                try:
                    sec.Length = 0.3
                except Exception:
                    pass
                self._offset_stub_node(attach_node, stub_node)
                to_id = str(getattr(sec, "ToNode", None) or stub_node).strip().strip("'\"")
                return {
                    "SectionID": stub_sec,
                    "ToNodeID": to_id or stub_node,
                    "LineID": stub_line,
                    "ParentSectionID": parent_section_id,
                    "reused": True,
                }
        except Exception:
            pass

        # Borrar stub previo residual
        try:
            self.cympy.study.DeleteSection(stub_sec)
        except Exception:
            pass

        line_kind, eq = self._pick_stub_line_equipment(parent_section_id)
        DT = self.cympy.enums.DeviceType
        line_dtype = DT.Underground if line_kind == "Underground" else DT.OverheadLine

        last_err = None
        for kind, eid in (
            (line_kind, eq),
            ("Underground", "XLPE120"),
            ("OverheadLine", eq or "DEFAULT"),
            ("OverheadLine", "DEFAULT"),
        ):
            dtype = DT.Underground if kind == "Underground" else DT.OverheadLine
            try:
                try:
                    self.cympy.study.DeleteSection(stub_sec)
                except Exception:
                    pass
                sec = self.cympy.study.AddSection(
                    stub_sec, net, stub_line, dtype, attach_node, stub_node,
                    "", "DEFAULT", eid or "DEFAULT",
                )
                try:
                    sec.Length = 0.3
                except Exception:
                    pass
                self._offset_stub_node(attach_node, stub_node)
                to_id = str(getattr(sec, "ToNode", None) or stub_node).strip().strip("'\"")
                return {
                    "SectionID": stub_sec,
                    "ToNodeID": to_id or stub_node,
                    "LineID": stub_line,
                    "ParentSectionID": parent_section_id,
                    "EquipmentID": eid,
                    "LineType": kind,
                    "reused": False,
                }
            except Exception as ex:
                last_err = ex
                continue
        raise RuntimeError(
            "No se pudo crear tramo stub para SpotLoad %s en nodo %s: %s"
            % (load_id, attach_node, last_err)
        )

    def _offset_stub_node(self, from_node, stub_node, offset=20.0):
        """Coloca el nodo VIRTUAL cerca del nodo de conexion para ver el simbolo."""
        try:
            nx = float(str(self.cympy.study.QueryInfoNode("CoordX", str(from_node))).replace(",", "."))
            ny = float(str(self.cympy.study.QueryInfoNode("CoordY", str(from_node))).replace(",", "."))
        except Exception:
            return False
        try:
            n = self.cympy.study.GetNode(str(stub_node))
            if n is None:
                return False
            n.X = nx + float(offset)
            n.Y = ny - float(offset)
            return True
        except Exception as ex:
            print("AVISO offset nodo stub %s: %s" % (stub_node, ex))
            return False

    def _add_spot_device(self, load_id, dtype, section_id, loc_enum):
        """AddDevice SpotLoad: sin overwrite primero (coexiste con seccionador), luego OW."""
        Loc = self.cympy.enums.Location
        if loc_enum is None:
            loc_enum = Loc.FirstAvailable
        try:
            self.cympy.study.AddDevice(
                load_id, dtype, section_id, "DEFAULT", loc_enum, False
            )
            return True
        except Exception as ex1:
            msg = str(ex1).lower()
            if "ubicaci" in msg or "overwrite" in msg or "sobreescrib" in msg or "sobrescrib" in msg or "existe" in msg:
                try:
                    self.cympy.study.AddDevice(
                        load_id, dtype, section_id, "DEFAULT", loc_enum, True
                    )
                    return True
                except Exception as ex2:
                    print("AVISO AddDevice overwrite: %s | %s" % (ex1, ex2))
            try:
                self.cympy.study.AddDevice(
                    load_id, dtype, section_id, "DEFAULT", Loc.FirstAvailable, False
                )
                return True
            except Exception:
                pass
            try:
                self.cympy.study.AddDevice(
                    load_id, dtype, section_id, "DEFAULT", loc_enum, True
                )
                return True
            except TypeError:
                self.cympy.study.AddDevice(load_id, dtype, section_id)
                return True
            except Exception as ex3:
                raise RuntimeError(
                    "No se pudo crear SpotLoad %s en %s: %s" % (load_id, section_id, ex3)
                )

    @staticmethod
    def _resolve_spot_location(location, node_id, from_node, to_node):
        """Determina extremo del tramo para dibujar la SpotLoad junto al nodo."""
        def _n(v):
            s = str(v or "").strip()
            if len(s) >= 2 and ((s[0] == s[-1] == "'") or (s[0] == s[-1] == '"')):
                s = s[1:-1].strip()
            return s.upper()

        loc = str(location or "").strip()
        if loc:
            if loc.upper() in ("TO", "T"):
                return "To"
            if loc.upper() in ("FROM", "F"):
                return "From"
            if loc.upper() in ("MIDDLE", "M", "MID"):
                return "Middle"
            return loc if loc in ("From", "To", "Middle") else "To"
        nid = _n(node_id)
        if nid and _n(to_node) == nid:
            return "To"
        if nid and _n(from_node) == nid:
            return "From"
        return "To"

    def save_study(self, path=""):
        path = path or self.settings.get("study_path") or ""
        try:
            from cympy.enums import SaveStudyEquipmentOption
            if path:
                self.cympy.study.Save(path, True, True, SaveStudyEquipmentOption.AllEquipments)
            else:
                self.cympy.study.Save("", True, True, SaveStudyEquipmentOption.AllEquipments)
        except Exception:
            if path:
                self.cympy.study.Save(path)
            else:
                self.cympy.study.Save()
        # Persistir tambien en BD proyecto (necesario para que el simbolo aparezca al reabrir).
        # En estudios de trabajo aislados (1 red) NO tocar SaveProject: borraría redes del proyecto BD.
        if self.settings.get("skip_db_project_save") or self.settings.get("isolated_work_study"):
            return
        try:
            import cympy.db as db
            db.Update()
            try:
                db.SaveProject()
            except Exception:
                pass
        except Exception as ex:
            print("AVISO db.Update/SaveProject: %s" % ex)

    def set_node_base_voltage(self, node_id, kv):
        cfg = self.obj_cfg("Node")
        field = cfg["base_voltage_field"]
        before = self.cympy.study.GetValueNode(field, str(node_id))
        self.cympy.study.SetValueNode(float(kv), field, str(node_id))
        after = self.cympy.study.GetValueNode(field, str(node_id))
        return before, after

    def raise_load_connected_kva(self, load_id, min_kva=None):
        """
        Corrige 260044: capacidad conectada < potencia aparente de la SpotLoad.
        Lee P/Q, calcula S=sqrt(P^2+Q^2) y sube ConnectedKVA a max(actual, S, min_kva)
        con margen 5% redondeado hacia arriba.
        """
        import math
        cfg = self.obj_cfg("Load")
        d = self.get_device("Load", load_id)
        value_base = (
            cfg.get("value_base")
            or "CustomerLoads[0].CustomerLoadModels[0].CustomerLoadValues[0].LoadValue"
        )
        kw = self._parse_load_number(d.GetValue(value_base + ".KW")) or 0.0
        kvar = 0.0
        try:
            kvar = self._parse_load_number(d.GetValue(value_base + ".KVAR")) or 0.0
        except Exception:
            pass
        s_kva = math.sqrt(float(kw) ** 2 + float(kvar) ** 2)
        target = max(float(min_kva or 0), s_kva)
        # Margen 5% y redondeo a entero kVA (mínimo 1)
        target = max(1.0, math.ceil(target * 1.05))

        candidates = [
            cfg.get("connected_kva_field"),
            "CustomerLoads[0].ConnectedKVA",
            "CustomerLoads[0].ConnectedCapacity",
            "CustomerLoads[0].RatedKVA",
            "ConnectedKVA",
        ]
        last_err = None
        for field in candidates:
            if not field:
                continue
            try:
                before = d.GetValue(field)
                before_n = self._parse_load_number(before)
                if before_n is not None and before_n >= target:
                    return before, before, field, "already_ok"
                d.SetValue(float(target), field)
                after = d.GetValue(field)
                return before, after, field, "raised"
            except Exception as ex:
                last_err = ex
                continue
        raise RuntimeError(
            "No se pudo escribir ConnectedKVA en SpotLoad %s (S=%.2f kVA): %s"
            % (load_id, s_kva, last_err)
        )

    def open_tie_at_loop_node(self, node_id, network_id=None, search_all_networks=False):
        """
        Corrige 220048: abre un seccionador/switch cerrado que toque el nodo de bucle.
        Preferencia: dispositivos con ClosedPhase no vacío en secciones incidentes.
        """
        c = self.cympy
        net = str(network_id or (self.settings or {}).get("network_id") or "")
        node_id = str(node_id).rstrip(".,;")
        # Token intermediario (p.ej. 907891) para match parcial
        token = ""
        parts = [p for p in node_id.replace("-", "_").split("_") if p.isdigit() and len(p) >= 4]
        if parts:
            token = parts[-1] if len(parts) == 1 else parts[0]

        nets = []
        if search_all_networks or not net:
            try:
                nets = [str(n) for n in list(c.study.ListNetworks())]
            except Exception:
                nets = [net] if net else []
        else:
            nets = [net]

        # Mapear secciones que tocan el nodo
        section_ids = set()
        try:
            for n in nets:
                for sec in list(c.study.ListSections(n) if n else c.study.ListSections()):
                    try:
                        frm = str(getattr(sec, "FromNodeID", None) or sec.GetValue("FromNodeID") or "")
                        to = str(getattr(sec, "ToNodeID", None) or sec.GetValue("ToNodeID") or "")
                    except Exception:
                        frm = to = ""
                    hit = (frm == node_id or to == node_id)
                    if not hit and token:
                        hit = (token in frm) or (token in to)
                    if hit:
                        sid = str(getattr(sec, "ID", None) or getattr(sec, "SectionID", None) or "")
                        if sid:
                            section_ids.add(sid)
        except Exception as ex:
            raise RuntimeError("No se listaron secciones para nodo bucle %s: %s" % (node_id, ex))

        if not section_ids:
            raise RuntimeError("Nodo de bucle %s sin secciones incidentes" % node_id)

        tried = []
        for dtype_name in ("Sectionalizer", "Switch", "Breaker", "Fuse", "Recloser"):
            try:
                dtype = getattr(c.enums.DeviceType, dtype_name)
            except Exception:
                continue
            for n in nets:
                try:
                    devices = list(c.study.ListDevices(dtype, n) if n else c.study.ListDevices(dtype))
                except Exception:
                    continue
                for d in devices:
                    try:
                        sec = str(getattr(d, "SectionID", None) or d.GetValue("SectionID") or "")
                    except Exception:
                        sec = ""
                    if sec and sec not in section_ids:
                        continue
                    dev_id = str(getattr(d, "DeviceNumber", None) or "")
                    for field, open_val in (
                        ("ClosedPhase", ""),
                        ("ClosedPhase", "None"),
                        ("Status", "Open"),
                        ("NormalStatus", "Open"),
                    ):
                        try:
                            before = d.GetValue(field)
                            before_s = str(before or "").strip()
                            if field == "ClosedPhase" and before_s in ("", "None", "NONE"):
                                continue
                            if field in ("Status", "NormalStatus") and before_s.lower() == "open":
                                continue
                            d.SetValue(open_val, field)
                            after = d.GetValue(field)
                            return {
                                "device": dev_id,
                                "type": dtype_name,
                                "section": sec,
                                "field": field,
                                "before": before_s,
                                "after": str(after or ""),
                                "network": n,
                            }
                        except Exception as ex:
                            tried.append("%s.%s: %s" % (dev_id, field, ex))
                            continue
        raise RuntimeError(
            "No se encontró seccionador cerrado en nodo bucle %s. Intentos: %s"
            % (node_id, "; ".join(tried[:8]) or "ninguno")
        )

    def fix_dual_source_voltage(self, node_id, network_id=None, target_kv=22.9):
        """
        Corrige 480067: nodo alimentado por ≥2 fuentes con tensiones distintas.

        Estrategia (alimentador único):
          1) Desconectar fuentes cuya tensión LL difiere >15% de target_kv
             (p.ej. 10 kV cuando el feeder es 22.9 kV).
          2) Si no hay fuentes desconectables, abrir seccionador/enlace en el nodo
             (misma lógica que open_tie_at_loop_node / 220048).
        """
        c = self.cympy
        net = str(network_id or (self.settings or {}).get("network_id") or "")
        node_id = str(node_id or "").rstrip(".,;")
        target = float(target_kv or 22.9)
        tol = max(1.0, abs(target) * 0.15)

        notes = []
        disconnected = []

        try:
            dtype = c.enums.DeviceType.Source
        except Exception:
            dtype = None
        sources = []
        nets = []
        try:
            nets = [str(n) for n in list(c.study.ListNetworks())]
        except Exception:
            nets = [net] if net else []
        if not nets and net:
            nets = [net]
        if dtype is not None:
            # Importante: el .zxst multi-red mezcla fuentes 10 kV y 22.9 kV.
            # Hay que listar fuentes de TODAS las redes del estudio.
            for n in (nets or [""]):
                try:
                    lst = list(c.study.ListDevices(dtype, n) if n else c.study.ListDevices(dtype))
                except Exception as ex:
                    notes.append("ListSources(%s): %s" % (n, ex))
                    continue
                for d in lst:
                    sources.append((n, d))

        def _read_vll(dev):
            for fld in (
                "OperatingVoltage", "NominalVoltage", "RatedVoltage",
                "Voltage", "DesiredVoltage",
            ):
                try:
                    v = float(str(dev.GetValue(fld)).replace(",", "."))
                    if v > 0.1:
                        # Si parece LN del target (p.ej. 13.2 ≈ 22.9/√3), convertir a LL.
                        # NO convertir 10 kV LL (quedaría ~17.3 y se confundiría con MT).
                        if target >= 18:
                            v_as_ll = v * (3.0 ** 0.5)
                            if abs(v_as_ll - target) + 0.5 < abs(v - target) and 5.0 < v < 16.0:
                                return v_as_ll
                        return v
                except Exception:
                    continue
            # Fases A/B/C (LN)
            vals = []
            for fld in ("OperatingVoltageA", "OperatingVoltageB", "OperatingVoltageC"):
                try:
                    vals.append(float(str(dev.GetValue(fld)).replace(",", ".")))
                except Exception:
                    pass
            if vals:
                vln = sum(vals) / float(len(vals))
                if target >= 18 and 5.0 < vln < 16.0:
                    return vln * (3.0 ** 0.5)
                return vln
            return None

        for net_id, d in sources:
            sid = str(getattr(d, "DeviceNumber", None) or getattr(d, "ID", None) or "")
            vll = _read_vll(d)
            if vll is None:
                notes.append("%s@%s:sin_V" % (sid, net_id[-12:]))
                continue
            if abs(vll - target) <= tol:
                notes.append("%s:keep_V=%.2f" % (sid, vll))
                continue
            # Desconectar fuente secundaria (otra red / otra tensión)
            done = False
            for field, val in (
                ("ConnectionStatus", "Disconnected"),
                ("Status", "Open"),
                ("NormalStatus", "Open"),
                ("ClosedPhase", ""),
            ):
                try:
                    before = d.GetValue(field)
                    d.SetValue(val, field)
                    after = d.GetValue(field)
                    disconnected.append({
                        "source": sid,
                        "network": net_id,
                        "v_ll": vll,
                        "field": field,
                        "before": str(before),
                        "after": str(after),
                    })
                    done = True
                    break
                except Exception:
                    continue
            if not done:
                notes.append("%s:no_disconnect_V=%.2f" % (sid, vll))

        if disconnected:
            return {
                "ok": True,
                "method": "disconnect_mismatch_sources",
                "node_id": node_id,
                "target_kv": target,
                "disconnected": disconnected,
                "before": "; ".join("%s@%.2fkV" % (x["source"], x["v_ll"]) for x in disconnected),
                "after": "Disconnected %d fuente(s) fuera de ±%.1f kV de %.2f" % (
                    len(disconnected), tol, target),
                "notes": notes,
            }

        if str(node_id or "").strip() in ("", "*", "ALL"):
            return {
                "ok": True,
                "method": "disconnect_mismatch_sources",
                "node_id": node_id,
                "target_kv": target,
                "disconnected": [],
                "before": "",
                "after": "Sin fuentes fuera de tolerancia (nada que desconectar)",
                "notes": notes,
            }

        # Fallback: abrir enlace en el nodo (todas las redes; match parcial de ID)
        try:
            tie = self.open_tie_at_loop_node(node_id, net)
            return {
                "ok": True,
                "method": "open_tie",
                "node_id": node_id,
                "target_kv": target,
                "tie": tie,
                "before": "%s.%s=%s" % (tie.get("device"), tie.get("field"), tie.get("before")),
                "after": "OpenTie %s -> %s" % (tie.get("field"), tie.get("after")),
                "notes": notes,
            }
        except Exception as ex_tie:
            # Segundo intento: buscar secciones en todas las redes por substring del nodo
            try:
                tie2 = self.open_tie_at_loop_node(node_id, None, search_all_networks=True)
                return {
                    "ok": True,
                    "method": "open_tie_all_nets",
                    "node_id": node_id,
                    "target_kv": target,
                    "tie": tie2,
                    "before": "%s.%s=%s" % (tie2.get("device"), tie2.get("field"), tie2.get("before")),
                    "after": "OpenTie %s -> %s" % (tie2.get("field"), tie2.get("after")),
                    "notes": notes + ["fallback_all_nets"],
                }
            except Exception as ex_tie2:
                raise RuntimeError(
                    "480067: no se desconectaron fuentes ni se abrió enlace en %s. "
                    "Notas=%s Tie=%s / %s" % (node_id, "; ".join(notes[:8]), ex_tie, ex_tie2)
                )

    def connect_database(self, mdb_path=None, connection_name=None):
        """Conecta la BD Access compartida Electro Dunas (.mdb)."""
        import cympy.db as db
        name = connection_name or self.settings.get("database_connection_name") or ""
        if name:
            try:
                db.ConnectDatabaseByName(str(name))
                self._db_connected = True
                print("BD conectada por nombre:", name)
                return name
            except Exception as ex:
                print("AVISO ConnectDatabaseByName(%s): %s" % (name, ex))

        path = mdb_path or self.settings.get("database_mdb") or ""
        if not path:
            raise RuntimeError("Falta database_mdb en config/settings.json")
        if not os.path.isfile(path):
            raise RuntimeError("No existe la BD: " + path)

        mdb = db.MDBDataSource(path)
        ci = db.ConnectionInformation()
        ci.Name = name or os.path.splitext(os.path.basename(path))[0]
        ci.Network = mdb
        ci.Equipment = mdb
        ci.Project = mdb
        db.Connect(ci)
        self._db_connected = True
        print("BD conectada:", path)
        return path

    def open_study(self, study_path=None, force_backup=None, connect_db=True):
        path = study_path or self.settings.get("study_path") or ""
        if not path:
            raise RuntimeError(
                "Falta study_path / study_file. "
                "Coloque el .zxst en projects_dir o defínalo en config/feeders/<ID>.json."
            )
        if not os.path.isfile(path):
            raise RuntimeError("No existe el estudio: " + path)

        if connect_db and self.settings.get("database_mdb"):
            try:
                self.connect_database()
            except Exception as ex:
                print("AVISO conexión BD (se continúa con study.Open):", ex)

        do_backup = self.settings.get("auto_backup", True) if force_backup is None else force_backup
        if do_backup:
            b = backup_file(path)
            if b:
                print("Backup estudio:", b)

        self.cympy.study.Open(path)
        self._study_open = True
        print("Estudio abierto:", path)

        net = self.settings.get("network_id")
        try:
            nets = [str(x) for x in list(self.cympy.study.ListNetworks())]
            print("Redes en estudio:", ", ".join(nets[:20]))
            if net and net not in nets:
                print("AVISO: network_id %s no aparece en ListNetworks()." % net)
        except Exception as ex:
            print("AVISO ListNetworks:", ex)
        return path

    def ensure_study(self):
        if self._study_open:
            return
        if self.settings.get("dry_run") and not self.settings.get("force_open_study"):
            return
        if self.settings.get("study_path"):
            self.open_study()

    def run_load_flow(self, networks=None):
        net = networks or self.settings.get("network_id")
        if net:
            try:
                return self.command("load_flow", [str(net)])
            except TypeError:
                return self.command("load_flow")
        return self.command("load_flow")

    def run_load_allocation(self, networks=None):
        net = networks or self.settings.get("network_id")
        if net:
            try:
                return self.command("load_allocation", [str(net)])
            except TypeError:
                return self.command("load_allocation")
        return self.command("load_allocation")

    def query_topo(self, keyword, network_id=None, precision=4):
        net = network_id or self.settings.get("network_id")
        return self.cympy.study.QueryInfoTopo(str(keyword), str(net), int(precision))

    def close_study(self, save=False):
        """Cierra el estudio si la API lo permite (evita crash al destruir CymPy)."""
        if not self._study_open:
            return
        try:
            if save and self.settings.get("save_after_fix", True):
                try:
                    self.save_study()
                except Exception as ex:
                    print("AVISO Save antes de Close:", ex)
            close_fn = getattr(self.cympy.study, "Close", None)
            if callable(close_fn):
                close_fn()
            self._study_open = False
        except Exception as ex:
            print("AVISO close_study:", ex)

    def shutdown(self, save=False, ok=True, code=0):
        """Cierre controlado + os._exit para evitar ACCESS_VIOLATION de CymPy al teardown."""
        import os as _os
        try:
            self.close_study(save=save)
        except Exception:
            pass
        if ok:
            _os._exit(0 if code == 0 else int(code))
        _os._exit(int(code) if code else 1)
