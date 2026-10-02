import { useEffect, useRef, useState } from "react";
import { api, getActiveFeeder, runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

function nodeIdOf(n: Json): string {
  return String(n.NodeID || n.node_id || n.id || "").trim();
}

function sectionPreview(n: Json): string {
  const direct = String(n.SectionID || n.section_id || "").trim();
  if (direct) return direct;
  const secs = n.sections;
  if (Array.isArray(secs) && secs.length) return String(secs[0] || "");
  return "";
}

type BatchRow = {
  row?: number;
  Accion?: string;
  NodeID?: string;
  Nombre?: string;
  SectionID?: string;
  Modo?: string;
  P_kW?: string | number | null;
  Q_kvar?: string | number | null;
  cosfi?: string | number | null;
  Cliente?: string;
  Notas?: string;
  ok?: boolean;
  errors?: string[];
  Estado?: string;
  LoadID?: string;
  error?: string;
};

type ConnectedRow = {
  LoadID?: string;
  Nombre?: string;
  NodeID?: string;
  SectionID?: string;
  P_kW?: string | number;
  Q_kvar?: string | number;
  cosfi?: string | number;
  Estado?: string;
  verificado?: boolean;
  existe?: boolean;
  conectado?: boolean;
  P_kW_actual?: number | null;
  detalle?: string;
};

async function downloadTemplate(fmt: "xlsx" | "csv") {
  const h = new Headers();
  const feeder = getActiveFeeder();
  if (feeder) h.set("X-Feeder", feeder);
  const r = await fetch(`/api/cargas/plantilla?fmt=${fmt}`, { headers: h });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text.slice(0, 200) || `HTTP ${r.status}`);
  }
  const blob = await r.blob();
  const cd = r.headers.get("content-disposition") || "";
  const m = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(cd);
  const fname = m ? m[1].replace(/['"]/g, "") : `spotload_lote.${fmt}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fname;
  a.click();
  URL.revokeObjectURL(url);
}

export function Step4SpotLoad() {
  const { feeder } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [q, setQ] = useState("");
  const [nodes, setNodes] = useState<Json[]>([]);
  const [nodeId, setNodeId] = useState("");
  const [sectionId, setSectionId] = useState("");
  const [loadName, setLoadName] = useState("");
  const [candidates, setCandidates] = useState<string[]>([]);
  const [mode, setMode] = useState("KW_COSFI");
  const [pKw, setPKw] = useState("");
  const [qKvar, setQKvar] = useState("");
  const [cosfi, setCosfi] = useState("0.95");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const [batchFileName, setBatchFileName] = useState("");
  const [batchRows, setBatchRows] = useState<BatchRow[]>([]);
  const [batchMsg, setBatchMsg] = useState("");

  // 4.3 · una sola carga (mismos campos que 4.2)
  const [uQ, setUQ] = useState("");
  const [uNodes, setUNodes] = useState<Json[]>([]);
  const [uNodeId, setUNodeId] = useState("");
  const [uSectionId, setUSectionId] = useState("");
  const [uLoadName, setULoadName] = useState("");
  const [uCandidates, setUCandidates] = useState<string[]>([]);
  const [uMode, setUMode] = useState("KW_COSFI");
  const [uPKw, setUPKw] = useState("");
  const [uQKvar, setUQKvar] = useState("");
  const [uCosfi, setUCosfi] = useState("0.95");
  const [uMsg, setUMsg] = useState("");

  const [connected, setConnected] = useState<ConnectedRow[]>([]);
  const [connectedMsg, setConnectedMsg] = useState("");
  const [mapUrl, setMapUrl] = useState("");

  async function loadConnected() {
    try {
      const j = await api<{ ok?: boolean; error?: string; rows?: ConnectedRow[]; msg?: string; n?: number }>(
        "/api/cargas/conectadas"
      );
      if (!j.ok) throw new Error(j.error || "Error");
      setConnected(j.rows || []);
      setConnectedMsg(j.msg || `${j.n ?? 0} carga(s) guardadas`);
    } catch (e) {
      setConnected([]);
      setConnectedMsg(String(e));
    }
  }

  async function verifyConnectedLive() {
    if (!hasCtx) {
      setConnectedMsg("Aplique 1.1 antes de verificar en vivo contra CYMDIST");
      return;
    }
    setConnectedMsg("Verificando en vivo contra CYMDIST (solo lectura)…");
    try {
      const j = await runJob("cargas_verificar_cymdist", {}, (job) => {
        if (job.message) setConnectedMsg(String(job.message));
      });
      const rows = (j.rows as Json[] | undefined) || [];
      setConnected(rows as unknown as ConnectedRow[]);
      setConnectedMsg(
        `${j.all_verified ? "OK" : "REVISAR"} · ${String(j.msg || "")}`
      );
    } catch (e) {
      setConnectedMsg(String(e));
    }
  }

  useEffect(() => {
    void loadConnected();
  }, [feeder]);

  async function resolveNode(nid: string, nameHint?: string) {
    if (!hasCtx) {
      setMsg("Aplique 1.1 al contexto actual antes de buscar o resolver nodos");
      return;
    }
    const id = String(nid || "").trim();
    if (!id) return;
    setNodeId(id);
    const name = String(nameHint || loadName || id).trim();
    if (!loadName.trim()) setLoadName(name);
    setMsg(`Resolviendo nodo ${id}…`);
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        SectionID?: string;
        section_id?: string;
        section_candidates?: string[];
        LoadID?: string;
        n_sections?: number;
      }>("/api/nodos/resolver", {
        method: "POST",
        body: JSON.stringify({ node_id: id, load_name: name }),
      });
      if (!j.ok) throw new Error(j.error || "No se resolvió sección");
      const sec = String(j.SectionID || j.section_id || "");
      setSectionId(sec);
      setCandidates((j.section_candidates || []).map(String));
      setMsg(
        `Nodo ${id} · SectionID ${sec}` +
          (j.n_sections ? ` · ${j.n_sections} tramos` : "") +
          (j.LoadID ? ` · LoadID ${j.LoadID}` : "")
      );
    } catch (e) {
      setSectionId("");
      setCandidates([]);
      setMsg(String(e));
    }
  }

  async function search() {
    if (!hasCtx) {
      setMsg("Aplique 1.1 al contexto actual antes de buscar nodos");
      return;
    }
    const query = q.trim();
    if (!query) {
      setMsg("Indique un ID de nodo (parcial o exacto).");
      return;
    }
    setBusy(true);
    setMsg(`Buscando «${query}»…`);
    try {
      const j = await api<{ ok?: boolean; error?: string; nodes?: Json[]; results?: Json[] }>(
        `/api/nodos/buscar?q=${encodeURIComponent(query)}&limit=80`
      );
      if (j.ok === false) throw new Error(j.error || "Error búsqueda");
      const list = j.nodes || j.results || [];
      setNodes(list);

      if (!list.length) {
        setNodeId("");
        setSectionId("");
        setCandidates([]);
        setMsg(`Sin nodos para «${query}». Verifique el ID en el estudio activo.`);
        return;
      }

      const exact = list.find((n) => nodeIdOf(n).toLowerCase() === query.toLowerCase());
      const pick = exact || (list.length === 1 ? list[0] : null);
      if (pick) {
        const nid = nodeIdOf(pick);
        setMsg(`1 coincidencia · resolviendo ${nid}…`);
        await resolveNode(nid, loadName.trim() || nid);
      } else {
        setMsg(`${list.length} nodos · haga clic en una fila para cargar SectionID.`);
      }
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    if (!hasCtx) {
      setMsg("Aplique 1.1 al contexto actual antes de conectar SpotLoads");
      return;
    }
    if (!nodeId.trim()) {
      setMsg("Seleccione un nodo (Buscar → clic en fila, o coincidencia única).");
      return;
    }
    if (!loadName.trim()) {
      setMsg("Indique el nombre de la carga (DeviceNumber).");
      return;
    }
    if (!sectionId.trim()) {
      setMsg("Falta SectionID. Pulse Buscar y seleccione el nodo otra vez.");
      return;
    }
    setBusy(true);
    setMsg("Conectando SpotLoad y guardando en estudio…");
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        result?: Json & {
          location_map_url?: string;
          LoadID?: string;
          saved_for_simulations?: boolean;
        };
      }>("/api/cargas/nueva", {
        method: "POST",
        body: JSON.stringify({
          node_id: nodeId,
          load_name: loadName,
          mode,
          P_kW: pKw === "" ? null : Number(pKw),
          Q_kvar: qKvar === "" ? null : Number(qKvar),
          cosfi: cosfi === "" ? null : Number(cosfi),
        }),
        timeoutMs: 300000,
      });
      if (!j.ok) throw new Error(j.error || "Error conectar");
      const res = j.result || {};
      const url = String(res.location_map_url || "");
      if (url) setMapUrl(url);
      setMsg(
        `OK · ${res.LoadID || loadName} guardada en el estudio` +
          (url ? " · figura de ubicación generada" : "") +
          " · disponible para §5 (proyectado)."
      );
      void loadConnected();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onPickFile(file: File | null) {
    if (!file) return;
    setBatchFileName(file.name);
    setBusy(true);
    setBatchMsg(`Leyendo ${file.name}…`);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const j = await api<{
        ok?: boolean;
        error?: string;
        rows?: BatchRow[];
        n?: number;
        n_ok?: number;
        n_error?: number;
      }>("/api/cargas/lote/preview", {
        method: "POST",
        body: fd,
        timeoutMs: 120000,
      });
      if (!j.ok) throw new Error(j.error || "Error preview");
      setBatchRows(j.rows || []);
      setBatchMsg(
        `Vista previa · ${j.n_ok ?? 0} válidas · ${j.n_error ?? 0} con error · total ${j.n ?? 0}`
      );
    } catch (e) {
      setBatchRows([]);
      setBatchMsg(String(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function connectBatch(rows?: BatchRow[]) {
    if (!hasCtx) {
      setBatchMsg("Aplique 1.1 al contexto actual antes de conectar SpotLoads");
      return;
    }
    const payload = rows || batchRows;
    if (!payload.length) {
      setBatchMsg("Cargue primero un CSV/Excel o añada una fila desde el formulario 4.3.");
      return;
    }
    const nOk = payload.filter((r) => r.ok !== false).length;
    if (!nOk) {
      setBatchMsg("No hay filas válidas para conectar.");
      return;
    }
    if (
      !confirm(
        `Conectar en bloque ${nOk} SpotLoad en ${feeder || "alimentador activo"}?\n\nQuedan guardadas para §5. CYMDIST se abre una vez al final.`
      )
    ) {
      return;
    }
    setBusy(true);
    setBatchMsg(`Conectando ${nOk} cargas…`);
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        msg?: string;
        n_ok?: number;
        n_error?: number;
        n_skipped?: number;
        results?: BatchRow[];
        location_map_url?: string;
      }>("/api/cargas/lote/conectar", {
        method: "POST",
        body: JSON.stringify({ rows: payload }),
        timeoutMs: 600000,
      });
      if (j.ok === false && !j.n_ok) throw new Error(j.error || "Error lote");
      if (j.location_map_url) setMapUrl(String(j.location_map_url));
      setBatchMsg(
        (j.msg || `OK ${j.n_ok ?? 0}`) +
          " · guardadas en estudio" +
          (j.location_map_url ? " · figura ubicación OK" : "")
      );
      if (j.results?.length) {
        setBatchRows(
          j.results.map((r, i) => ({
            ...r,
            row: r.row ?? i + 1,
            ok: r.ok !== false && String(r.Estado || "").toUpperCase().indexOf("ERR") < 0,
            errors: r.error ? [String(r.error)] : r.errors,
          }))
        );
      }
      void loadConnected();
    } catch (e) {
      setBatchMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resolveUNode(nid: string, nameHint?: string) {
    if (!hasCtx) {
      setUMsg("Aplique 1.1 al contexto actual antes de buscar o resolver nodos");
      return;
    }
    const id = String(nid || "").trim();
    if (!id) return;
    setUNodeId(id);
    const name = String(nameHint || uLoadName || id).trim();
    if (!uLoadName.trim()) setULoadName(name);
    setUMsg(`Resolviendo nodo ${id}…`);
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        SectionID?: string;
        section_id?: string;
        section_candidates?: string[];
        LoadID?: string;
        n_sections?: number;
      }>("/api/nodos/resolver", {
        method: "POST",
        body: JSON.stringify({ node_id: id, load_name: name }),
      });
      if (!j.ok) throw new Error(j.error || "No se resolvió sección");
      const sec = String(j.SectionID || j.section_id || "");
      setUSectionId(sec);
      setUCandidates((j.section_candidates || []).map(String));
      setUMsg(
        `Nodo ${id} · SectionID ${sec}` +
          (j.n_sections ? ` · ${j.n_sections} tramos` : "") +
          (j.LoadID ? ` · LoadID ${j.LoadID}` : "")
      );
    } catch (e) {
      setUSectionId("");
      setUCandidates([]);
      setUMsg(String(e));
    }
  }

  async function searchU() {
    if (!hasCtx) {
      setUMsg("Aplique 1.1 al contexto actual antes de buscar nodos");
      return;
    }
    const query = uQ.trim();
    if (!query) {
      setUMsg("Indique un ID de nodo (parcial o exacto).");
      return;
    }
    setBusy(true);
    setUMsg(`Buscando «${query}»…`);
    try {
      const j = await api<{ ok?: boolean; error?: string; nodes?: Json[]; results?: Json[] }>(
        `/api/nodos/buscar?q=${encodeURIComponent(query)}&limit=80`
      );
      if (j.ok === false) throw new Error(j.error || "Error búsqueda");
      const list = j.nodes || j.results || [];
      setUNodes(list);
      if (!list.length) {
        setUNodeId("");
        setUSectionId("");
        setUCandidates([]);
        setUMsg(`Sin nodos para «${query}».`);
        return;
      }
      const exact = list.find((n) => nodeIdOf(n).toLowerCase() === query.toLowerCase());
      const pick = exact || (list.length === 1 ? list[0] : null);
      if (pick) {
        const nid = nodeIdOf(pick);
        setUMsg(`1 coincidencia · resolviendo ${nid}…`);
        await resolveUNode(nid, uLoadName.trim() || nid);
      } else {
        setUMsg(`${list.length} nodos · haga clic en una fila.`);
      }
    } catch (e) {
      setUMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  function buildURow(accion: "NUEVA" | "ACTUALIZAR"): BatchRow | null {
    if (!uNodeId.trim() || !uLoadName.trim()) {
      setUMsg("Complete NodeID y Nombre (igual que 4.2).");
      return null;
    }
    if (uPKw === "") {
      setUMsg("Indique P_kW.");
      return null;
    }
    if (uMode === "KW_KVAR" && uQKvar === "") {
      setUMsg("Modo KW_KVAR: falta Q_kvar.");
      return null;
    }
    return {
      row: (batchRows.length || 0) + 1,
      Accion: accion,
      NodeID: uNodeId.trim(),
      Nombre: uLoadName.trim(),
      SectionID: uSectionId.trim() || undefined,
      Modo: uMode,
      P_kW: uPKw === "" ? null : Number(uPKw),
      Q_kvar: uQKvar === "" ? null : Number(uQKvar),
      cosfi: uCosfi === "" ? 0.95 : Number(uCosfi),
      ok: true,
      Estado: "lista",
    };
  }

  async function updateOneAndConnect() {
    if (!hasCtx) {
      setUMsg("Aplique 1.1 al contexto actual antes de actualizar cargas");
      return;
    }
    const row = buildURow("ACTUALIZAR");
    if (!row) return;
    setBusy(true);
    setUMsg("Actualizando una carga y conectando en CYMDIST…");
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        result?: Json & { location_map_url?: string; LoadID?: string };
      }>("/api/cargas/nueva", {
        method: "POST",
        body: JSON.stringify({
          node_id: row.NodeID,
          load_name: row.Nombre,
          mode: row.Modo,
          P_kW: row.P_kW,
          Q_kvar: row.Q_kvar,
          cosfi: row.cosfi,
          accion: "ACTUALIZAR",
        }),
        timeoutMs: 300000,
      });
      if (!j.ok) throw new Error(j.error || "Error actualizar");
      const res = j.result || {};
      if (res.location_map_url) setMapUrl(String(res.location_map_url));
      setUMsg(
        `OK · ACTUALIZAR ${res.LoadID || row.Nombre} en CYMDIST` +
          " · disponible para §5."
      );
      setBatchRows((prev) => [
        ...prev.filter(
          (r) =>
            String(r.Nombre || "").toUpperCase() !== String(row.Nombre).toUpperCase()
        ),
        { ...row, Estado: "OK", LoadID: String(res.LoadID || row.Nombre) },
      ]);
      void loadConnected();
    } catch (e) {
      setUMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  function addURowToBatch(accion: "NUEVA" | "ACTUALIZAR" = "ACTUALIZAR") {
    const row = buildURow(accion);
    if (!row) return;
    setBatchRows((prev) => {
      const without = prev.filter(
        (r) => String(r.Nombre || "").toUpperCase() !== String(row.Nombre).toUpperCase()
      );
      return [...without, { ...row, row: without.length + 1 }];
    });
    setBatchMsg(
      `Fila ${accion} añadida a la tabla de bloque · ${row.Nombre}. Pulse «Conectar en bloque» cuando esté listo.`
    );
    setUMsg(`Añadida a bloque · ${row.Nombre} (${accion}).`);
  }

  return (
    <section className="panel">
      <h2>4 · Nueva carga concentrada (SpotLoad)</h2>
      <ContextBind hint="SpotLoad se crea y guarda en el estudio de §1" />
      <p className="muted">
        No se crean nodos: se usa un nodo existente del estudio activo.
        <b> 4.2</b> = una carga · <b>4.3</b> = mismas cargas en bloque (CSV/Excel, 1 o N filas).
        Ambos guardan en el estudio para §5. <b>4.3 es opcional</b>: si no lo usa, §5 sigue igual.
      </p>

      {/* —— Cargas ya en estudio (persistencia) —— */}
      <h3 style={{ marginTop: 12, marginBottom: 6, fontSize: 15 }}>
        Cargas §4 en el estudio (para §5)
      </h3>
      <div className="actions">
        <button type="button" className="ghost" disabled={busy || !hasCtx} onClick={() => void loadConnected()}>
          Actualizar listado
        </button>
        <button type="button" className="secondary" disabled={busy || !hasCtx} onClick={() => void verifyConnectedLive()}
          title="Reabre el estudio (solo lectura) y confirma que cada carga §4 realmente existe y esta Connected en CYMDIST">
          Verificar en CYMDIST
        </button>
        <span className="muted">{connectedMsg}</span>
      </div>
      <div className="wrap" style={{ marginTop: 6 }}>
        <table>
          <thead>
            <tr>
              <th>LoadID / Nombre</th>
              <th>NodeID</th>
              <th>SectionID</th>
              <th>P_kW</th>
              <th>Q_kvar</th>
              <th>Estado</th>
              <th>Verificado CYMDIST</th>
            </tr>
          </thead>
          <tbody>
            {connected.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  Ninguna aún — conecte con 4.2 (una) o 4.3 (bloque). 4.3 no es obligatorio.
                </td>
              </tr>
            ) : (
              connected.map((r, i) => (
                <tr key={i}>
                  <td>{r.Nombre || r.LoadID}</td>
                  <td>{r.NodeID}</td>
                  <td>{r.SectionID}</td>
                  <td>{r.P_kW ?? ""}</td>
                  <td>{r.Q_kvar ?? ""}</td>
                  <td>{r.Estado}</td>
                  <td title={r.detalle || ""}>
                    {r.verificado === undefined
                      ? "— pulse Verificar"
                      : r.verificado
                        ? "✓ OK"
                        : `✗ ${r.detalle || "revisar"}`}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {mapUrl ? (
        <div style={{ marginTop: 12 }}>
          <h3 style={{ margin: "0 0 6px", fontSize: 15 }}>Figura de ubicación (carga nueva)</h3>
          <img
            src={mapUrl}
            alt="Ubicación carga nueva"
            style={{
              maxWidth: "100%",
              borderRadius: 10,
              border: "1px solid var(--line)",
              background: "#111",
            }}
          />
        </div>
      ) : null}

      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "18px 0" }} />

      {/* —— 4.2 una —— */}
      <h3 style={{ marginTop: 0, marginBottom: 8, fontSize: 16 }}>
        4.2 · Nueva carga concentrada (una)
      </h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Busque el nodo y pulse <b>Buscar nodo 4.2</b>. Con 1 coincidencia se cargan Nodo y SectionID.
        Al conectar se guarda en el .zxst y se genera el mapa de ubicación.
      </p>

      <div className="grid">
        <div>
          <label>Buscar nodo</label>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && search()}
            placeholder="ej. 16955"
          />
        </div>
        <div style={{ display: "flex", alignItems: "end" }}>
          <button type="button" className="ghost" disabled={busy || !hasCtx} onClick={search}>
            Buscar nodo 4.2
          </button>
        </div>
        <div>
          <label>Nombre carga (DeviceNumber)</label>
          <input value={loadName} onChange={(e) => setLoadName(e.target.value)} />
        </div>
        <div>
          <label>Nodo seleccionado</label>
          <input value={nodeId} readOnly placeholder="— tras Buscar —" />
        </div>
        <div>
          <label>SectionID</label>
          <input value={sectionId} readOnly placeholder="— derivado del nodo —" />
        </div>
        <div>
          <label>Modo</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="KW_COSFI">P + cosφ</option>
            <option value="KW_KVAR">P + Q</option>
          </select>
        </div>
        <div>
          <label>P trifásica (kW)</label>
          <input value={pKw} onChange={(e) => setPKw(e.target.value)} />
        </div>
        <div>
          <label>Q (kvar)</label>
          <input
            value={qKvar}
            onChange={(e) => setQKvar(e.target.value)}
            disabled={mode === "KW_COSFI"}
            placeholder={mode === "KW_COSFI" ? "auto desde cosφ" : ""}
          />
        </div>
        <div>
          <label>cosφ</label>
          <input
            value={cosfi}
            onChange={(e) => setCosfi(e.target.value)}
            disabled={mode === "KW_KVAR"}
          />
        </div>
      </div>

      {candidates.length > 1 ? (
        <p className="muted">
          Tramos del nodo: {candidates.join(" · ")} (activo: <b>{sectionId || "—"}</b>)
        </p>
      ) : null}

      <div className="actions">
        <button
          type="button"
          disabled={busy || !hasCtx || !nodeId || !loadName || !sectionId}
          onClick={connect}
        >
          4.2 · Conectar y guardar en CYMDIST
        </button>
        <span className="muted">{msg}</span>
      </div>

      <div className="wrap">
        <table>
          <thead>
            <tr>
              <th>NodeID</th>
              <th>Section (preview)</th>
              <th>Tramos</th>
              <th>Info</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((n, i) => {
              const nid = nodeIdOf(n);
              const nSec = Array.isArray(n.sections) ? n.sections.length : Number(n.n_sections || 0);
              const selected = nid === nodeId;
              return (
                <tr
                  key={i}
                  style={{
                    cursor: "pointer",
                    background: selected ? "rgba(37,99,235,0.12)" : undefined,
                  }}
                  onClick={() => !busy && resolveNode(nid, loadName.trim() || nid)}
                >
                  <td>{nid}</td>
                  <td>{sectionPreview(n)}</td>
                  <td>{nSec || ""}</td>
                  <td>{String(n.Label || n.label || n.Name || "")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "22px 0" }} />

      {/* —— 4.3: una carga (campos 4.2) + bloque CSV —— */}
      <h3 style={{ marginTop: 0, marginBottom: 8, fontSize: 16 }}>
        4.3 · Actualizar una carga / cargas en bloque
      </h3>
      <p className="muted">
        <b>A)</b> Formulario (mismos campos que 4.2) para <b>actualizar una sola carga</b> y
        conectar en CYMDIST. <b>B)</b> CSV/Excel + <b>Conectar en bloque</b> (1 o N filas).
        Opcional: sin 4.3, §5 no se bloquea.
      </p>

      <h4 style={{ margin: "12px 0 6px", fontSize: 14 }}>
        A · Una sola carga (campos = 4.2)
      </h4>
      <div className="grid">
        <div>
          <label>Buscar nodo</label>
          <input
            value={uQ}
            onChange={(e) => setUQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && searchU()}
            placeholder="ej. 16955"
          />
        </div>
        <div style={{ display: "flex", alignItems: "end" }}>
          <button type="button" className="ghost" disabled={busy || !hasCtx} onClick={searchU}>
            Buscar nodo 4.3
          </button>
        </div>
        <div>
          <label>Nombre carga (DeviceNumber)</label>
          <input value={uLoadName} onChange={(e) => setULoadName(e.target.value)} />
        </div>
        <div>
          <label>Nodo seleccionado</label>
          <input value={uNodeId} readOnly placeholder="— tras Buscar —" />
        </div>
        <div>
          <label>SectionID</label>
          <input value={uSectionId} readOnly placeholder="— derivado del nodo —" />
        </div>
        <div>
          <label>Modo</label>
          <select value={uMode} onChange={(e) => setUMode(e.target.value)}>
            <option value="KW_COSFI">P + cosφ</option>
            <option value="KW_KVAR">P + Q</option>
          </select>
        </div>
        <div>
          <label>P trifásica (kW)</label>
          <input value={uPKw} onChange={(e) => setUPKw(e.target.value)} />
        </div>
        <div>
          <label>Q (kvar)</label>
          <input
            value={uQKvar}
            onChange={(e) => setUQKvar(e.target.value)}
            disabled={uMode === "KW_COSFI"}
            placeholder={uMode === "KW_COSFI" ? "auto desde cosφ" : ""}
          />
        </div>
        <div>
          <label>cosφ</label>
          <input
            value={uCosfi}
            onChange={(e) => setUCosfi(e.target.value)}
            disabled={uMode === "KW_KVAR"}
          />
        </div>
      </div>
      {uCandidates.length > 1 ? (
        <p className="muted">
          Tramos: {uCandidates.join(" · ")} (activo: <b>{uSectionId || "—"}</b>)
        </p>
      ) : null}
      <div className="actions">
        <button
          type="button"
          disabled={busy || !hasCtx || !uNodeId || !uLoadName || !uSectionId}
          onClick={() => void updateOneAndConnect()}
          title="Actualiza P/Q de esta carga y la escribe en CYMDIST"
        >
          4.3 · Actualizar y conectar en CYMDIST
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy || !uNodeId || !uLoadName}
          onClick={() => addURowToBatch("ACTUALIZAR")}
        >
          Añadir a tabla de bloque
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy || !uNodeId || !uLoadName}
          onClick={() => addURowToBatch("NUEVA")}
        >
          Añadir como NUEVA al bloque
        </button>
        <span className="muted">{uMsg}</span>
      </div>
      {uNodes.length > 1 ? (
        <div className="wrap" style={{ marginTop: 8 }}>
          <table>
            <thead>
              <tr>
                <th>NodeID</th>
                <th>Section</th>
                <th>Info</th>
              </tr>
            </thead>
            <tbody>
              {uNodes.map((n, i) => {
                const nid = nodeIdOf(n);
                return (
                  <tr
                    key={i}
                    style={{
                      cursor: "pointer",
                      background:
                        nid === uNodeId ? "rgba(37,99,235,0.12)" : undefined,
                    }}
                    onClick={() => !busy && resolveUNode(nid, uLoadName.trim() || nid)}
                  >
                    <td>{nid}</td>
                    <td>{sectionPreview(n)}</td>
                    <td>{String(n.Label || n.label || n.Name || "")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <h4 style={{ margin: "18px 0 6px", fontSize: 14 }}>
        B · Lote CSV / Excel + Conectar en bloque
      </h4>
      <p className="muted" style={{ marginTop: 0 }}>
        Mismos campos. Descargue plantilla, complete 1 o N filas, o use «Añadir a tabla»
        arriba. Luego <b>Conectar en bloque</b>.
      </p>

      <div className="actions">
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={async () => {
            try {
              setBusy(true);
              await downloadTemplate("xlsx");
              setBatchMsg("Plantilla Excel 4.3 (campos = 4.2) descargada.");
            } catch (e) {
              setBatchMsg(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          4.3 · Descargar plantilla (.xlsx)
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy}
          onClick={async () => {
            try {
              setBusy(true);
              await downloadTemplate("csv");
              setBatchMsg("Plantilla CSV 4.3 (campos = 4.2) descargada.");
            } catch (e) {
              setBatchMsg(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          4.3 · Descargar plantilla (.csv)
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => fileRef.current?.click()}
        >
          4.3 · Cargar CSV / Excel
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,.xlsx,.xlsm,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          style={{ display: "none" }}
          onChange={(e) => void onPickFile(e.target.files?.[0] || null)}
        />
        <button
          type="button"
          disabled={busy || !hasCtx || !batchRows.some((r) => r.ok !== false)}
          onClick={() => void connectBatch()}
          title="Conecta/actualiza todas las filas válidas en CYMDIST (bloque)"
        >
          4.3 · Conectar en bloque
        </button>
        <span className="muted">
          {batchFileName ? `Archivo: ${batchFileName}` : ""} {batchMsg}
        </span>
      </div>

      <div className="wrap" style={{ marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Accion</th>
              <th>NodeID</th>
              <th>Nombre</th>
              <th>SectionID</th>
              <th>Modo</th>
              <th>P_kW</th>
              <th>Q_kvar</th>
              <th>cosφ</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {batchRows.length === 0 ? (
              <tr>
                <td colSpan={10} className="muted">
                  Sin filas — descargue plantilla 4.3 (mismos campos 4.2), complete 1 o N
                  cargas y «Conectar en bloque». Opcional para §5.
                </td>
              </tr>
            ) : (
              batchRows.map((r, i) => (
                <tr
                  key={i}
                  style={{
                    background:
                      r.ok === false || r.error
                        ? "rgba(176,0,32,0.08)"
                        : String(r.Estado || "").toUpperCase().includes("OK")
                          ? "rgba(4,120,87,0.08)"
                          : undefined,
                  }}
                >
                  <td>{r.row ?? i + 1}</td>
                  <td>{r.Accion || "NUEVA"}</td>
                  <td>{r.NodeID}</td>
                  <td>{r.Nombre || r.LoadID}</td>
                  <td>{r.SectionID || "— auto"}</td>
                  <td>{r.Modo}</td>
                  <td>{r.P_kW ?? ""}</td>
                  <td>{r.Modo === "KW_KVAR" ? r.Q_kvar ?? "" : "—"}</td>
                  <td>{r.Modo === "KW_COSFI" ? r.cosfi ?? "" : "—"}</td>
                  <td>
                    {r.error ||
                      (r.errors && r.errors.length ? r.errors.join("; ") : null) ||
                      r.Estado ||
                      (r.ok === false ? "ERROR" : "OK")}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
