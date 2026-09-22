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
  error?: string;
};

type MedicionFile = { name: string; path: string; size_mb?: number };

type CabeceraSess = {
  ok?: boolean;
  feeder_id?: string;
  network_id?: string;
  P_kW?: number | null;
  Q_kvar?: number | null;
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
  const stem = base.replace(/\.(zxst|zsxst|sxst)$/i, "");
  if (!stem || stem.toUpperCase() === "ELD") return "";
  return stem;
}

export function Step1Contexto() {
  const { feeder, network, setFeeder } = useFeeder();
  const [files, setFiles] = useState<CtxFiles>({});
  const [db, setDb] = useState("");
  const [study, setStudy] = useState("");
  const [feederPick, setFeederPick] = useState("");
  const [medicionFiles, setMedicionFiles] = useState<MedicionFile[]>([]);
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
    const j = await api<{ ok?: boolean; files?: MedicionFile[]; error?: string }>(
      "/api/cabecera/medicion/archivos"
    );
    if (!j.ok && j.error) throw new Error(j.error);
    setMedicionFiles(j.files || []);
    return j.files || [];
  }

  async function loadFiles() {
    const j = await api<CtxFiles>("/api/contexto/archivos");
    setFiles(j);
    setDb(j.current_database || "");
    const st = j.current_study || "";
    setStudy(st);
    const fid = j.current_feeder || feederFromStudy(st) || "";
    setFeederPick(fid);
    if (fid) setFeeder(fid, j.current_network || undefined);
    return fid;
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
  }

  async function extraerMedicion(opts?: {
    feeder?: string;
    file?: string;
    silent?: boolean;
    autoFind?: boolean;
  }) {
    const fid = (opts?.feeder || feederPick || feeder || "").trim();
    // Al cambiar de alimentador no reutilizar Excel anterior (evita datos de PA217 en IN112)
    let file =
      opts?.file !== undefined ? opts.file || "" : medicionFile || "";
    const autoFind = opts?.autoFind !== false;
    if (!fid) {
      if (!opts?.silent) setMsg("Elija alimentador (BD) para extracción de medición");
      return null;
    }
    const seq = ++extractSeq.current;
    setBusy(true);
    if (!opts?.silent) {
      setMsg(
        file
          ? `Extrayendo medición · ${fid} · ${file}…`
          : `Extrayendo medición · ${fid} (auto-archivo)…`
      );
    }
    try {
      if (!file && autoFind) {
        const res = await resolverMedicion(fid);
        if (seq !== extractSeq.current) return null;
        if (res.medidor) setMedidor(res.medidor);
        const vllMap = normalizeVll(res.Vll_kV);
        if (vllMap) {
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
      if (j.medidor) setMedidor(j.medidor);
      if (j.medicion_file) setMedicionFile(j.medicion_file);
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
      const warn =
        j.warnings && j.warnings.length
          ? ` · aviso: ${j.warnings.slice(0, 2).join("; ")}`
          : "";
      setMsg(
        (j.msg ||
          `OK · ${fid} · medidor ${j.medidor || "?"} · Pmáx=${j.P_kW} · Q=${j.Q_kvar} · Vll=${vll}`) +
          warn
      );
      return j;
    } catch (e) {
      if (seq === extractSeq.current) {
        // No dejar valores del alimentador anterior
        clearMedicionFields();
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
        const fid = await loadFiles();
        await loadMedicionFiles();
        await loadCabecera(fid || undefined);
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

  function onPickFeeder(fid: string, opts?: { extract?: boolean }) {
    setFeederPick(fid);
    const row = (files.feeders || []).find(
      (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
    );
    if (row?.study_path && row.has_study) {
      setStudy(row.study_path);
    } else if (fid) {
      // Sin .zxst propio válido → ELD (todas las redes de la BD)
      const eld = (files.studies || []).find((s) => {
        const n = asLabel(s).toUpperCase();
        return n === "ELD.ZXST" || n.startsWith("ELD.");
      });
      if (eld) setStudy(asPath(eld));
    }
    if (fid) setFeeder(fid, row?.network_id);
    // Limpiar siempre al cambiar: evita residuales del alimentador anterior
    clearMedicionFields();
    if (!fid) return;
    if (opts?.extract !== false) {
      skipCabeceraReload.current = true;
      window.setTimeout(() => {
        // file vacío → auto-elige Excel del sistema correcto (no reusa el anterior)
        extraerMedicion({ feeder: fid, file: "", autoFind: true });
      }, 0);
    }
  }

  function onPickStudy(path: string) {
    setStudy(path);
    const fid = feederFromStudy(path);
    if (fid) {
      onPickFeeder(fid, { extract: true });
    }
  }

  async function applyContext() {
    setBusy(true);
    setMsg("Aplicando BD + alimentador…");
    try {
      const fid = (feederPick || feederFromStudy(study) || feeder || "").trim();
      const j = await api<{
        ok?: boolean;
        error?: string;
        feeder_id?: string;
        network_id?: string;
        study_path?: string;
        msg?: string;
      }>("/api/contexto/aplicar", {
        method: "POST",
        body: JSON.stringify({
          database_mdb: db || null,
          study_path: study || null,
          feeder: fid || null,
        }),
      });
      if (!j.ok) throw new Error(j.error || "Error contexto");
      const resolved = j.feeder_id || fid;
      if (resolved) {
        setFeederPick(resolved);
        setFeeder(resolved, j.network_id);
      }
      if (j.study_path) setStudy(j.study_path);
      const head = await loadCabecera(resolved || undefined);
      const hasP = head.P_kW != null && String(head.P_kW) !== "";
      setMsg(
        (j.msg || `OK · ${resolved || "?"} · red ${j.network_id || "—"}`) +
          (hasP
            ? ` · cabecera P=${head.P_kW} Q=${head.Q_kvar}`
            : " · cabecera sin medición previa")
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveHead(previewOnly = false) {
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
  const feederOptions = feeders.map((f) => ({
    value: f.feeder_id,
    label:
      (f.label || `${f.feeder_id} · ${f.network_id || ""}`) +
      (f.has_study ? "" : " (via ELD)"),
    searchText: `${f.feeder_id} ${f.network_id || ""} ${f.label || ""}`,
  }));
  const studyOptions = studies.map((s) => {
    const p = asPath(s);
    return { value: p, label: asLabel(s), searchText: p };
  });
  const medicionOptions = medicionFiles.map((f) => ({
    value: f.name,
    label: f.size_mb != null ? `${f.name} (${f.size_mb} MB)` : f.name,
    searchText: f.name,
  }));

  return (
    <section className="panel">
      <h2>1 · Contexto + cabecera</h2>
      <p className="muted">
        Ningún alimentador está fijo: elija <b>cualquier</b> alimentador de la BD (~{files.n_feeders || "96"})
        y su estudio <code>.zxst</code>. Escriba iniciales (p.ej. <b>PA</b>) para filtrar.
        Toda corrección/escritura usa ese par: estudio + BD (p.ej. <b>20260919</b>).
      </p>

      <div className="grid">
        <div>
          <label>Base de datos (.mdb)</label>
          <SearchableSelect
            value={db}
            options={dbOptions}
            onChange={setDb}
            placeholder="Buscar .mdb…"
            emptyLabel="—"
          />
        </div>
        <div>
          <label>Alimentador (BD)</label>
          <SearchableSelect
            value={feederPick}
            options={feederOptions}
            disabled={busy}
            placeholder="Escriba PA, IN, NA…"
            emptyLabel="— elegir —"
            onChange={(v) => onPickFeeder(v, { extract: true })}
          />
        </div>
        <div>
          <label>Estudio (.zxst)</label>
          <SearchableSelect
            value={study}
            options={studyOptions}
            onChange={(v) => onPickStudy(v)}
            placeholder="Buscar .zxst…"
            emptyLabel="—"
          />
        </div>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Activo: <b>{feederPick || feeder || "—"}</b>
        {" · "}red <b>{network || "—"}</b>
        {" · "}Pulse <b>1.1 Aplicar</b> antes de guardar cabecera.
      </p>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy} onClick={applyContext}>
          1.1 · Aplicar BD + alimentador
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={() =>
            Promise.all([loadFiles(), loadMedicionFiles()])
              .then(([fid]) => loadCabecera(fid || undefined))
              .catch((e) => setMsg(String(e)))
          }
        >
          Actualizar listas
        </button>
      </div>

      <h3>Medición de cabecera</h3>
      <p className="muted">
        Usa el alimentador elegido arriba. Elija Excel de <code>medicioncabecera</code> (o deje
        auto): se resuelve medidor + <b>Vll</b> desde <code>medidoralimentador</code> y se
        completan P máx, Q, kVA, fecha, P promedio y factor de carga. Pulse <b>1.2</b> para
        escribir en CYMDIST.
      </p>

      <div className="grid">
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
              if (feederPick && v) {
                extraerMedicion({ feeder: feederPick, file: v, autoFind: true });
              }
            }}
          />
        </div>
        <div>
          <label>Medidor (mapeo)</label>
          <input value={medidor} readOnly placeholder="auto desde medidoralimentador" />
        </div>
        <div>
          <label>Vll (kV) — medidoralimentador</label>
          <input
            value={fmtVllLabel(vLl)}
            readOnly
            placeholder="auto al extraer"
            title="Nivel de tensión del alimentador en medidoralimentador.xlsx"
          />
        </div>
        <div className="actions" style={{ alignItems: "end", margin: 0 }}>
          <button
            type="button"
            className="ghost"
            disabled={busy || !feederPick}
            onClick={() => extraerMedicion({ autoFind: true })}
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
        <button type="button" disabled={busy} onClick={() => saveHead(false)}>
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
