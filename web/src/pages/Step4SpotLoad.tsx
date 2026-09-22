import { useState } from "react";
import { api, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";

export function Step4SpotLoad() {
  const { feeder } = useFeeder();
  const [q, setQ] = useState("");
  const [nodes, setNodes] = useState<Json[]>([]);
  const [nodeId, setNodeId] = useState("");
  const [sectionId, setSectionId] = useState("");
  const [loadName, setLoadName] = useState("");
  const [mode, setMode] = useState("KW_COSFI");
  const [pKw, setPKw] = useState("");
  const [qKvar, setQKvar] = useState("");
  const [cosfi, setCosfi] = useState("0.95");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function search() {
    setBusy(true);
    try {
      const j = await api<{ ok?: boolean; error?: string; nodes?: Json[]; results?: Json[] }>(
        `/api/nodos/buscar?q=${encodeURIComponent(q)}&limit=80`
      );
      if (j.ok === false) throw new Error(j.error || "Error búsqueda");
      setNodes(j.nodes || j.results || []);
      setMsg(`${(j.nodes || j.results || []).length} nodos`);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function refreshInventory() {
    setBusy(true);
    setMsg("Actualizando inventario nodos…");
    try {
      const j = await api<{ ok?: boolean; error?: string; msg?: string; n?: number }>(
        "/api/nodos/inventario",
        { method: "POST", body: JSON.stringify({ refresh: true }), timeoutMs: 300000 }
      );
      if (!j.ok) throw new Error(j.error || "Error inventario");
      setMsg(j.msg || `Inventario OK · ${j.n ?? ""}`);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resolveNode(nid: string) {
    setNodeId(nid);
    try {
      const j = await api<{ ok?: boolean; error?: string; SectionID?: string; section_id?: string }>(
        "/api/nodos/resolver",
        { method: "POST", body: JSON.stringify({ node_id: nid, load_name: loadName }) }
      );
      if (!j.ok) throw new Error(j.error || "No se resolvió sección");
      setSectionId(String(j.SectionID || j.section_id || ""));
    } catch (e) {
      setMsg(String(e));
    }
  }

  async function connect() {
    setBusy(true);
    setMsg("Conectando SpotLoad…");
    try {
      const j = await api<{ ok?: boolean; error?: string; result?: Json }>(
        "/api/cargas/nueva",
        {
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
        }
      );
      if (!j.ok) throw new Error(j.error || "Error conectar");
      setMsg(JSON.stringify(j.result || j, null, 2).slice(0, 1200));
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>4 · Nueva carga concentrada (SpotLoad)</h2>
      <p className="muted">
        Estudio activo: <b>{feeder || "—"}</b>. P trifásica → A/B/C = P/3, Q/3. Locked (fuera de distribución).
      </p>

      <div className="actions">
        <button type="button" className="ghost" disabled={busy} onClick={refreshInventory}>
          4.1 · Actualizar inventario nodos
        </button>
      </div>

      <div className="grid">
        <div>
          <label>Buscar nodo</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} />
        </div>
        <div style={{ display: "flex", alignItems: "end" }}>
          <button type="button" className="ghost" disabled={busy} onClick={search}>Buscar</button>
        </div>
        <div>
          <label>Nombre carga (DeviceNumber)</label>
          <input value={loadName} onChange={(e) => setLoadName(e.target.value)} />
        </div>
        <div>
          <label>Nodo seleccionado</label>
          <input value={nodeId} readOnly />
        </div>
        <div>
          <label>SectionID</label>
          <input value={sectionId} readOnly />
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
          <input value={qKvar} onChange={(e) => setQKvar(e.target.value)} />
        </div>
        <div>
          <label>cosφ</label>
          <input value={cosfi} onChange={(e) => setCosfi(e.target.value)} />
        </div>
      </div>

      <div className="actions">
        <button type="button" disabled={busy || !nodeId || !loadName} onClick={connect}>
          4.2 · Conectar carga en CYMDIST
        </button>
        <span className="muted">{msg}</span>
      </div>

      <div className="wrap">
        <table>
          <thead><tr><th>NodeID</th><th>Section</th><th>Info</th></tr></thead>
          <tbody>
            {nodes.map((n, i) => {
              const nid = String(n.NodeID || n.node_id || n.id || "");
              return (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => resolveNode(nid)}>
                  <td>{nid}</td>
                  <td>{String(n.SectionID || n.section_id || "")}</td>
                  <td>{String(n.Label || n.label || n.Name || "")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
