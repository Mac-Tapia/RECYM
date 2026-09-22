import { useState } from "react";
import { api, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";

export function Step7Suite() {
  const { feeder } = useFeeder();
  const [force, setForce] = useState(false);
  const [msg, setMsg] = useState("");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [nfId, setNfId] = useState("");
  const [nfName, setNfName] = useState("");
  const [nfNet, setNfNet] = useState("");
  const [nfKv, setNfKv] = useState("22.9");

  async function call(path: string, label: string, body?: Json, method = "POST") {
    setBusy(true);
    setMsg(label + "…");
    try {
      const j = await api<Json>(path, {
        method,
        body: method === "GET" ? undefined : JSON.stringify(body || {}),
        timeoutMs: 600000,
      });
      setOut(JSON.stringify(j, null, 2));
      setMsg(String(j.msg || (j.ok ? "OK" : j.error) || label));
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>7 · Optimización + Suite</h2>
      <p className="muted">Herramientas del pipeline · contexto §1 ({feeder || "—"}).</p>

      <h3>7.1 Optimización CYMDIST</h3>
      <div className="actions">
        <label style={{ display: "inline-flex", gap: 6, alignItems: "center", margin: 0 }}>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Forzar
        </label>
        <button type="button" className="secondary" disabled={busy}
          onClick={() => call("/api/optimizacion/reclosers", "7.1a Reclosers", { force })}>
          7.1a · Reconectadores
        </button>
        <button type="button" className="secondary" disabled={busy}
          onClick={() => call("/api/optimizacion/regulators", "7.1b Regulators", { force })}>
          7.1b · Reguladores
        </button>
        <button type="button" className="secondary" disabled={busy}
          onClick={() => call("/api/optimizacion/capacitors", "7.1c Capacitors", { force })}>
          7.1c · Capacitores
        </button>
      </div>

      <h3>7.2 Entorno y conexión</h3>
      <div className="actions">
        <button type="button" className="ghost" disabled={busy}
          onClick={() => call("/api/suite/entorno", "Entorno", undefined, "GET")}>
          7.2a · Validar entorno
        </button>
        <button type="button" className="secondary" disabled={busy}
          onClick={() => call("/api/suite/conexion", "Conexión")}>
          7.2b · Probar conexión CYMDIST
        </button>
        <button type="button" className="ghost" disabled={busy}
          onClick={() => call("/api/suite/validar_entradas", "Validar entradas")}>
          7.2c · Validar entradas Excel
        </button>
        <button type="button" className="ghost" disabled={busy}
          onClick={() => call("/api/suite/inventario_cargas", "Inventario", { system: true })}>
          7.2d · Inventario SpotLoad (96)
        </button>
      </div>

      <h3>7.3 Equipos / modelo</h3>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy}
          onClick={() => call("/api/suite/sync_equipos", "Sync equipos")}>
          7.3a · Sync equipos Excel → CYMDIST
        </button>
        <button type="button" className="ghost" disabled={busy}
          onClick={() => call("/api/suite/fix_default", "Fix DEFAULT")}>
          7.3b · Cerrar DEFAULT AAAC/XLPE
        </button>
        <button type="button" className="ghost" disabled={busy}
          onClick={() => call("/api/suite/export_ascii", "Export ASCII")}>
          7.3c · Exportar ASCII
        </button>
      </div>

      <h3>7.4 Nuevo alimentador</h3>
      <div className="grid">
        <div>
          <label>ID</label>
          <input value={nfId} onChange={(e) => setNfId(e.target.value)} placeholder="PA218" />
        </div>
        <div>
          <label>Nombre</label>
          <input value={nfName} onChange={(e) => setNfName(e.target.value)} />
        </div>
        <div>
          <label>NetworkID</label>
          <input value={nfNet} onChange={(e) => setNfNet(e.target.value)} placeholder="NET_PA218" />
        </div>
        <div>
          <label>Tensión LL (kV)</label>
          <input value={nfKv} onChange={(e) => setNfKv(e.target.value)} />
        </div>
      </div>
      <div className="actions">
        <button type="button" disabled={busy}
          onClick={() => call("/api/suite/nuevo_alimentador", "Nuevo feeder", {
            feeder_id: nfId, name: nfName, network_id: nfNet, voltage_kv: Number(nfKv),
          })}>
          7.4 · Crear alimentador
        </button>
      </div>

      <h3>7.5 Pipeline batch</h3>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy}
          onClick={() => {
            if (!confirm("Ejecutar pipeline completo. ¿Continuar?")) return;
            call("/api/suite/pipeline", "Pipeline");
          }}>
          7.5 · Ejecutar pipeline alimentador
        </button>
        <span className="muted">{msg}</span>
      </div>
      <pre className="out muted">{out}</pre>
    </section>
  );
}
