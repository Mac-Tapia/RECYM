import { useEffect, useState } from "react";
import { api, type Json } from "../api/client";

type Delivery = {
  ok?: boolean;
  ready?: boolean;
  missing?: string[];
  checks?: Record<string, boolean>;
  loadflow_situacional?: boolean;
  loadflow_proyectado?: boolean;
  meta?: boolean;
  charts?: boolean;
};

const META_FIELDS = [
  "cliente", "ubicacion", "solicitud", "potencia_kw", "potencia_txt",
  "alimentador", "set", "tension_kv", "transformador", "expediente",
] as const;

export function Step6Informes() {
  const [delivery, setDelivery] = useState<Delivery>({});
  const [paths, setPaths] = useState<Json>({});
  const [meta, setMeta] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [pdf, setPdf] = useState<File | null>(null);

  async function refreshStatus() {
    const j = await api<Delivery>("/api/informe/status");
    setDelivery(j);
  }

  async function refreshPaths() {
    const j = await api<Json>("/api/informe/rutas");
    setPaths(j);
  }

  async function loadMeta() {
    const j = await api<{ ok?: boolean; meta?: Record<string, unknown> }>("/api/informe/meta");
    const m = j.meta || {};
    const next: Record<string, string> = {};
    for (const k of META_FIELDS) next[k] = m[k] == null ? "" : String(m[k]);
    setMeta(next);
  }

  useEffect(() => {
    Promise.all([refreshStatus(), refreshPaths(), loadMeta()]).catch((e) => setMsg(String(e)));
  }, []);

  async function extractPdf() {
    if (!pdf) return;
    setBusy(true);
    setMsg("OCR…");
    try {
      const fd = new FormData();
      fd.append("file", pdf);
      const j = await api<{ ok?: boolean; error?: string; meta?: Record<string, unknown>; msg?: string }>(
        "/api/informe/meta_pdf",
        { method: "POST", body: fd, timeoutMs: 300000 }
      );
      if (!j.ok) throw new Error(j.error || "OCR falló");
      const m = j.meta || {};
      const next: Record<string, string> = { ...meta };
      for (const k of META_FIELDS) {
        if (m[k] != null) next[k] = String(m[k]);
      }
      setMeta(next);
      setMsg(j.msg || "OCR OK");
      await refreshStatus();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveMeta() {
    setBusy(true);
    try {
      const body: Json = { ...meta };
      if (meta.potencia_kw !== "") body.potencia_kw = Number(meta.potencia_kw);
      if (meta.tension_kv !== "") body.tension_kv = Number(meta.tension_kv);
      const j = await api<{ ok?: boolean; error?: string; msg?: string }>(
        "/api/informe/meta",
        { method: "POST", body: JSON.stringify(body) }
      );
      if (!j.ok) throw new Error(j.error || "Error guardar meta");
      setMsg(j.msg || "Meta guardada");
      await refreshStatus();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function fill() {
    setBusy(true);
    setMsg("Rellenando informes…");
    try {
      const j = await api<{ ok?: boolean; error?: string; msg?: string; missing?: string[] }>(
        "/api/informe/armar",
        { method: "POST", body: JSON.stringify({ fill: true }), timeoutMs: 180000 }
      );
      if (!j.ok) throw new Error(j.error || `Falta: ${(j.missing || []).join(", ")}`);
      setMsg(j.msg || "Informes OK");
      await refreshStatus();
      await refreshPaths();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  const chk = (key: string) => {
    const c = delivery.checks || {};
    if (key in c) return Boolean(c[key]);
    if (key === "sit") return Boolean(delivery.loadflow_situacional);
    if (key === "proy") return Boolean(delivery.loadflow_proyectado);
    if (key === "meta") return Boolean(delivery.meta);
    if (key === "img") return Boolean(delivery.charts);
    return false;
  };

  return (
    <section className="panel">
      <h2>6 · Informes de entrega</h2>
      <p className="muted">PDF OCR + ambos flujos §5 + gráficas → Word/Excel en doc/.</p>

      <div className="pathbox">
        <b>Checklist entrega</b>{" "}
        <span className={"badge" + (delivery.ready ? " ready" : "")}>
          {delivery.ready ? "lista" : "pendiente"}
        </span>
        <ul className="check-list">
          <li><span className={"dot " + (chk("sit") ? "ok" : "bad")} /> LoadFlow situacional</li>
          <li><span className={"dot " + (chk("proy") ? "ok" : "bad")} /> LoadFlow proyectado</li>
          <li><span className={"dot " + (chk("meta") ? "ok" : "bad")} /> Datos generales PDF OCR</li>
          <li><span className={"dot " + (chk("img") ? "ok" : "bad")} /> Gráficas LF (4 PNG)</li>
        </ul>
        <div className="actions">
          <button type="button" className="ghost" onClick={() => refreshStatus()}>6.0 · Actualizar checklist</button>
        </div>
        {(delivery.missing || []).length > 0 && (
          <div className="muted">Falta: {(delivery.missing || []).join(", ")}</div>
        )}
      </div>

      <h3>6.1 Datos generales (PDF → OCR)</h3>
      <div className="actions">
        <input type="file" accept=".pdf,application/pdf" onChange={(e) => setPdf(e.target.files?.[0] || null)} />
        <button type="button" className="secondary" disabled={busy || !pdf} onClick={extractPdf}>
          Extraer datos generales (OCR)
        </button>
        <button type="button" className="ghost" disabled={busy} onClick={loadMeta}>Cargar meta</button>
        <button type="button" disabled={busy} onClick={saveMeta}>Guardar meta</button>
      </div>
      <div className="grid">
        {META_FIELDS.map((k) => (
          <div key={k}>
            <label>{k}</label>
            <input
              value={meta[k] || ""}
              onChange={(e) => setMeta({ ...meta, [k]: e.target.value })}
            />
          </div>
        ))}
      </div>

      <h3>6.2 Rellenar Word/Excel</h3>
      <div className="actions">
        <button type="button" className="ghost" onClick={refreshPaths}>Ver rutas</button>
        <button type="button" disabled={busy} onClick={fill}>Rellenar informes → doc</button>
      </div>
      <div className="pathbox">
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(paths, null, 2)}</pre>
      </div>
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
