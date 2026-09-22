import { useEffect, useState } from "react";
import { api } from "../api/client";
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

type CabeceraSess = {
  ok?: boolean;
  feeder_id?: string;
  network_id?: string;
  P_kW?: number | null;
  Q_kvar?: number | null;
  Vll_kV?: number | null;
  Va_kV?: number | null;
  Vb_kV?: number | null;
  Vc_kV?: number | null;
  fecha_medicion?: string;
  status?: string;
  error?: string;
};

const VLL_OPTIONS = [
  { value: "10", label: "10 kV" },
  { value: "22.9", label: "22.9 kV" },
] as const;

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
  // Aceptar 22.9 / 22.90 / 10 / 10.0
  if (Math.abs(n - 22.9) < 0.05) return "22.9";
  if (Math.abs(n - 10) < 0.05) return "10";
  return String(n);
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
  const [pKw, setPKw] = useState("");
  const [qKvar, setQKvar] = useState("");
  const [vLl, setVLl] = useState("");
  const [vaKv, setVaKv] = useState("");
  const [vbKv, setVbKv] = useState("");
  const [vcKv, setVcKv] = useState("");
  const [fecha, setFecha] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  function applyCabeceraToForm(j: CabeceraSess) {
    setPKw(fmtNum(j.P_kW));
    setQKvar(fmtNum(j.Q_kvar));
    const vll = normalizeVll(j.Vll_kV);
    setVLl(vll);
    setFecha(String(j.fecha_medicion || ""));
    const vlnDefault = vll ? phaseFromVll(vll) : "";
    setVaKv(fmtNum(j.Va_kV) || vlnDefault);
    setVbKv(fmtNum(j.Vb_kV) || vlnDefault);
    setVcKv(fmtNum(j.Vc_kV) || vlnDefault);
  }

  async function loadCabecera(fid?: string) {
    const q = fid ? `?feeder=${encodeURIComponent(fid)}` : "";
    const j = await api<CabeceraSess>(`/api/cabecera${q}`);
    if (!j.ok && j.error) throw new Error(j.error);
    applyCabeceraToForm(j);
    if (j.feeder_id) setFeeder(j.feeder_id, j.network_id);
    return j;
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

  useEffect(() => {
    (async () => {
      try {
        const fid = await loadFiles();
        await loadCabecera(fid || undefined);
      } catch (e) {
        setMsg(String(e));
      }
    })();
  }, []);

  // Al cambiar alimentador activo: rellenar con la última sesión de ESE radial
  useEffect(() => {
    const fid = (feederPick || feeder || "").trim();
    if (!fid) return;
    loadCabecera(fid).catch((e) => setMsg(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feederPick]);

  function onPickVll(value: string) {
    setVLl(value);
    if (!value) {
      setVaKv("");
      setVbKv("");
      setVcKv("");
      return;
    }
    const vln = phaseFromVll(value);
    setVaKv(vln);
    setVbKv(vln);
    setVcKv(vln);
  }

  function onPickFeeder(fid: string) {
    setFeederPick(fid);
    const row = (files.feeders || []).find(
      (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
    );
    if (row?.study_path) setStudy(row.study_path);
    else if (fid) {
      const eld = (files.studies || []).find((s) => {
        const n = asLabel(s).toUpperCase();
        return n === "ELD.ZXST" || n.startsWith("ELD.");
      });
      if (eld) setStudy(asPath(eld));
    }
    if (fid) setFeeder(fid, row?.network_id);
  }

  function onPickStudy(path: string) {
    setStudy(path);
    const fid = feederFromStudy(path);
    if (fid) {
      setFeederPick(fid);
      const row = (files.feeders || []).find(
        (f) => String(f.feeder_id).toUpperCase() === fid.toUpperCase()
      );
      setFeeder(fid, row?.network_id);
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
        throw new Error("Seleccione tensión de línea Vll (10 kV o 22.9 kV)");
      }
      const body = {
        mode: "KW_KVAR",
        P_kW: pKw === "" ? null : Number(pKw),
        Q_kvar: qKvar === "" ? null : Number(qKvar),
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
          Vll_kV: j.Vll_kV ?? body.Vll_kV,
          Va_kV: j.Va_kV ?? body.Va_kV,
          Vb_kV: j.Vb_kV ?? body.Vb_kV,
          Vc_kV: j.Vc_kV ?? body.Vc_kV,
          fecha_medicion: j.fecha_medicion ?? fecha,
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

  return (
    <section className="panel">
      <h2>1 · Contexto + cabecera</h2>
      <p className="muted">
        Ningún alimentador está fijo: elija <b>cualquier</b> alimentador de la BD (~{files.n_feeders || "96"})
        y su estudio <code>.zxst</code>. Toda corrección/escritura usa ese par:
        estudio del alimentador + BD seleccionada (p.ej. <b>20260919</b>).
      </p>

      <div className="grid">
        <div>
          <label>Base de datos (.mdb)</label>
          <select value={db} onChange={(e) => setDb(e.target.value)}>
            <option value="">—</option>
            {dbs.map((d) => {
              const p = asPath(d);
              return (
                <option key={p} value={p}>
                  {asLabel(d)}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label>Alimentador (BD — cualquiera)</label>
          <select value={feederPick} onChange={(e) => onPickFeeder(e.target.value)}>
            <option value="">— elegir —</option>
            {feeders.map((f) => (
              <option key={f.feeder_id} value={f.feeder_id}>
                {f.label || `${f.feeder_id} · ${f.network_id || ""}`}
                {f.has_study ? "" : " (via ELD)"}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>Estudio (.zxst)</label>
          <select value={study} onChange={(e) => onPickStudy(e.target.value)}>
            <option value="">—</option>
            {studies.map((s) => {
              const p = asPath(s);
              return (
                <option key={p} value={p}>
                  {asLabel(s)}
                </option>
              );
            })}
          </select>
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
            loadFiles()
              .then((fid) => loadCabecera(fid || undefined))
              .catch((e) => setMsg(String(e)))
          }
        >
          Actualizar listas
        </button>
      </div>

      <h3>Medición de cabecera</h3>
      <p className="muted">
        Se muestran los <b>últimos valores guardados</b> de este alimentador (no se vacían al
        recargar ni al Actualizar). Solo <b>Restablecer</b> limpia la cabecera.
        Al guardar se escriben en la fuente/equivalente (OperatingVoltage A/B/C + SetDemand).
      </p>
      <div className="grid">
        <div>
          <label>P (kW)</label>
          <input value={pKw} onChange={(e) => setPKw(e.target.value)} />
        </div>
        <div>
          <label>Q (kvar)</label>
          <input value={qKvar} onChange={(e) => setQKvar(e.target.value)} />
        </div>
        <div>
          <label>Vll (kV)</label>
          <select value={vLl} onChange={(e) => onPickVll(e.target.value)}>
            <option value="">— elegir —</option>
            {VLL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>Fecha medición</label>
          <input value={fecha} onChange={(e) => setFecha(e.target.value)} />
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
