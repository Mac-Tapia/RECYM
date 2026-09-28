import { useEffect, useRef, useState } from "react";
import { api, runDetachedJob, type Json } from "../api/client";
import { SearchableSelect } from "../components/SearchableSelect";
import { useFeeder } from "../state/feeder";
import {
  acceptDiscoveryResult,
  beginDatabaseSelection,
  selectFeeder as selectContextFeeder,
  selectStudy,
  type SelectionState,
} from "../context/selection";

type CtxFiles = {
  ok?: boolean;
  databases?: { path: string; name?: string }[] | string[];
  studies?: { path: string; name?: string; feeder_id?: string }[] | string[];
  feeders?: {
    feeder_id: string;
    network_id?: string;
    study_path?: string;
    study_file?: string;
    has_study?: boolean;
    label?: string;
    operational?: boolean;
    inputs_ready?: boolean;
    input_errors?: { code?: string; message?: string }[];
  }[];
  current_database?: string;
  current_study?: string;
  current_feeder?: string;
  current_network?: string;
  n_feeders?: number;
  n_studies?: number;
  msg?: string;
  error?: string;
  networks_source?: string;
  networks_connection?: string;
};

type MedicionFile = { name: string; path: string; size_mb?: number };

type MapAlimentador = {
  feeder_id: string;
  feeder_raw?: string;
  medidor?: string;
  Vll_kV?: number | null;
  siglas?: string;
  label?: string;
};

type CabeceraSess = {
  ok?: boolean;
  feeder_id?: string;
  network_id?: string;
  P_kW?: number | null;
  Q_kvar?: number | null;
  P_kW_medicion?: number | null;
  Q_kvar_medicion?: number | null;
  P_kW_excluidas_restadas?: number | null;
  n_excluidas_cabecera?: number | null;
  cabecera_ajustada_por_excluidas?: boolean;
  S_kVA?: number | null;
  P_avg_kW?: number | null;
  factor_carga_pct?: number | null;
  medidor?: string;
  medicion_file?: string;
  Vll_kV?: number | null;
  Va_kV?: number | null;
  Vb_kV?: number | null;
  Vc_kV?: number | null;
  fecha_medicion?: string;
  status?: string;
  error?: string;
};

type Extraccion = {
  ok?: boolean;
  error?: string;
  msg?: string;
  feeder_id?: string;
  medidor?: string;
  Vll_kV?: number | null;
  P_kW?: number | null;
  Q_kvar?: number | null;
  S_kVA?: number | null;
  P_avg_kW?: number | null;
  factor_carga_pct?: number | null;
  fecha_medicion?: string;
  medicion_file?: string;
  sheet?: string;
  n_samples?: number;
  file_switched?: boolean;
  warnings?: string[];
};

type Resolucion = {
  ok?: boolean;
  error?: string;
  msg?: string;
  feeder_id?: string;
  map_code?: string;
  medidor?: string;
  Vll_kV?: number | null;
  suggested_file?: string | null;
  candidate_files?: { name: string; sheet?: string }[];
  n_candidates?: number;
};

function phaseFromVll(vll: string): string {
  const n = Number(vll);
  if (!(n > 0)) return "";
  return (n / Math.sqrt(3)).toFixed(4);
}

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return String(n);
}

function normalizeVll(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  if (Math.abs(n - 22.9) < 0.05) return "22.9";
  if (Math.abs(n - 10) < 0.05) return "10";
  return String(n);
}

function fmtVllLabel(vll: string): string {
  if (!vll) return "";
  return `${vll} kV`;
}

function asPath(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object" && "path" in item) return String((item as { path: string }).path);
  return String(item || "");
}

function asLabel(item: unknown): string {
  if (typeof item === "string") return item.split(/[/\\]/).pop() || item;
  if (item && typeof item === "object") {
    const o = item as { name?: string; path?: string; feeder_id?: string };
    return o.name || o.feeder_id || (o.path || "").split(/[/\\]/).pop() || "";
  }
  return "";
}

function normPath(p: string): string {
  return (p || "").replace(/\//g, "\\").toLowerCase();
}

/** Código en medidoralimentador: PA217V2 → PA217 */
function mapCodeForFeeder(fid: string): string {
  const u = (fid || "").trim().toUpperCase();
  if (!u) return "";
  const m = u.match(/^([A-Z]{1,3}\d{2,4})V\d+$/);
  return m ? m[1] : u;
}

export function Step1Contexto() {
  const { feeder, network, setFeeder, setContext } = useFeeder();
  const [files, setFiles] = useState<CtxFiles>({});
  const [db, setDb] = useState("");
  const [study, setStudy] = useState("");
  const [feederPick, setFeederPick] = useState("");
  const [medicionFiles, setMedicionFiles] = useState<MedicionFile[]>([]);
  const [mapAlimentadores, setMapAlimentadores] = useState<MapAlimentador[]>([]);
  const [codigoAlimentador, setCodigoAlimentador] = useState("");
  const [medicionFile, setMedicionFile] = useState("");
  const [medidor, setMedidor] = useState("");
  const [pKw, setPKw] = useState("");
  const [qKvar, setQKvar] = useState("");
  const [sKva, setSKva] = useState("");
  const [pAvg, setPAvg] = useState("");
  const [factorCarga, setFactorCarga] = useState("");
  const [vLl, setVLl] = useState("");
  const [vaKv, setVaKv] = useState("");
  const [vbKv, setVbKv] = useState("");
  const [vcKv, setVcKv] = useState("");
  const [fecha, setFecha] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [cabAdjNote, setCabAdjNote] = useState("");
  /** true tras 1.1: BD verificada/creada en CYMDIST y estudio activo */
  const [cymdistReady, setCymdistReady] = useState(false);
  const [cymdistSyncNote, setCymdistSyncNote] = useState("");
  const [selection, setSelection] = useState<SelectionState>({
    databaseMdb: "",
    canonicalDatabaseMdb: "",
    studyPath: "",
    feederId: "",
    networkId: "",
    databaseRequestId: 0,
    feeders: [],
  });
  const selectionRef = useRef(selection);
  const extractSeq = useRef(0);
  const skipCabeceraReload = useRef(false);
  /** Excel medicioncabecera elegido por el usuario (siempre al día; evita stale closure) */
  const medicionFileRef = useRef("");

  function setMedicionFileKeep(name: string) {
    const v = (name || "").trim();
    medicionFileRef.current = v;
    setMedicionFile(v);
  }

  useEffect(() => {
    medicionFileRef.current = medicionFile || "";
  }, [medicionFile]);

  function applyCabeceraToForm(j: CabeceraSess | Extraccion) {
    setPKw(fmtNum(j.P_kW));
    setQKvar(fmtNum(j.Q_kvar));
    setSKva(fmtNum(j.S_kVA));
    setPAvg(fmtNum(j.P_avg_kW));
    setFactorCarga(fmtNum(j.factor_carga_pct));
    if ("medidor" in j && j.medidor) setMedidor(String(j.medidor));
    // No pisar el Excel que el usuario ya eligió (Chincha, etc.)
    if ("medicion_file" in j && j.medicion_file && !medicionFileRef.current) {
      setMedicionFileKeep(String(j.medicion_file));
    }
    const vll = normalizeVll(j.Vll_kV);
    setVLl(vll);
    setFecha(String(j.fecha_medicion || ""));
    const vlnDefault = vll ? phaseFromVll(vll) : "";
    const sess = j as CabeceraSess;
    setVaKv(fmtNum(sess.Va_kV) || vlnDefault);
    setVbKv(fmtNum(sess.Vb_kV) || vlnDefault);
    setVcKv(fmtNum(sess.Vc_kV) || vlnDefault);
    if (
      sess.cabecera_ajustada_por_excluidas &&
      Number(sess.P_kW_excluidas_restadas || 0) > 0
    ) {
      setCabAdjNote(
        `Ajustada en 3.2: P_medicion=${fmtNum(sess.P_kW_medicion)} - sum(Pot_excluidas)=${fmtNum(sess.P_kW_excluidas_restadas)} (${sess.n_excluidas_cabecera ?? "?"} cargas) -> P=${fmtNum(sess.P_kW)}`
      );
    } else {
      setCabAdjNote("");
    }
  }

  async function loadCabecera(fid?: string) {
    const q = fid ? `?feeder=${encodeURIComponent(fid)}` : "";
    const j = await api<CabeceraSess>(`/api/cabecera${q}`);
    if (!j.ok && j.error) throw new Error(j.error);
    applyCabeceraToForm(j);
    if (j.feeder_id) setFeeder(j.feeder_id, j.network_id);
    return j;
  }

  async function loadMedicionFiles() {
    const j = await api<{
      ok?: boolean;
      files?: MedicionFile[];
      alimentadores?: MapAlimentador[];
      error?: string;
      map_error?: string;
    }>("/api/cabecera/medicion/archivos");
    if (!j.ok && j.error) throw new Error(j.error);
    setMedicionFiles(j.files || []);
    setMapAlimentadores(j.alimentadores || []);
    if (j.map_error) {
      setMsg(`Aviso medidoralimentador: ${j.map_error}`);
    }
    return j.files || [];
  }

  async function loadFiles(opts?: { database_mdb?: string; study_path?: string }) {
    const mdb = (opts?.database_mdb || db || "").trim();
    const qs = new URLSearchParams();
    if (mdb) qs.set("database_mdb", mdb);
    if (opts?.study_path || study) qs.set("study_path", opts?.study_path || study);
    const q = qs.toString() ? `?${qs.toString()}` : "";
    const j = await api<CtxFiles>(`/api/contexto/archivos${q}`, { timeoutMs: 30000 });
    if (!j.ok && j.error) throw new Error(j.error);
    setFiles((previous) => ({ ...j, feeders: previous.feeders || [] }));
    const initialDb = mdb || j.current_database || "";
    const initialStudy = opts?.study_path || study || j.current_study || "";
    if (!db && initialDb) setDb(initialDb);
    if (!study && initialStudy) setStudy(initialStudy);
    setSelection((current) => {
      const next = {
        ...current,
        databaseMdb: current.databaseMdb || initialDb,
        canonicalDatabaseMdb: current.canonicalDatabaseMdb || normPath(initialDb),
        studyPath: current.studyPath || initialStudy,
      };
      selectionRef.current = next;
      return next;
    });
    return j;
  }

  async function onPickDatabase(path: string, canonicalPath?: string) {
    setDb(path);
    setCymdistReady(false);
    setCymdistSyncNote("");
    if (!path) {
      setFeederPick("");
      clearMedicionFields();
      setFiles((prev) => ({ ...prev, feeders: [], n_feeders: 0 }));
      return;
    }
    setBusy(true);
    const started = beginDatabaseSelection(selectionRef.current, path, canonicalPath);
    selectionRef.current = started;
    setSelection(started);
    setFeederPick("");
    setFeeder("", "");
    clearMedicionFields();
    setFiles((prev) => ({ ...prev, feeders: [], n_feeders: 0 }));
    const dbName = path.split(/[/\\]/).pop() || path;
    setMsg(`Descubriendo redes reales de ${dbName} en CYMDIST…`);
    try {
      await loadFiles({ database_mdb: path, study_path: study });
      const discovered = await runDetachedJob(
        "contexto_descubrir_redes",
        { database_mdb: path },
        (job) => setMsg(String(job.message || `Descubriendo ${dbName}…`))
      );
      setSelection(() => {
        const current = selectionRef.current;
        const accepted = acceptDiscoveryResult(
          current,
          started.databaseRequestId,
          discovered as Json
        );
        if (accepted !== current) {
          setFiles((previous) => ({
            ...previous,
            feeders: accepted.feeders,
            n_feeders: accepted.feeders.length,
            networks_source: String(discovered.source || "cympy"),
          }));
          setMsg(
            `BD ${dbName} · ${accepted.feeders.length} alimentadores reales · elija alimentador y estudio`
          );
        }
        selectionRef.current = accepted;
        return accepted;
      });
      setContext({ feeder: "", network: "", studyPath: study, databaseMdb: path });
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function browseContextFile(kind: "database" | "study") {
    setMsg(`Abriendo selector de ${kind === "database" ? "MDB" : "estudio"}…`);
    try {
      const current = kind === "database" ? db : study;
      const result = await api<{
        ok?: boolean;
        cancelled?: boolean;
        error?: string;
        path?: string;
        canonical_path?: string;
      }>("/api/contexto/examinar", {
        method: "POST",
        body: JSON.stringify({
          kind,
          initial_dir: current ? current.replace(/[\\/][^\\/]+$/, "") : undefined,
        }),
        timeoutMs: 610000,
        detachedContext: true,
      });
      if (result.cancelled) {
        setMsg("Selección cancelada; el contexto no cambió.");
        return;
      }
      if (!result.ok || !result.path) throw new Error(result.error || "Selector sin ruta");
      if (kind === "database") {
        await onPickDatabase(result.path, result.canonical_path);
      } else {
        onPickStudy(result.path);
        await loadFiles({ database_mdb: db, study_path: result.path });
      }
    } catch (error) {
      setMsg(String(error));
    }
  }

  async function resolverMedicion(fid: string) {
    const j = await api<Resolucion>("/api/cabecera/medicion/resolver", {
      method: "POST",
      body: JSON.stringify({ feeder: fid }),
      timeoutMs: 60000,
    });
    if (!j.ok) throw new Error(j.error || "No se pudo resolver medidor");
    return j;
  }

  function clearMedicionFields(opts?: { keepExcel?: boolean }) {
    setMedidor("");
    setCodigoAlimentador("");
    if (!opts?.keepExcel) {
      setMedicionFileKeep("");
    }
    setPKw("");
    setQKvar("");
    setSKva("");
    setPAvg("");
    setFactorCarga("");
    setVLl("");
    setVaKv("");
    setVbKv("");
    setVcKv("");
    setFecha("");
    setCabAdjNote("");
  }

  async function extraerMedicion(opts?: {
    feeder?: string;
    file?: string;
    silent?: boolean;
    autoFind?: boolean;
    /** Código Excel (medidoralimentador) — manda sobre alimentador BD */
    mapCode?: string;
    /** Si true, no vacía el Excel elegido al fallar (selección manual) */
    keepFileOnError?: boolean;
  }) {
    const fidBd = (opts?.feeder || feederPick || feeder || "").trim();
    // Lookup medidor/Excel: preferir código de medidoralimentador
    const mapCode = (opts?.mapCode || codigoAlimentador || "").trim();
    const fid = (mapCode || fidBd).trim();
    // Preferir Excel explícito / seleccionado (ref); no reutilizar vacío por stale state
    let file =
      opts?.file !== undefined
        ? (opts.file || "").trim()
        : (medicionFileRef.current || medicionFile || "").trim();
    const chosenFile = file;
    const autoFind = opts?.autoFind !== false;
    const keepFileOnError = Boolean(opts?.keepFileOnError);
    if (!fid) {
      if (!opts?.silent)
        setMsg("Elija código alimentador o alimentador (BD) para extracción");
      return null;
    }
    const seq = ++extractSeq.current;
    setBusy(true);
    if (!opts?.silent) {
      setMsg(
        file
          ? `Buscando medidor en hojas de ${file} · ${fid}…`
          : `Extrayendo medición · ${fid} (auto-archivo / todas las hojas)…`
      );
    }
    try {
      if (!file && autoFind) {
        const res = await resolverMedicion(fid);
        if (seq !== extractSeq.current) return null;
        if (mapCode) {
          applyMapMedidor(mapCode, { applyVll: false });
        } else if (res.medidor) {
          setMedidor(res.medidor);
        }
        applyVllFromApi(res.Vll_kV);
        if (res.suggested_file) {
          file = res.suggested_file;
          setMedicionFileKeep(file);
        } else {
          throw new Error(
            res.error ||
              `Sin Excel con medición de ${fid} (medidor ${res.medidor || "?"})`
          );
        }
      }
      if (!file) {
        throw new Error("Elija un Excel de medicioncabecera");
      }
      const j = await api<Extraccion>("/api/cabecera/medicion/extraer", {
        method: "POST",
        body: JSON.stringify({
          feeder: fid,
          medicion_file: file || null,
          auto_find_file: Boolean(autoFind),
        }),
        timeoutMs: 180000,
      });
      if (seq !== extractSeq.current) return null;
      if (!j.ok) throw new Error(j.error || "No se pudo extraer la medición");
      if (!(Number(j.P_kW) > 0) || j.Q_kvar == null || Number.isNaN(Number(j.Q_kvar))) {
        throw new Error(
          `Extracción incompleta para ${fid}: P=${j.P_kW} Q=${j.Q_kvar}`
        );
      }
      applyCabeceraToForm(j);
      // Reafirmar medidor del código; Vll desde API (mapa)
      if (mapCode) {
        applyMapMedidor(mapCode, { applyVll: false });
      } else if (j.medidor) {
        setMedidor(j.medidor);
      }
      // Mostrar SIEMPRE el Excel usado (el elegido por el usuario)
      const usedFile = String(j.medicion_file || chosenFile || file || "").trim();
      if (usedFile) setMedicionFileKeep(usedFile);
      else if (chosenFile) setMedicionFileKeep(chosenFile);
      const vll = applyVllFromApi(j.Vll_kV);
      if (!vll) {
        throw new Error(`Sin Vll para ${fid} en medidoralimentador`);
      }
      const warn =
        j.warnings && j.warnings.length
          ? ` · aviso: ${j.warnings.slice(0, 2).join("; ")}`
          : "";
      const sheetNote = j.sheet ? ` · hoja ${j.sheet}` : "";
      setMsg(
        (j.msg ||
          `OK · ${fid} · medidor ${j.medidor || "?"} · Pmáx=${j.P_kW} · Q=${j.Q_kvar}`) +
          sheetNote +
          warn
      );
      return j;
    } catch (e) {
      if (seq === extractSeq.current) {
        // Conservar código/medidor/Vll/Excel; solo limpiar P/Q/S si falló
        setPKw("");
        setQKvar("");
        setSKva("");
        setPAvg("");
        setFactorCarga("");
        setFecha("");
        setCabAdjNote("");
        if (chosenFile || keepFileOnError) {
          setMedicionFileKeep(chosenFile || medicionFileRef.current || "");
        }
        if (mapCode) applyMapMedidor(mapCode, { applyVll: false });
        let hint = "";
        try {
          const res = await resolverMedicion(fid);
          const names = (res.candidate_files || [])
            .map((c) => c.name)
            .filter(Boolean);
          if (names.length) {
            hint = ` · hoja ${res.medidor || "?"} está en: ${names.join(", ")}`;
          }
        } catch {
          /* sin hint */
        }
        const err = String(e || "Error extracción");
        setMsg(
          err.replace(/^Error:\s*/i, "") +
            (chosenFile || medicionFileRef.current
              ? ` · Excel: ${chosenFile || medicionFileRef.current}`
              : " · elija Excel medicioncabecera") +
            hint
        );
      }
      return null;
    } finally {
      if (seq === extractSeq.current) setBusy(false);
    }
  }

  useEffect(() => {
    (async () => {
      try {
        const catalog = await loadFiles();
        await loadMedicionFiles();
        const fid =
          (catalog.feeders || []).find(
            (f) =>
              String(f.feeder_id).toUpperCase() ===
              String(catalog.current_feeder || "").toUpperCase()
          )?.feeder_id ||
          catalog.current_feeder ||
          "";
        if (fid) await loadCabecera(fid);
      } catch (e) {
        setMsg(String(e));
      }
    })();
  }, []);

  // Al cambiar alimentador activo: sesión previa (salvo si se está extrayendo medición)
  useEffect(() => {
    const fid = (feederPick || feeder || "").trim();
    if (!fid) return;
    if (skipCabeceraReload.current) {
      skipCabeceraReload.current = false;
      return;
    }
    loadCabecera(fid).catch((e) => setMsg(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feederPick]);

  // NOTA: no auto-vincular estudio ↔ alimentador. Un estudio puede tener N redes.

  function applyMapMedidor(fid: string, opts?: { applyVll?: boolean }) {
    const code = (fid || "").trim().toUpperCase();
    if (!code) return null;
    const row =
      mapAlimentadores.find((a) => String(a.feeder_id).toUpperCase() === code) ||
      mapAlimentadores.find((a) => {
        const base = code.replace(/V\d+$/i, "");
        return String(a.feeder_id).toUpperCase() === base;
      });
    if (!row) return null;
    setCodigoAlimentador(String(row.feeder_id));
    if (row.medidor) setMedidor(String(row.medidor));
    // Vll: por defecto sí; tras resolver/extraer API pasar applyVll:false
    // para no pisar el valor fresco de medidoralimentador.xlsx con caché SPA.
    if (opts?.applyVll !== false) {
      const vll = normalizeVll(row.Vll_kV);
      if (vll) {
        setVLl(vll);
        const vln = phaseFromVll(vll);
        setVaKv(vln);
        setVbKv(vln);
        setVcKv(vln);
      }
    }
    return row;
  }

  function applyVllFromApi(raw: unknown) {
    const vll = normalizeVll(raw);
    if (!vll) return "";
    setVLl(vll);
    const vln = phaseFromVll(vll);
    setVaKv(vln);
    setVbKv(vln);
    setVcKv(vln);
    return vll;
  }

  /**
   * Código → medidor + Vll. Si hay Excel, extrae (auto-localiza archivo correcto
   * si el elegido no tiene la hoja del medidor, p.ej. Pisco→Chincha para CA101).
   */
  async function onPickCodigoAlimentador(code: string) {
    setCodigoAlimentador(code);
    if (!code) {
      setMedidor("");
      setVLl("");
      setVaKv("");
      setVbKv("");
      setVcKv("");
      return;
    }
    setPKw("");
    setQKvar("");
    setSKva("");
    setPAvg("");
    setFactorCarga("");
    setFecha("");
    setCabAdjNote("");
    setVLl("");

    const keepExcel = (medicionFileRef.current || medicionFile || "").trim();
    if (keepExcel) setMedicionFileKeep(keepExcel);

    const local = applyMapMedidor(code);
    if (local?.medidor) setMedidor(String(local.medidor));

    let mid = local?.medidor || "";
    let suggested = "";
    try {
      const res = await resolverMedicion(code);
      mid = String(res.medidor || mid).trim();
      if (mid) setMedidor(mid);
      setCodigoAlimentador(String(res.map_code || res.feeder_id || code));
      applyVllFromApi(res.Vll_kV);
      suggested = String(res.suggested_file || "").trim();
    } catch (e) {
      if (!mid) {
        setMsg(String(e));
        return;
      }
    }

    const excel = keepExcel || suggested;
    if (!excel) {
      setMsg(
        `Código ${code} · medidor ${mid || "?"} · elija Excel (Chincha / Ica / Nasca / Pisco)`
      );
      return;
    }
    if (excel) setMedicionFileKeep(excel);

    skipCabeceraReload.current = true;
    await extraerMedicion({
      feeder: code,
      mapCode: code,
      file: excel,
      autoFind: true,
      keepFileOnError: true,
    });
  }

  /** Al elegir Excel: extraer; si no tiene la hoja, auto-pasa al SISTEMA correcto. */
  async function onPickMedicionExcel(fileName: string) {
    const name = (fileName || "").trim();
    setMedicionFileKeep(name);
    if (!name) {
      setMsg("Excel desseleccionado · elija Chincha / Ica / Nasca / Pisco");
      return;
    }
    const code = (codigoAlimentador || feederPick || "").trim();
    if (!code) {
      setMsg(`Excel ${name} · elija código alimentador y pulse Extraer máximos`);
      return;
    }
    skipCabeceraReload.current = true;
    await extraerMedicion({
      feeder: code,
      mapCode: codigoAlimentador || undefined,
      file: name,
      autoFind: true,
      keepFileOnError: true,
    });
  }

  /**
   * Actualiza cabecera/contexto SIN cruzar alimentador ↔ estudio.
   * Un mismo estudio (p.ej. CA101V2.sxst) puede tener varios alimentadores;
   * la selección de cada uno es independiente.
   */
  async function syncFeederStudyCabecera(opts: {
    feederId?: string;
    studyPath?: string;
    extract?: boolean;
    /** Si true, no tocar el alimentador actual (solo estudio). */
    keepFeeder?: boolean;
    /** Si true, no tocar el estudio actual (solo alimentador). */
    keepStudy?: boolean;
  }) {
    const keepFeeder = Boolean(opts.keepFeeder);
    const keepStudy = Boolean(opts.keepStudy);

    let fid = keepFeeder
      ? (feederPick || feeder || "").trim()
      : (opts.feederId !== undefined ? String(opts.feederId || "").trim() : (feederPick || "").trim());
    let stPath = keepStudy
      ? (study || "").trim()
      : (opts.studyPath !== undefined ? String(opts.studyPath || "").trim() : (study || "").trim());

    if (!keepFeeder && opts.feederId !== undefined) {
      setFeederPick(fid);
    }
    if (!keepStudy && opts.studyPath !== undefined) {
      setStudy(stPath || "");
    }

    const row = (files.feeders || []).find(
      (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
    );
    setContext({
      feeder: fid || "",
      network: row?.network_id || "",
      studyPath: stPath || "",
      databaseMdb: db || "",
      inputsReady: row?.inputs_ready ?? null,
      inputErrors: (row?.input_errors || []).map((e) =>
        String(e.message || e.code || "Entrada inválida")
      ),
    });
    if (!keepFeeder) {
      if (fid) setFeeder(fid, row?.network_id);
      else setFeeder("", undefined);
    }

    if (!keepFeeder) {
      clearMedicionFields({ keepExcel: true });
      const mapCode = mapCodeForFeeder(fid);
      if (mapCode) applyMapMedidor(mapCode);
    }

    if (!fid && !stPath) {
      setMsg("Elija alimentador y estudio (independientes)");
      return;
    }

    if (!keepFeeder) {
      skipCabeceraReload.current = true;
      try {
        if (fid) await loadCabecera(fid);
      } catch {
        /* sin sesión previa */
      }
      const mapCode = mapCodeForFeeder(fid);
      if (mapCode) applyMapMedidor(mapCode);

      const keepExcel = (medicionFileRef.current || "").trim();
      if (opts.extract !== false && (fid || mapCode)) {
        await extraerMedicion({
          feeder: fid || mapCode,
          mapCode: mapCode || undefined,
          file: keepExcel,
          autoFind: !keepExcel,
          keepFileOnError: true,
        });
        return;
      }
    }

    const stName = (stPath || "").split(/[/\\]/).pop() || "—";
    setMsg(
      `Contexto · alimentador ${fid || "—"} · estudio ${stName}` +
        (db ? ` · BD ${(db.split(/[/\\]/).pop() || "")}` : "") +
        " · independientes · pulse 1.1"
    );
  }

  function onPickFeeder(fid: string, opts?: { extract?: boolean }) {
    setCymdistReady(false);
    setCymdistSyncNote("");
    const row = (files.feeders || []).find(
      (item) => String(item.feeder_id).toUpperCase() === String(fid).toUpperCase()
    );
    const networkId = String(row?.network_id || "");
    setSelection((current) => {
      const next = selectContextFeeder(current, fid, networkId);
      selectionRef.current = next;
      return next;
    });
    setFeederPick(fid);
    setFeeder(fid, networkId);
    // Solo alimentador: no cambiar ni filtrar el estudio elegido
    void syncFeederStudyCabecera({
      feederId: fid,
      keepStudy: true,
      extract: opts?.extract !== false,
    });
  }

  function onPickStudy(path: string) {
    setCymdistReady(false);
    setCymdistSyncNote("");
    setSelection((current) => {
      const next = selectStudy(current, path);
      selectionRef.current = next;
      return next;
    });
    setStudy(path);
    setContext({ studyPath: path });
    // Solo estudio: no cambiar el alimentador (un .sxst puede tener N redes)
    void syncFeederStudyCabecera({
      studyPath: path,
      keepFeeder: true,
      extract: false,
    });
  }

  async function applyContext() {
    setBusy(true);
    setMsg("1.1 · Verificando BD en CYMDIST (existe → conectar; no existe → crear) y activando estudio…");
    setCymdistReady(false);
    setCymdistSyncNote("");
    try {
      const fid = (feederPick || feeder || "").trim();
      const stPath = (study || "").trim();
      const selected = (files.feeders || []).find(
        (item) => String(item.feeder_id).toUpperCase() === fid.toUpperCase()
      );
      const networkId = String(selected?.network_id || network || "").trim();
      if (!db) {
        throw new Error("Seleccione la base de datos (.mdb) antes de 1.1");
      }
      if (!fid) {
        throw new Error("Seleccione el alimentador (BD) antes de 1.1");
      }
      if (!stPath) {
        throw new Error("Seleccione el estudio (.zxst/.xst) antes de 1.1");
      }
      if (!networkId) {
        throw new Error("El alimentador seleccionado no tiene NetworkID descubierto");
      }

      const j = await api<{
        ok?: boolean;
        error?: string;
        feeder_id?: string;
        network_id?: string;
        study_path?: string;
        ui_study_path?: string;
        study_file?: string;
        database_mdb?: string;
        database_connection_name?: string;
        context_fingerprint?: string;
        msg?: string;
        cymdist_sync?: {
          ok?: boolean;
          error?: string;
          msg?: string;
          db_action?: string;
          db_created?: boolean;
          db_existed?: boolean;
          database_connection_name?: string;
          study_path?: string;
          database_mdb?: string;
        };
        cymdist_sync_error?: string;
      }>("/api/contexto/aplicar", {
        method: "POST",
        body: JSON.stringify({
          database_mdb: db,
          study_path: stPath,
          feeder_id: fid,
          network_id: networkId,
          allowed_networks: (files.feeders || []).map((item) => ({
            feeder_id: item.feeder_id,
            network_id: item.network_id,
            label: item.label,
          })),
        }),
      });
      if (!j.ok) throw new Error(j.error || "Error contexto");

      const returnedStudy = j.ui_study_path || j.study_path || "";
      const identityMatches =
        normPath(String(j.database_mdb || "")) === normPath(db) &&
        normPath(returnedStudy) === normPath(stPath) &&
        String(j.feeder_id || "").toUpperCase() === fid.toUpperCase() &&
        String(j.network_id || "").toUpperCase() === networkId.toUpperCase();
      if (!identityMatches) {
        throw new Error("CONTEXT_IDENTITY_MISMATCH: 1.1 devolvió otro contexto");
      }

      const sync = j.cymdist_sync || {};
      if (j.cymdist_sync_error || (sync && sync.ok === false)) {
        throw new Error(
          j.cymdist_sync_error ||
            sync.error ||
            "CYMDIST no pudo verificar/activar la BD y el estudio"
        );
      }

      const resolved = j.feeder_id || fid;
      if (resolved) {
        setFeederPick(resolved);
        setFeeder(resolved, j.network_id || networkId);
      }
      // Conservar elección UI (.xst); CYMDIST abre study_path (.zxst) en backend
      const uiStudy = j.ui_study_path || stPath || j.study_path || "";
      if (uiStudy) setStudy(uiStudy);
      setContext({
        feeder: resolved || "",
        network: j.network_id || networkId,
        studyPath: uiStudy || j.study_path || "",
        databaseMdb: db || j.database_mdb || "",
        contextFingerprint: j.context_fingerprint || "",
        inputsReady: (files.feeders || []).find(
          (f) => String(f.feeder_id).toUpperCase() === resolved.toUpperCase()
        )?.inputs_ready ?? null,
        inputErrors: ((files.feeders || []).find(
          (f) => String(f.feeder_id).toUpperCase() === resolved.toUpperCase()
        )?.input_errors || []).map((e) => String(e.message || e.code || "Entrada inválida")),
      });

      const connName =
        sync.database_connection_name ||
        j.database_connection_name ||
        "";
      let dbBit = "";
      if (sync.db_created || sync.db_action === "created_and_linked") {
        dbBit = `BD creada y vinculada «${connName || "?"}»`;
      } else if (sync.db_existed || sync.db_action === "activated_existing") {
        dbBit = `BD existente conectada «${connName || "?"}»`;
      } else if (connName) {
        dbBit = `BD «${connName}» activada`;
      } else {
        dbBit = "BD activada por ruta";
      }
      const studyName = (uiStudy || sync.study_path || "").split(/[/\\]/).pop() || "—";
      const syncNote = `${dbBit} · estudio ${studyName} activo en CYMDIST`;
      setCymdistSyncNote(syncNote);
      setCymdistReady(true);

      // Solo después de conectar CYMDIST: cargar mediciones de cabecera (Excel → formulario)
      skipCabeceraReload.current = true;
      await syncFeederStudyCabecera({
        feederId: resolved,
        studyPath: uiStudy,
        keepStudy: false,
        extract: true,
      });
      setMsg(
        `Listo · ${syncNote}` +
          (resolved ? ` · alimentador ${resolved}` : "") +
          (j.network_id ? ` · red ${j.network_id}` : "") +
          " · ya puede cargar mediciones en la fuente (1.2)"
      );
    } catch (e) {
      setCymdistReady(false);
      setCymdistSyncNote("");
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveHead(previewOnly = false) {
    if (!previewOnly && !cymdistReady) {
      setMsg(
        "Pulse primero «1.1 · Verificar y conectar en CYMDIST» (crea o activa la BD y el estudio) antes de cargar la cabecera en la fuente."
      );
      return;
    }
    setBusy(true);
    setMsg(previewOnly ? "Recalculando P/Q…" : "Cargando en la fuente…");
    try {
      const fid = (feederPick || feeder || "").trim();
      if (!fid) {
        throw new Error("Seleccione el alimentador (BD) antes de cargar cabecera");
      }
      setFeeder(fid);
      if (!previewOnly && !vLl) {
        throw new Error(
          "Falta Vll: extraiga medición (Vll viene de medidoralimentador) o verifique el mapeo del alimentador"
        );
      }
      const body = {
        mode: "KW_KVAR",
        P_kW: pKw === "" ? null : Number(pKw),
        Q_kvar: qKvar === "" ? null : Number(qKvar),
        S_kVA: sKva === "" ? null : Number(sKva),
        P_avg_kW: pAvg === "" ? null : Number(pAvg),
        factor_carga_pct: factorCarga === "" ? null : Number(factorCarga),
        medidor: medidor || undefined,
        medicion_file: medicionFile || undefined,
        Vll_kV: vLl === "" ? null : Number(vLl),
        Va_kV: vaKv === "" ? null : Number(vaKv),
        Vb_kV: vbKv === "" ? null : Number(vbKv),
        Vc_kV: vcKv === "" ? null : Number(vcKv),
        fecha_medicion: fecha,
        database_mdb: db || undefined,
        study_path: study || undefined,
        feeder: fid || undefined,
        preview_only: previewOnly,
        reset_downstream: !previewOnly,
      };
      const j = await api<{
        ok?: boolean;
        error?: string;
        msg?: string;
        P_kW?: number;
        Q_kvar?: number;
        S_kVA?: number;
        P_avg_kW?: number;
        factor_carga_pct?: number;
        Vll_kV?: number;
        Va_kV?: number;
        Vb_kV?: number;
        Vc_kV?: number;
        fecha_medicion?: string;
        feeder_id?: string;
        network_id?: string;
        session_saved?: boolean;
      }>("/api/cabecera", { method: "POST", body: JSON.stringify(body), timeoutMs: 180000 });
      // Mantener en pantalla lo último enviado / guardado (no vaciar campos)
      if (!previewOnly || j.P_kW != null) {
        applyCabeceraToForm({
          P_kW: j.P_kW ?? body.P_kW,
          Q_kvar: j.Q_kvar ?? body.Q_kvar,
          S_kVA: j.S_kVA ?? body.S_kVA,
          P_avg_kW: j.P_avg_kW ?? body.P_avg_kW,
          factor_carga_pct: j.factor_carga_pct ?? body.factor_carga_pct,
          Vll_kV: j.Vll_kV ?? body.Vll_kV,
          Va_kV: j.Va_kV ?? body.Va_kV,
          Vb_kV: j.Vb_kV ?? body.Vb_kV,
          Vc_kV: j.Vc_kV ?? body.Vc_kV,
          fecha_medicion: j.fecha_medicion ?? fecha,
          medidor,
          medicion_file: medicionFile,
        });
      }
      if (j.feeder_id) {
        setFeederPick(j.feeder_id);
        setFeeder(j.feeder_id, j.network_id);
      }
      if (!j.ok && !previewOnly) {
        // Sesión ya quedó guardada aunque CYMDIST falle: no perder valores en UI
        if (j.session_saved) {
          setMsg(j.error || j.msg || "Sesión guardada; reintente CYMDIST");
          return;
        }
        throw new Error(j.error || j.msg || "Fallo cabecera");
      }
      // Releer sesión para confirmar persistencia
      if (!previewOnly) {
        try {
          await loadCabecera(j.feeder_id || fid || undefined);
        } catch {
          /* form ya tiene los valores del POST */
        }
      }
      setMsg(
        j.msg ||
          (previewOnly
            ? "P/Q recalculado"
            : `Cabecera OK · ${j.feeder_id || fid} · ${j.network_id || ""} · Vll ${vLl} kV`)
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  const dbs = files.databases || [];
  const studies = files.studies || [];
  const feeders = files.feeders || [];
  const selectedFeeder = feeders.find(
    (f) => String(f.feeder_id).toUpperCase() === (feederPick || feeder).toUpperCase()
  );
  const showPhases = Boolean(vLl);

  const dbOptions = dbs.map((d) => {
    const p = asPath(d);
    return { value: p, label: asLabel(d), searchText: p };
  });
  const feederOptions = feeders.map((f) => {
    const nid = String(f.network_id || "").trim();
    // Solo código (+ red si existe). Nunca «(solo estudio)» en el label.
    const label = nid ? `${f.feeder_id} · ${nid}` : String(f.feeder_id);
    return {
      value: f.feeder_id,
      label,
      searchText: `${f.feeder_id} ${nid} ${f.label || ""}`,
    };
  });
  const codigoAlimentadorOptions = mapAlimentadores.map((a) => ({
    value: a.feeder_id,
    // Solo código (columna codigo alimentador); el medidor va al campo Medidor
    label: a.feeder_raw || a.feeder_id,
    searchText: `${a.feeder_id} ${a.feeder_raw || ""} ${a.medidor || ""} ${a.siglas || ""}`,
  }));
  // Todos los estudios del catálogo (no filtrar ni priorizar por alimentador)
  const studyOptions = studies
    .map((s) => {
      const p = asPath(s);
      return {
        value: p,
        label: asLabel(s),
        searchText: `${p} ${asLabel(s)}`,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
  const medicionOptions = medicionFiles.map((f) => ({
    value: f.name,
    label: f.size_mb != null ? `${f.name} (${f.size_mb} MB)` : f.name,
    searchText: f.name,
  }));

  return (
    <section className="panel">
      <h2>1 · Contexto + cabecera</h2>
      <p className="muted">
        1) Elija <b>base .mdb</b>, <b>alimentador</b> y <b>estudio</b>{" "}
        <i>(independientes: un estudio puede tener varios alimentadores)</i>. 2) Pulse{" "}
        <b>1.1</b>: RECYM verifica si esa BD ya está en CYMDIST — si <b>no</b> existe
        la crea y la vincula; si <b>sí</b> existe solo la conecta — y activa el
        estudio. 3) Luego cargue mediciones y pulse <b>1.2</b> para escribir en la
        fuente (solo con 1.1 OK).
      </p>

      <div className="grid">
        <div>
          <label>Base de datos (.mdb)</label>
          <SearchableSelect
            value={db}
            options={dbOptions}
            disabled={busy}
            onChange={(v) => onPickDatabase(v)}
            placeholder="Buscar .mdb…"
            emptyLabel="—"
          />
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={() => browseContextFile("database")}
            style={{ marginTop: 6 }}
          >
            Examinar MDB…
          </button>
          {db && <p className="muted path-full">{db}</p>}
        </div>
        <div>
          <label>
            Alimentador (BD)
            {feeders.length ? ` · ${feeders.length}` : ""}
          </label>
          <SearchableSelect
            value={feederPick}
            options={feederOptions}
            disabled={busy}
            placeholder={
              busy
                ? "Cargando alimentadores…"
                : feeders.length
                  ? "Escriba PA, IN, NA…"
                  : "Elija BD y espere el catálogo…"
            }
            emptyLabel="— elegir —"
            onChange={(v) => onPickFeeder(v, { extract: true })}
          />
        </div>
        <div>
          <label>
            Estudio (.zxst/.xst)
            {studies.length ? ` · ${studies.length}` : ""}
          </label>
          <SearchableSelect
            value={study}
            options={studyOptions}
            disabled={busy}
            onChange={(v) => onPickStudy(v)}
            placeholder="Buscar estudio…"
            emptyLabel="—"
          />
          <button
            type="button"
            className="ghost"
            disabled={busy}
            onClick={() => browseContextFile("study")}
            style={{ marginTop: 6 }}
          >
            Examinar estudio…
          </button>
          {study && <p className="muted path-full">{study}</p>}
          <p className="muted" style={{ marginTop: 4, fontSize: 12 }}>
            {(() => {
              const name = (study || "").split(/[/\\]/).pop() || "";
              if (!study) {
                return "Elija el estudio (independiente del alimentador); luego 1.1.";
              }
              return (
                `${name}` +
                (feederPick ? ` · alim. ${feederPick}` : "") +
                (db ? ` · BD ${(db.split(/[/\\]/).pop() || "")}` : "") +
                " · pulse 1.1 antes de cargar cabecera."
              );
            })()}
          </p>
        </div>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Activo: <b>{feederPick || feeder || "—"}</b>
        {" · "}red <b>{network || "—"}</b>
        {" · "}
        {cymdistReady ? (
          <span className="ok">CYMDIST listo · {cymdistSyncNote || "BD + estudio"}</span>
        ) : (
          <>
            Pulse <b>1.1</b> para verificar/crear la BD y activar el estudio en CYMDIST
            antes de la cabecera.
          </>
        )}
      </p>
      {selectedFeeder && (
        <div className={selectedFeeder.inputs_ready ? "pathbox ok" : "pathbox bad"}>
          Contexto CYMDIST: {selectedFeeder.operational ? "disponible" : "incompleto"}
          {" · "}Entradas Excel: {selectedFeeder.inputs_ready ? "listas" : "bloqueadas"}
          {!selectedFeeder.inputs_ready && selectedFeeder.input_errors?.length
            ? ` · ${selectedFeeder.input_errors.map((e) => e.message || e.code).join(" · ")}`
            : ""}
        </div>
      )}
      <div className="actions">
        <button
          type="button"
          className="secondary"
          disabled={busy || !db || !study || !feederPick || selectedFeeder?.operational === false}
          onClick={applyContext}
          title="Verifica si la BD existe en CYMDIST; si no, la crea; luego activa el estudio"
        >
          1.1 · Verificar y conectar en CYMDIST
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy}
          title="Solo refresca código alimentador / Excel medicioncabecera / Vll (no toca BD, alimentador ni estudio de arriba)"
            onClick={async () => {
            const keepCode = (codigoAlimentador || "").trim();
            const keepExcel = (medicionFileRef.current || medicionFile || "").trim();
            setBusy(true);
            setMsg("Actualizando listas de medición (abajo)…");
            try {
              const files = await loadMedicionFiles();
              // Reaplicar código → medidor + Vll frescos desde medidoralimentador.xlsx
              if (keepCode) {
                setCodigoAlimentador(keepCode);
                try {
                  const res = await resolverMedicion(keepCode);
                  if (res.medidor) setMedidor(String(res.medidor));
                  applyVllFromApi(res.Vll_kV);
                  // Excel independiente: solo conservar el elegido; nunca imponer suggested_file
                  if (keepExcel) setMedicionFileKeep(keepExcel);
                  setMsg(
                    `Medición actualizada · ${keepCode} · medidor ${res.medidor || "?"} · Vll ${normalizeVll(res.Vll_kV) || "?"} kV` +
                      (keepExcel ? ` · Excel ${keepExcel}` : " · elija Excel") +
                      ` · ${files.length} archivo(s)`
                  );
                } catch (e) {
                  applyMapMedidor(keepCode);
                  if (keepExcel) setMedicionFileKeep(keepExcel);
                  setMsg(`Listas medición OK · aviso lookup: ${String(e)}`);
                }
              } else {
                if (keepExcel) setMedicionFileKeep(keepExcel);
                setMsg(
                  `Listas medición OK · ${files.length} Excel · elija código alimentador`
                );
              }
            } catch (e) {
              setMsg(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Actualizar listas
        </button>
      </div>

      <h3>Medición de cabecera</h3>
      <p className="muted">
        Primero complete <b>1.1</b>. Elija <b>código alimentador</b> (medidor/Vll) y
        luego <b>uno de los 4 Excel</b> medicioncabecera (Chincha / Ica / Nasca /
        Pisco): al seleccionarlo se extraen P/Q/S de la hoja del medidor. También
        puede pulsar <b>Extraer máximos</b>. Luego <b>1.2</b> escribe en la fuente.
      </p>

      <div className="grid">
        <div>
          <label>Código alimentador</label>
          <SearchableSelect
            value={codigoAlimentador}
            options={codigoAlimentadorOptions}
            disabled={busy}
            placeholder="Columna codigo alimentador…"
            emptyLabel="— elegir código —"
            onChange={(v) => onPickCodigoAlimentador(v)}
          />
        </div>
        <div>
          <label>Medidor</label>
          <input
            value={medidor}
            readOnly
            placeholder="auto al elegir código"
            title="Columna Medidor de medidoralimentador.xlsx"
          />
        </div>
        <div>
          <label>Vll (kV)</label>
          <input
            value={fmtVllLabel(vLl)}
            readOnly
            placeholder="auto al elegir código"
            title="Nivel Tension en medidoralimentador.xlsx"
          />
        </div>
        <div>
          <label>
            Excel medicioncabecera
            {medicionFiles.length ? ` · ${medicionFiles.length}` : " · sin archivos"}
          </label>
          <SearchableSelect
            value={medicionFile}
            options={medicionOptions}
            disabled={false}
            allowEmpty={false}
            placeholder={
              medicionFiles.length
                ? "Elegir SISTEMA Chincha / Ica / Nasca / Pisco…"
                : "Sin Excel — pulse Actualizar listas"
            }
            emptyLabel="— elegir Excel —"
            onChange={(v) => {
              void onPickMedicionExcel(v);
            }}
          />
        </div>
        <div className="actions" style={{ alignItems: "end", margin: 0 }}>
          <button
            type="button"
            className="ghost"
            disabled={busy || !(codigoAlimentador || feederPick)}
            title="Extrae Pmáx/Q/S desde el Excel seleccionado (hoja = medidor)"
            onClick={() => {
              const code = (codigoAlimentador || feederPick || "").trim();
              const file = (medicionFileRef.current || medicionFile || "").trim();
              if (!file) {
                setMsg(
                  "Seleccione uno de los 4 Excel (Chincha / Ica / Nasca / Pisco) para Extraer máximos"
                );
                return;
              }
              if (!code) {
                setMsg("Elija código alimentador antes de Extraer máximos");
                return;
              }
              void extraerMedicion({
                feeder: code,
                mapCode: codigoAlimentador || undefined,
                file,
                autoFind: true,
                keepFileOnError: true,
              });
            }}
          >
            Extraer máximos
          </button>
        </div>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div>
          <label>P (kW) máx</label>
          <input value={pKw} onChange={(e) => setPKw(e.target.value)} />
        </div>
        <div>
          <label>Q (kvar)</label>
          <input value={qKvar} onChange={(e) => setQKvar(e.target.value)} />
        </div>
        <div>
          <label>S (kVA)</label>
          <input value={sKva} onChange={(e) => setSKva(e.target.value)} />
        </div>
        <div>
          <label>Fecha medición</label>
          <input value={fecha} onChange={(e) => setFecha(e.target.value)} />
        </div>
        <div>
          <label>P (kW) promedio</label>
          <input value={pAvg} onChange={(e) => setPAvg(e.target.value)} />
        </div>
        <div>
          <label>Factor de carga (%)</label>
          <input
            value={factorCarga}
            onChange={(e) => setFactorCarga(e.target.value)}
            title="P promedio / P máxima × 100"
          />
        </div>
      </div>
      {cabAdjNote ? <p className="muted" style={{ marginTop: 8 }}>{cabAdjNote}</p> : null}

      {showPhases && (
        <>
          <h3 style={{ marginTop: 16 }}>Tensiones de fase (kV LN)</h3>
          <p className="muted">
            Prefijadas a Vll/√3 ({phaseFromVll(vLl)} kV). Editable por fase antes de cargar en CYMDIST.
          </p>
          <div className="grid">
            <div>
              <label>A (kV)</label>
              <input value={vaKv} onChange={(e) => setVaKv(e.target.value)} />
            </div>
            <div>
              <label>B (kV)</label>
              <input value={vbKv} onChange={(e) => setVbKv(e.target.value)} />
            </div>
            <div>
              <label>C (kV)</label>
              <input value={vcKv} onChange={(e) => setVcKv(e.target.value)} />
            </div>
          </div>
        </>
      )}

      <div className="actions">
        <button
          type="button"
          disabled={busy || !cymdistReady}
          onClick={() => saveHead(false)}
          title={
            cymdistReady
              ? "Escribe P/Q/Vph en la fuente del estudio activo en CYMDIST"
              : "Debe pulsar 1.1 antes (verificar/crear BD y activar estudio)"
          }
        >
          1.2 · Cargar en la fuente
        </button>
        <button type="button" className="ghost" disabled={busy} onClick={() => saveHead(true)}>
          Recalcular P/Q
        </button>
        <span className="muted">{msg}</span>
      </div>
    </section>
  );
}
