import { useState } from "react";
import { runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";

export function Step5Flujos() {
  const { feeder } = useFeeder();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  async function run(scenario?: string, label = "5") {
    setBusy(label);
    setMsg(`${label}…`);
    try {
      const payload: Json = { update_informe: true };
      if (scenario) payload.scenario = scenario;
      const j = await runJob("flujo", payload, (job) => setMsg(String(job.message || label)));
      setMsg(JSON.stringify(j, null, 2).slice(0, 1500));
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <h2>5 · Análisis CYMDIST (flujos)</h2>
      <p className="muted">
        Alimentador <b>{feeder || "—"}</b>. Independiente de §4.1 (eliminado).
        Situacional desconecta las SpotLoad §4 ya guardadas; proyectado las conecta.
        Basta con haber conectado cargas vía <b>4.2</b> <i>o</i> <b>4.3</b> (no hace falta ambos).
        Cada botón es independiente. Tras OK se intenta actualizar §6.
      </p>
      <div className="actions">
        <button type="button" className={"secondary" + (busy === "5.1" ? " running" : "")}
          disabled={!!busy} onClick={() => run("situacional", "5.1")}>
          5.1 · Flujo estado situacional
        </button>
        <button type="button" className={"secondary" + (busy === "5.2" ? " running" : "")}
          disabled={!!busy} onClick={() => run("proyectado", "5.2")}>
          5.2 · Flujo con cargas nuevas
        </button>
        <button type="button" className={"ghost" + (busy === "5.3" ? " running" : "")}
          disabled={!!busy} onClick={() => run(undefined, "5.3")}>
          5.3 · Flujo general
        </button>
      </div>
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
