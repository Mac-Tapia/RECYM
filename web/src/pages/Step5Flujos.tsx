import { useState } from "react";
import { runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

export function Step5Flujos() {
  const { feeder } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  async function run(scenario?: string, label = "5") {
    if (!hasCtx) {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §5.");
      return;
    }
    setBusy(label);
    setMsg(`${label} · ${feeder}…`);
    try {
      const payload: Json = { update_informe: true };
      if (scenario) payload.scenario = scenario;
      const j = await runJob("flujo", payload, (job) => setMsg(String(job.message || label)));
      setMsg(String(j.msg || JSON.stringify(j, null, 2).slice(0, 1500)));
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <h2>5 · Análisis CYMDIST (flujos)</h2>
      <ContextBind hint="LoadFlow sobre el mismo estudio/BD de §1" />
      <p className="muted">
        Situacional desconecta las SpotLoad §4 ya guardadas; proyectado las conecta.
        Basta con <b>4.2</b> (una) <i>y/o</i> <b>4.3</b> (bloque).{" "}
        <b>4.3 es opcional</b>: si no hay lote, §5 no se bloquea.
        Cada botón es independiente. Tras OK se intenta actualizar §6.
      </p>
      <div className="actions">
        <button type="button" className={"secondary" + (busy === "5.1" ? " running" : "")}
          disabled={!!busy || !hasCtx} onClick={() => run("situacional", "5.1")}>
          5.1 · Flujo estado situacional
        </button>
        <button type="button" className={"secondary" + (busy === "5.2" ? " running" : "")}
          disabled={!!busy || !hasCtx} onClick={() => run("proyectado", "5.2")}>
          5.2 · Flujo con cargas nuevas
        </button>
        <button type="button" className={"ghost" + (busy === "5.3" ? " running" : "")}
          disabled={!!busy || !hasCtx} onClick={() => run(undefined, "5.3")}>
          5.3 · Flujo general
        </button>
      </div>
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
