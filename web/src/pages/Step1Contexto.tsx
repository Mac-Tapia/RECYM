import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { SearchableSelect } from "../components/SearchableSelect";
import { useFeeder } from "../state/feeder";

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

function feederFromStudy(path: string): string {
  const base = (path || "").split(/[/\\]/).pop() || "";
  const stem = base.replace(/\.(zxst|zsxst|sxst|xst)$/i, "");
  if (!stem || stem.toUpperCase() === "ELD") return "";
  return stem;
}

function normPath(p: string): string {
  return (p || "").replace(/\//g, "\\").toLowerCase();
}

function studyBasename(path: string): string {
  return ((path || "").split(/[/\\]/).pop() || "").toLowerCase();
}

/** Código en medidoralimentador: PA217V2 → PA217 */
function mapCodeForFeeder(fid: string): string {
  const u = (fid || "").trim().toUpperCase();
  if (!u) return "";
  const m = u.match(/^([A-Z]{1,3}\d{2,4})V\d+$/);
  return m ? m[1] : u;
}

function studyStem(pathOrLabel: string): string {
  return (pathOrLabel || "")
    .split(/[/\\]/)
    .pop()!
    .replace(/\.(zxst|sxst|zsxst|xst)$/i, "")
    .toUpperCase();
}

/** Familia del alimentador: PA217, PA217V2, PA217_ALT → PA217 */
function feederFamily(fid: string): string {
  const u = (fid || "").trim().toUpperCase();
  if (!u) return "";
  const base = mapCodeForFeeder(u);
  // PA217_ALT / PA217-2 → PA217
  const m = base.match(/^([A-Z]{1,3}\d{2,4})/);
  return m ? m[1] : base;
}

function studyBelongsToFeeder(studyPath: string, fid: string): boolean {
  const stem = feederFromStudy(studyPath);
  if (!stem || !fid) return false;
  const fu = fid.toUpperCase();
  const su = stem.toUpperCase();
  if (su === fu) return true;
  return feederFamily(su) === feederFamily(fu);
}

/** Todos los estudios del mismo alimentador (puede haber varios: PA217.zxst, PA217v2.xst…). */
function listStudiesForFeeder(fid: string, files: CtxFiles): string[] {
  const id = (fid || "").trim();
  if (!id) return [];
  const fam = feederFamily(id);
  const out: { path: string; score: number }[] = [];
  for (const s of files.studies || []) {
    const p = asPath(s);
    const stem = studyStem(asLabel(s) || p);
    if (!stem || stem === "ELD") continue;
    if (feederFamily(stem) !== fam && stem !== id.toUpperCase()) continue;
    let score = 50;
    if (stem === id.toUpperCase()) score = 0;
    else if (stem === fam) score = 1;
    else if (stem.startsWith(fam)) score = 2;
    out.push({ path: p, score });
  }
  out.sort((a, b) => a.score - b.score || a.path.localeCompare(b.path));
  // únicos por path
  const seen = new Set<string>();
  const paths: string[] = [];
  for (const it of out) {
    const k = normPath(it.path);
    if (seen.has(k)) continue;
    seen.add(k);
    paths.push(it.path);
  }
  return paths;
}

/**
 * Elige un estudio por defecto para el alimentador.
 * Si preferPath ya es de la familia, lo conserva (varios estudios por alim.).
 */
function resolveStudyForFeeder(
  fid: string,
  files: CtxFiles,
  preferPath?: string
): string {
  const related = listStudiesForFeeder(fid, files);
  if (!related.length) {
    const eld = (files.studies || []).find((s) => {
      const n = asLabel(s).toUpperCase();
      return n === "ELD.ZXST" || n.startsWith("ELD.");
    });
    return eld ? asPath(eld) : "";
  }
  if (preferPath && related.some((p) => normPath(p) === normPath(preferPath))) {
    return preferPath;
  }
  // Preferir match exacto de stem, luego el primero de la familia
  const idU = fid.toUpperCase();
  const exact = related.find((p) => studyStem(p) === idU);
  return exact || related[0];
}

/**
 * Estudio → alimentador BD: preferir la red de la BD (con network_id),
 * no la entrada huérfana «solo estudio» (PA217v2.xst → PA217 en BD).
 */
function resolveFeederForStudy(studyPath: string, files: CtxFiles): string {
  const stem = feederFromStudy(studyPath);
  if (!stem) return "";
  const feeders = files.feeders || [];
  const fam = feederFamily(stem);
  const stemU = stem.toUpperCase();

  const hasNet = (f: { network_id?: string; label?: string }) =>
    Boolean(String(f.network_id || "").trim()) &&
    !String(f.label || "").toLowerCase().includes("solo estudio");

  // 1) Misma familia con red BD (p.ej. PA217)
  const bdFam = feeders.find(
    (f) => feederFamily(f.feeder_id) === fam && hasNet(f)
  );
  if (bdFam) return bdFam.feeder_id;

  // 2) Stem exacto con red BD
  const exactBd = feeders.find(
    (f) => String(f.feeder_id).toUpperCase() === stemU && hasNet(f)
  );
  if (exactBd) return exactBd.feeder_id;

  // 3) Cualquier entrada con red en la familia
  const anyBd = feeders.find(
    (f) =>
      (String(f.feeder_id).toUpperCase() === stemU ||
        feederFamily(f.feeder_id) === fam) &&
      String(f.network_id || "").trim()
  );
  if (anyBd) return anyBd.feeder_id;

  // 4) Huérfano / solo estudio
  const orphan = feeders.find(
    (f) => String(f.feeder_id).toUpperCase() === stemU
  );
  if (orphan) return orphan.feeder_id;

  return stem;
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
  const extractSeq = useRef(0);
  const skipCabeceraReload = useRef(false);

  function applyCabeceraToForm(j: CabeceraSess | Extraccion) {
    setPKw(fmtNum(j.P_kW));
    setQKvar(fmtNum(j.Q_kvar));
    setSKva(fmtNum(j.S_kVA));
    setPAvg(fmtNum(j.P_avg_kW));
    setFactorCarga(fmtNum(j.factor_carga_pct));
    if ("medidor" in j && j.medidor) setMedidor(String(j.medidor));
    if ("medicion_file" in j && j.medicion_file) setMedicionFile(String(j.medicion_file));
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

  async function loadFiles(opts?: { database_mdb?: string; refresh?: boolean }) {
    const mdb = (opts?.database_mdb || "").trim();
    const refresh = Boolean(opts?.refresh);
    const qs = new URLSearchParams();
    if (mdb) qs.set("database_mdb", mdb);
    if (refresh) qs.set("refresh", "1");
    const q = qs.toString() ? `?${qs.toString()}` : "";
    const j = await api<CtxFiles>(`/api/contexto/archivos${q}`, {
      timeoutMs: refresh ? 180000 : 30000,
    });
    if (!j.ok && j.error) throw new Error(j.error);
    setFiles(j);
    if (mdb) setDb(mdb);
    else if (j.current_database) setDb(j.current_database);

    const feedersList = j.feeders || [];
    const fids = new Set(feedersList.map((f) => String(f.feeder_id).toUpperCase()));
    let fid = (feederPick || j.current_feeder || feederFromStudy(j.current_study || "") || "").trim();
    // Al cambiar de BD: no conservar alimentador que no esté en el catálogo nuevo
    if (mdb) {
      if (fid && !fids.has(fid.toUpperCase())) fid = "";
      if (!feedersList.length) fid = "";
    } else if (fid && !fids.has(fid.toUpperCase())) {
      fid = "";
    }
    if (!fid && feedersList.length === 1) {
      fid = feedersList[0].feeder_id;
    }
    setFeederPick(fid);
    let resolvedStudy = "";
    if (fid) {
      const row = feedersList.find(
        (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
      );
      setFeeder(fid, row?.network_id || j.current_network || undefined);
      const resolved = resolveStudyForFeeder(fid, j);
      resolvedStudy = resolved || j.current_study || "";
      setStudy(resolvedStudy);
    } else if (!mdb) {
      const st = j.current_study || "";
      resolvedStudy = st;
      setStudy(st);
    } else {
      const eldPath =
        (j.studies || [])
          .map((s) => asPath(s))
          .find((p) => studyBasename(p).startsWith("eld.")) || "";
      resolvedStudy = eldPath || "";
      setStudy(resolvedStudy);
    }
    const dbPath = mdb || j.current_database || "";
    setContext({
      feeder: fid || "",
      network: j.current_network || "",
      studyPath: resolvedStudy || j.current_study || "",
      databaseMdb: dbPath,
    });
    if (mdb && feedersList.length) {
      setMsg(
        `BD ${mdb.split(/[/\\]/).pop()} · ${feedersList.length} alimentadores` +
          (j.networks_source ? ` (${j.networks_source})` : "")
      );
    }
    return j;
  }

  async function onPickDatabase(path: string) {
    setDb(path);
    setCymdistReady(false);
    setCymdistSyncNote("");
    if (!path) {
      setFeederPick("");
      setStudy("");
      clearMedicionFields();
      setFiles((prev) => ({ ...prev, feeders: [], n_feeders: 0 }));
      return;
    }
    setBusy(true);
    const prevStudy = study;
    const prevFeeder = feederPick;
    setFeederPick("");
    setStudy("");
    clearMedicionFields();
    setFiles((prev) => ({ ...prev, feeders: [], n_feeders: 0 }));
    const dbName = path.split(/[/\\]/).pop() || path;
    setMsg(`Cargando alimentadores y estudios de ${dbName}…`);
    try {
      await loadFiles({ database_mdb: path, refresh: false });
      const catalog = await loadFiles({ database_mdb: path, refresh: true });

      const fids = new Set(
        (catalog.feeders || []).map((f) => String(f.feeder_id).toUpperCase())
      );
      const studyPaths = new Set(
        (catalog.studies || []).map((s) => normPath(asPath(s)))
      );
      let fid = "";
      let st = "";
      if (prevStudy && studyPaths.has(normPath(prevStudy))) {
        st = prevStudy;
        fid = feederFromStudy(st) || "";
        if (fid && !fids.has(fid.toUpperCase())) {
          // estudio huérfano aún listable
        }
      }
      if (!fid && prevFeeder && fids.has(prevFeeder.toUpperCase())) {
        fid = prevFeeder;
        st = resolveStudyForFeeder(fid, catalog) || st;
      }
      if (fid || st) {
        await syncFeederStudyCabecera({
          feederId: fid,
          studyPath: st,
          fromStudy: Boolean(st && feederFromStudy(st)),
          extract: true,
        });
      } else {
        setMsg(
          `BD ${dbName} · ${(catalog.feeders || []).length} alimentadores · ${(catalog.studies || []).length} estudios · elija alimentador o estudio`
        );
      }
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
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

  function clearMedicionFields() {
    setMedidor("");
    setCodigoAlimentador("");
    setMedicionFile("");
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
    // Al cambiar de alimentador no reutilizar Excel anterior (evita datos de PA217 en IN112)
    let file =
      opts?.file !== undefined ? opts.file || "" : medicionFile || "";
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
          applyMapMedidor(mapCode);
        } else if (res.medidor) {
          setMedidor(res.medidor);
        }
        const vllMap = normalizeVll(res.Vll_kV);
        if (vllMap && !mapCode) {
          setVLl(vllMap);
          const vln = phaseFromVll(vllMap);
          setVaKv(vln);
          setVbKv(vln);
          setVcKv(vln);
        }
        if (res.suggested_file) {
          file = res.suggested_file;
          setMedicionFile(file);
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
          medicion_file: file,
          auto_find_file: autoFind,
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
      // Reafirmar medidor del código Excel
      if (mapCode) {
        applyMapMedidor(mapCode);
      } else if (j.medidor) {
        setMedidor(j.medidor);
      }
      if (j.medicion_file) setMedicionFile(j.medicion_file);
      if (!mapCode) {
        const vll = normalizeVll(j.Vll_kV);
        if (vll) {
          setVLl(vll);
          const vln = phaseFromVll(vll);
          setVaKv(vln);
          setVbKv(vln);
          setVcKv(vln);
        } else {
          throw new Error(`Sin Vll para ${fid} en medidoralimentador`);
        }
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
        if (keepFileOnError) {
          setPKw("");
          setQKvar("");
          setSKva("");
          setPAvg("");
          setFactorCarga("");
          setFecha("");
          setCabAdjNote("");
          if (chosenFile) setMedicionFile(chosenFile);
          if (mapCode) applyMapMedidor(mapCode);
        } else {
          clearMedicionFields();
          if (mapCode) {
            setCodigoAlimentador(mapCode);
            applyMapMedidor(mapCode);
          }
        }
        setMsg(String(e));
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

  // Catálogo de estudios: solo auto-elegir si no hay estudio o no pertenece a la familia
  useEffect(() => {
    const fid = (feederPick || "").trim();
    if (!fid || !(files.studies || []).length) return;
    if (study && studyBelongsToFeeder(study, fid)) return; // varios estudios OK
    const resolved = resolveStudyForFeeder(fid, files, study || undefined);
    if (!resolved) return;
    if (normPath(resolved) !== normPath(study)) setStudy(resolved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files.studies, files.feeders, feederPick]);

  function applyMapMedidor(fid: string) {
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
    const vll = normalizeVll(row.Vll_kV);
    if (vll) {
      setVLl(vll);
      const vln = phaseFromVll(vll);
      setVaKv(vln);
      setVbKv(vln);
      setVcKv(vln);
    }
    return row;
  }

  /** Código alimentador → medidor + buscar en hojas del Excel medicioncabecera */
  async function onPickCodigoAlimentador(code: string) {
    setCodigoAlimentador(code);
    if (!code) {
      setMedidor("");
      return;
    }
    // Limpiar magnitudes previas (evitar residuales PA217 al cambiar a AL107)
    setPKw("");
    setQKvar("");
    setSKva("");
    setPAvg("");
    setFactorCarga("");
    setFecha("");
    setCabAdjNote("");

    const local = applyMapMedidor(code);
    if (local?.medidor) setMedidor(String(local.medidor));

    let mid = local?.medidor || "";
    try {
      const res = await resolverMedicion(code);
      mid = String(res.medidor || mid).trim();
      if (mid) setMedidor(mid);
      setCodigoAlimentador(String(res.map_code || res.feeder_id || code));
      const vll = normalizeVll(res.Vll_kV);
      if (vll) {
        setVLl(vll);
        const vln = phaseFromVll(vll);
        setVaKv(vln);
        setVbKv(vln);
        setVcKv(vln);
      }
      if (res.suggested_file && !medicionFile) {
        setMedicionFile(res.suggested_file);
      }
      setMsg(
        `Código ${res.map_code || code} → medidor ${mid || "?"} · buscando en medicioncabecera…`
      );
    } catch (e) {
      if (!mid) {
        setMsg(String(e));
        return;
      }
    }

    // Extraer P/Q/S: busca el medidor en cada hoja del Excel (auto-cambia archivo si hace falta)
    skipCabeceraReload.current = true;
    await extraerMedicion({
      feeder: code,
      mapCode: code,
      file: medicionFile || "",
      autoFind: true,
      keepFileOnError: true,
    });
  }

  /**
   * Vínculo BD ↔ alimentador ↔ estudio(s) ↔ cabecera.
   * Un alimentador puede tener VARIOS estudios (PA217.zxst, PA217v2.xst…):
   * no se pisa el estudio elegido si pertenece a la misma familia.
   */
  async function syncFeederStudyCabecera(opts: {
    feederId?: string;
    studyPath?: string;
    extract?: boolean;
    fromStudy?: boolean;
    /** Conservar estudio actual si es de la familia del alimentador */
    keepStudyIfRelated?: boolean;
  }) {
    let fid = (opts.feederId || "").trim();
    let stPath = (opts.studyPath !== undefined ? opts.studyPath : study).trim();

    if (opts.fromStudy && stPath) {
      // Estudio manda el archivo; alimentador BD = red de la familia si existe
      fid = resolveFeederForStudy(stPath, files) || feederFromStudy(stPath);
    } else if (fid) {
      const related = listStudiesForFeeder(fid, files);
      const keep =
        opts.keepStudyIfRelated !== false &&
        stPath &&
        studyBelongsToFeeder(stPath, fid);
      if (keep) {
        // varios estudios: conservar el que ya eligió el usuario
        stPath = stPath;
      } else if (!stPath || !studyBelongsToFeeder(stPath, fid)) {
        stPath = resolveStudyForFeeder(fid, files, stPath) || "";
      }
      void related;
    }

    setFeederPick(fid);
    setStudy(stPath || "");

    const row = (files.feeders || []).find(
      (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
    );
    setContext({
      feeder: fid || "",
      network: row?.network_id || "",
      studyPath: stPath || "",
      databaseMdb: db || "",
    });
    if (fid) setFeeder(fid, row?.network_id);
    else setFeeder("", undefined);

    clearMedicionFields();
    const mapCode = mapCodeForFeeder(fid) || mapCodeForFeeder(feederFromStudy(stPath));
    if (mapCode) applyMapMedidor(mapCode);

    if (!fid && !stPath) {
      setMsg("Elija alimentador o estudio");
      return;
    }

    const nStudies = fid ? listStudiesForFeeder(fid, files).length : 0;

    skipCabeceraReload.current = true;
    try {
      if (fid) await loadCabecera(fid);
    } catch {
      /* sin sesión previa */
    }
    if (mapCode) applyMapMedidor(mapCode);

    if (opts.extract !== false && (fid || mapCode)) {
      await extraerMedicion({
        feeder: fid || mapCode,
        mapCode: mapCode || undefined,
        file: "",
        autoFind: true,
        keepFileOnError: true,
      });
    } else {
      setMsg(
        `Contexto · ${fid || "—"}` +
          (stPath ? ` · ${(stPath.split(/[/\\]/).pop() || "")}` : "") +
          (nStudies > 1 ? ` · ${nStudies} estudios disponibles` : "")
      );
    }
  }

  function onPickFeeder(fid: string, opts?: { extract?: boolean }) {
    setCymdistReady(false);
    setCymdistSyncNote("");
    void syncFeederStudyCabecera({
      feederId: fid,
      // Conservar estudio si ya es de esta familia (p.ej. PA217v2 con alim. PA217)
      studyPath: study,
      keepStudyIfRelated: true,
      fromStudy: false,
      extract: opts?.extract !== false,
    });
  }

  function onPickStudy(path: string) {
    setCymdistReady(false);
    setCymdistSyncNote("");
    const stem = feederFromStudy(path);
    if (!stem) {
      setStudy(path);
      setMsg("Estudio ELD · se mantiene el alimentador BD elegido · pulse 1.1 para conectar en CYMDIST");
      return;
    }
    void syncFeederStudyCabecera({
      feederId: resolveFeederForStudy(path, files) || stem,
      studyPath: path,
      fromStudy: true,
      extract: true,
    });
  }

  async function applyContext() {
    setBusy(true);
    setMsg("1.1 · Verificando BD en CYMDIST (existe → conectar; no existe → crear) y activando estudio…");
    setCymdistReady(false);
    setCymdistSyncNote("");
    try {
      const fid = (feederPick || feederFromStudy(study) || feeder || "").trim();
      const stPath = study || resolveStudyForFeeder(fid, files) || "";
      if (!db) {
        throw new Error("Seleccione la base de datos (.mdb) antes de 1.1");
      }
      if (!stPath) {
        throw new Error("Seleccione el estudio (.zxst/.xst) antes de 1.1");
      }
      if (stPath !== study) setStudy(stPath);

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
          database_mdb: db || null,
          study_path: stPath || null,
          feeder: fid || null,
        }),
      });
      if (!j.ok) throw new Error(j.error || "Error contexto");

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
        setFeeder(resolved, j.network_id);
      }
      // Conservar elección UI (.xst); CYMDIST abre study_path (.zxst) en backend
      const uiStudy = j.ui_study_path || stPath || j.study_path || "";
      if (uiStudy) setStudy(uiStudy);
      setContext({
        feeder: resolved || "",
        network: j.network_id || "",
        studyPath: uiStudy || j.study_path || "",
        databaseMdb: db || j.database_mdb || "",
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
        fromStudy: false,
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
      const fid = (feederPick || feederFromStudy(study) || feeder || "").trim();
      if (fid) setFeeder(fid);
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
  const studiesForFeeder = feederPick
    ? listStudiesForFeeder(feederPick, files)
    : [];
  const studyOptions = (() => {
    const relatedSet = new Set(studiesForFeeder.map((p) => normPath(p)));
    const idU = (feederPick || "").toUpperCase();
    const fam = feederFamily(feederPick);
    const score = (path: string) => {
      if (relatedSet.has(normPath(path))) {
        const stem = studyStem(path);
        if (stem === idU) return 0;
        if (stem === fam) return 1;
        return 2;
      }
      if (studyStem(path) === "ELD") return 90;
      return 50;
    };
    return studies
      .map((s) => {
        const p = asPath(s);
        // Solo el nombre del estudio (sin “· de PA217”)
        return {
          value: p,
          label: asLabel(s),
          searchText: `${p} ${asLabel(s)} ${fam}`,
          _s: score(p),
        };
      })
      .sort((a, b) => a._s - b._s || a.label.localeCompare(b.label))
      .map(({ value, label, searchText }) => ({ value, label, searchText }));
  })();
  const medicionOptions = medicionFiles.map((f) => ({
    value: f.name,
    label: f.size_mb != null ? `${f.name} (${f.size_mb} MB)` : f.name,
    searchText: f.name,
  }));

  return (
    <section className="panel">
      <h2>1 · Contexto + cabecera</h2>
      <p className="muted">
        1) Elija <b>base .mdb</b>, <b>alimentador</b> y <b>estudio</b>. 2) Pulse{" "}
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
            {studiesForFeeder.length > 1
              ? ` · ${studiesForFeeder.length} opciones`
              : ""}
          </label>
          <SearchableSelect
            value={study}
            options={studyOptions}
            disabled={busy}
            onChange={(v) => onPickStudy(v)}
            placeholder={
              studiesForFeeder.length > 1
                ? "Varios estudios — elija uno…"
                : "Buscar estudio…"
            }
            emptyLabel="—"
          />
          <p className="muted" style={{ marginTop: 4, fontSize: 12 }}>
            {(() => {
              const name = (study || "").split(/[/\\]/).pop() || "";
              const viaEld = studyBasename(study).startsWith("eld.");
              const n = studiesForFeeder.length;
              if (!study) {
                return n > 1
                  ? `${n} estudios para este alimentador — elija uno.`
                  : "Elija el estudio; luego 1.1 para conectar en CYMDIST.";
              }
              if (viaEld) {
                return `${name} (ELD) · pulse 1.1 para activar en CYMDIST.`;
              }
              return `${name}` +
                (db ? ` · BD ${(db.split(/[/\\]/).pop() || "")}` : "") +
                " · pulse 1.1 antes de cargar cabecera.";
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
      <div className="actions">
        <button
          type="button"
          className="secondary"
          disabled={busy || !db || !study}
          onClick={applyContext}
          title="Verifica si la BD existe en CYMDIST; si no, la crea; luego activa el estudio"
        >
          1.1 · Verificar y conectar en CYMDIST
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={() =>
            Promise.all([
              loadFiles({ database_mdb: db || undefined, refresh: true }),
              loadMedicionFiles(),
            ])
              .then(([catalog]) => {
                const fid = feederPick || catalog.current_feeder || "";
                return loadCabecera(fid || undefined);
              })
              .catch((e) => setMsg(String(e)))
          }
        >
          Actualizar listas
        </button>
      </div>

      <h3>Medición de cabecera</h3>
      <p className="muted">
        Primero complete <b>1.1</b> (BD + estudio activos en CYMDIST). Luego elija{" "}
        <b>código alimentador</b> para rellenar medidor y datos del Excel{" "}
        <code>medicioncabecera</code>. Pulse <b>1.2</b> para escribir en la fuente.
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
          <label>Excel medicioncabecera</label>
          <SearchableSelect
            value={medicionFile}
            options={medicionOptions}
            disabled={busy}
            placeholder="Buscar SISTEMA…"
            emptyLabel="— auto / elegir —"
            onChange={(v) => {
              setMedicionFile(v);
              const code = (codigoAlimentador || feederPick || "").trim();
              if (code && v) {
                extraerMedicion({
                  feeder: code,
                  mapCode: codigoAlimentador || undefined,
                  file: v,
                  autoFind: false,
                  keepFileOnError: true,
                });
              }
            }}
          />
        </div>
        <div className="actions" style={{ alignItems: "end", margin: 0 }}>
          <button
            type="button"
            className="ghost"
            disabled={busy || !(codigoAlimentador || feederPick)}
            onClick={() =>
              extraerMedicion({
                feeder: codigoAlimentador || feederPick,
                mapCode: codigoAlimentador || undefined,
                autoFind: true,
              })
            }
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
