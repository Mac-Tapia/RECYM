import { useState } from "react";
import { runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

export function Step5Flujos() {
  const { feeder } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  async function runProjected() {
    if (!hasCtx) {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §5.");
      return;
    }
    setBusy("5.1");
    setMsg(`5.1 · ${feeder} · flujo proyectado…`);
    try {
      const payload: Json = { update_informe: true, scenario: "proyectado" };
      const j = await runJob("flujo", payload, (job) => setMsg(String(job.message || "5.1")));
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
        El estado situacional y sus capturas se ejecutan en <b>3.4</b>. Aquí se ejecuta
        únicamente el flujo <b>proyectado</b>, con las cargas nuevas de §4 conectadas,
        y se registra como evidencia 5.1 del informe.
      </p>
      <div className="actions">
        <button type="button" className={"secondary" + (busy === "5.1" ? " running" : "")}
          disabled={!!busy || !hasCtx} onClick={runProjected}>
          5.1 · Flujo proyectado
        </button>
      </div>
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
