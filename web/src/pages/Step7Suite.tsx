import { useState } from "react";
import { api, runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

export function Step7Suite() {
  const { feeder } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [msg, setMsg] = useState("");
  const [out, setOut] = useState("");
  const [busy, setBusy] = useState(false);
  const [nfId, setNfId] = useState("");
  const [nfName, setNfName] = useState("");
  const [nfNet, setNfNet] = useState("");
  const [nfKv, setNfKv] = useState("22.9");

  async function call(path: string, label: string, body?: Json, method = "POST") {
    if (!hasCtx && path !== "/api/suite/entorno") {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §7.");
      return;
    }
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

  async function job(action: string, label: string, body: Json = {}) {
    if (!hasCtx) {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §7.");
      return;
    }
    setBusy(true);
    setMsg(label + "…");
    try {
      const j = await runJob(action, body, (state) =>
        setMsg(String(state.message || label))
      );
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
      <ContextBind hint="Optimización y herramientas sobre el estudio/BD de §1" />
      <p className="muted">Herramientas del pipeline · alimentador {feeder || "—"}.</p>
      <h3>7.1 Nuevo alimentador</h3>
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
          7.1 · Crear alimentador
        </button>
      </div>

      <h3>7.2 Pipeline batch</h3>
      <div className="actions">
        <button type="button" className="secondary" disabled={busy || !hasCtx}
          onClick={() => {
            if (!confirm("Ejecutar pipeline completo. ¿Continuar?")) return;
            job("suite_pipeline", "Pipeline");
          }}>
          7.2 · Ejecutar pipeline alimentador
        </button>
        <span className="muted">{msg}</span>
      </div>
      <pre className="out muted">{out}</pre>
    </section>
  );
}
