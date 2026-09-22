import { useEffect, useState } from "react";
import { api, getActiveFeeder, type Json } from "../api/client";

type Delivery = {
  ok?: boolean;
  ready?: boolean;
  delivery_ready?: boolean;
  missing?: string[];
  checks?: Record<string, boolean>;
  loadflow_situacional?: boolean;
  loadflow_proyectado?: boolean;
  meta?: boolean;
  charts?: boolean;
};

type PreviewImage = {
  name: string;
  url: string;
  bytes?: number;
  required?: boolean;
};

type Preview = {
  ok?: boolean;
  preview_ok?: boolean;
  can_close?: boolean;
  closed?: boolean;
  msg?: string;
  filled_at?: string;
  feeder_id?: string;
  meta?: Record<string, unknown>;
  scenarios_used?: {
    situacional?: boolean;
    proyectado?: boolean;
    situacional_metrics?: Record<string, number | null>;
    proyectado_metrics?: Record<string, number | null>;
  };
  images?: PreviewImage[];
  docs?: {
    informe?: { exists?: boolean; url?: string; bytes?: number };
    justificacion?: { exists?: boolean; url?: string; bytes?: number };
    pdf?: { exists?: boolean; url?: string; bytes?: number };
  };
  page_previews?: PreviewImage[];
  render?: { ok?: boolean; pages?: number; pdf?: string; rendered_at?: string };
  word_replacements?: { old?: string; new?: string; count?: number }[];
  confirm?: { confirmed_at?: string; note?: string } | null;
  error?: string;
};

const META_FIELDS = [
  "cliente", "ubicacion", "solicitud", "potencia_kw", "potencia_txt",
  "alimentador", "set", "tension_kv", "transformador", "expediente",
] as const;

const METRIC_ROWS: { key: string; label: string; digits?: number }[] = [
  { key: "kw", label: "P (kW)", digits: 1 },
  { key: "kvar", label: "Q (kvar)", digits: 1 },
  { key: "kva", label: "S (kVA)", digits: 1 },
  { key: "fp_pct", label: "FP (%)", digits: 2 },
  { key: "v_pct_a", label: "V% A", digits: 2 },
  { key: "v_pct_b", label: "V% B", digits: 2 },
  { key: "v_pct_c", label: "V% C", digits: 2 },
  { key: "i_a", label: "I (A)", digits: 1 },
];

function fmt(v: unknown, digits = 2): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("es-PE", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function Step6Informes() {
  const [delivery, setDelivery] = useState<Delivery>({});
  const [paths, setPaths] = useState<Json>({});
  const [meta, setMeta] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [validated, setValidated] = useState(false);
  const [closeNote, setCloseNote] = useState("");
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

  async function loadPreview() {
    const j = await api<Preview>("/api/informe/preview");
    setPreview(j);
    if (j.closed) setValidated(true);
    else setValidated(false);
    return j;
  }

  useEffect(() => {
    Promise.all([refreshStatus(), refreshPaths(), loadMeta(), loadPreview()]).catch((e) =>
      setMsg(String(e))
    );
  }, []);

  async function extractPdf() {
    if (!pdf) return;
    setBusy(true);
    setMsg("OCR…");
    try {
      const fd = new FormData();
      fd.append("pdf", pdf, pdf.name);
      const j = await api<{
        ok?: boolean;
        error?: string;
        meta?: Record<string, unknown>;
        msg?: string;
        method?: string;
        complete?: boolean;
        warnings?: string[];
      }>("/api/informe/meta_pdf", { method: "POST", body: fd, timeoutMs: 300000 });
      if (!j.ok) throw new Error(j.error || "OCR falló");
      const m = j.meta || {};
      const next: Record<string, string> = { ...meta };
      for (const k of META_FIELDS) {
        if (m[k] != null && String(m[k]).trim() !== "") next[k] = String(m[k]);
      }
      setMeta(next);
      const tag = j.complete ? "completa" : "parcial (complete cliente/potencia)";
      setMsg(
        `OCR OK (${j.method || "?"}) · meta ${tag}` +
          (j.warnings && j.warnings.length ? ` · avisos: ${j.warnings.join("; ")}` : "")
      );
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
    setValidated(false);
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        msg?: string;
        missing?: string[];
        needs_preview_confirm?: boolean;
      }>("/api/informe/armar", {
        method: "POST",
        body: JSON.stringify({ fill: true }),
        timeoutMs: 180000,
      });
      if (!j.ok) throw new Error(j.error || `Falta: ${(j.missing || []).join(", ")}`);
      setMsg((j.msg || "Informes OK") + " · revise la vista preliminar antes de cerrar.");
      await refreshStatus();
      await refreshPaths();
      const prev = await loadPreview();
      if (prev.preview_ok) {
        document.getElementById("informe-preview")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function regenMap() {
    setBusy(true);
    setMsg("Generando mapa satélite de la carga nueva…");
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        msg?: string;
        location?: { NodeID?: string; lat?: number; lon?: number };
      }>("/api/informe/mapa_ubicacion", {
        method: "POST",
        body: "{}",
        timeoutMs: 120000,
      });
      if (!j.ok) throw new Error(j.error || "No se generó el mapa");
      const loc = j.location || {};
      setMsg(
        (j.msg || "Mapa OK") +
          (loc.NodeID ? ` · nodo ${loc.NodeID}` : "") +
          (loc.lat != null ? ` · ${Number(loc.lat).toFixed(5)}, ${Number(loc.lon).toFixed(5)}` : "")
      );
      await loadPreview();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function closeDelivery() {
    if (!validated) {
      setMsg("Marque que validó la vista preliminar antes de cerrar.");
      return;
    }
    if (!confirm("¿Cerrar entrega? Confirma que el informe preliminar es correcto.")) return;
    setBusy(true);
    setMsg("Cerrando entrega…");
    try {
      const j = await api<{ ok?: boolean; error?: string; msg?: string }>(
        "/api/informe/cerrar",
        {
          method: "POST",
          body: JSON.stringify({ validated: true, note: closeNote }),
          timeoutMs: 60000,
        }
      );
      if (!j.ok) throw new Error(j.error || "No se pudo cerrar");
      setMsg(j.msg || "Entrega cerrada");
      await loadPreview();
      await refreshStatus();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  }

  const chk = (key: string) => {
    const c = delivery.checks || {};
    if (key === "sit") return Boolean(c.loadflow_situacional ?? delivery.loadflow_situacional);
    if (key === "proy") return Boolean(c.loadflow_proyectado ?? delivery.loadflow_proyectado);
    if (key === "meta") return Boolean(c.informe_meta_ocr ?? delivery.meta);
    if (key === "img") return Boolean(c.lf_images ?? delivery.charts);
    if (key in c) return Boolean(c[key]);
    return false;
  };

  const sit = preview?.scenarios_used?.situacional_metrics || {};
  const proy = preview?.scenarios_used?.proyectado_metrics || {};
  const feederHdr = getActiveFeeder() || preview?.feeder_id || "—";
  const cacheBust = preview?.filled_at ? encodeURIComponent(preview.filled_at) : String(Date.now());

  return (
    <section className="panel">
      <h2>6 · Informes de entrega</h2>
      <p className="muted">
        PDF OCR + ambos flujos §5 + gráficas → Word/Excel en doc/. Antes de cerrar, valide la vista preliminar.
        · alimentador {feederHdr}
      </p>

      <div className="pathbox">
        <b>Checklist entrega</b>{" "}
        <span className={"badge" + (delivery.ready || delivery.delivery_ready ? " ready" : "")}>
          {delivery.ready || delivery.delivery_ready ? "lista" : "pendiente"}
        </span>
        {preview?.closed && <span className="badge ready" style={{ marginLeft: 6 }}>cerrada</span>}
        <ul className="check-list">
          <li><span className={"dot " + (chk("sit") || chk("loadflow_situacional") ? "ok" : "bad")} /> LoadFlow situacional</li>
          <li><span className={"dot " + (chk("proy") || chk("loadflow_proyectado") ? "ok" : "bad")} /> LoadFlow proyectado</li>
          <li><span className={"dot " + (chk("meta") || chk("informe_meta_ocr") ? "ok" : "bad")} /> Datos generales PDF OCR</li>
          <li><span className={"dot " + (chk("img") || chk("lf_images") ? "ok" : "bad")} /> Gráficas LF (4 PNG)</li>
          <li><span className={"dot " + (preview?.preview_ok ? "ok" : "bad")} /> Vista preliminar</li>
          <li><span className={"dot " + (preview?.closed ? "ok" : "wait")} /> Entrega cerrada</li>
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
      <p className="muted">
        Al rellenar se genera también <code>topologia.png</code>: mapa satélite del nodo donde se conectó la carga nueva (§4).
      </p>
      <div className="actions">
        <button type="button" className="ghost" onClick={refreshPaths}>Ver rutas</button>
        <button type="button" disabled={busy} onClick={fill}>Rellenar informes → doc</button>
        <button type="button" className="secondary" disabled={busy} onClick={regenMap}>
          Mapa ubicación carga nueva
        </button>
      </div>
      <div className="pathbox">
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(paths, null, 2)}</pre>
      </div>

      <h3 id="informe-preview">6.3 Vista preliminar (validar antes de cerrar)</h3>
      <p className="muted">
        Revise cliente, potencias, métricas LoadFlow y el informe renderizado (PDF/páginas).
        {preview?.filled_at ? ` · generado ${preview.filled_at}` : ""}
        {preview?.render?.pages ? ` · ${preview.render.pages} pág.` : ""}
      </p>
      <div className="actions">
        <button type="button" className="ghost" disabled={busy} onClick={() => loadPreview().catch((e) => setMsg(String(e)))}>
          Actualizar preliminar
        </button>
        {preview?.docs?.informe?.exists && (
          <a className="btn-link" href={preview.docs.informe.url || "/api/informe/archivo/informe"} download>
            Descargar informe.docx
          </a>
        )}
        {preview?.docs?.justificacion?.exists && (
          <a className="btn-link" href={preview.docs.justificacion.url || "/api/informe/archivo/justificacion"} download>
            Descargar justificacion.xlsx
          </a>
        )}
        {preview?.docs?.pdf?.exists && (
          <a className="btn-link" href={preview.docs.pdf.url || "/api/informe/archivo/pdf"} download>
            Descargar informe.pdf
          </a>
        )}
      </div>

      {!preview?.preview_ok && (
        <div className="pathbox bad">
          {preview?.msg || preview?.error || "Aún no hay informe completo para previsualizar. Ejecute 6.2."}
        </div>
      )}

      {preview?.preview_ok && (
        <div className="preview-panel">
          <div className="preview-meta grid">
            {[
              ["Cliente", preview.meta?.cliente],
              ["Proyecto", preview.meta?.proyecto],
              ["Potencia", preview.meta?.potencia_txt || preview.meta?.potencia_kw],
              ["Alimentador", preview.meta?.alimentador],
              ["Tensión kV", preview.meta?.tension_kv],
              ["Expediente", preview.meta?.expediente],
              ["Ubicación", preview.meta?.ubicacion],
              ["Solicitud", preview.meta?.solicitud],
            ].map(([lab, val]) => (
              <div key={String(lab)}>
                <label>{lab}</label>
                <div className="preview-val">{val == null || val === "" ? "—" : String(val)}</div>
              </div>
            ))}
          </div>

          <div className="wrap" style={{ maxHeight: "none", marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Métrica</th>
                  <th>Situacional</th>
                  <th>Proyectado</th>
                </tr>
              </thead>
              <tbody>
                {METRIC_ROWS.map((r) => (
                  <tr key={r.key}>
                    <td>{r.label}</td>
                    <td className="num">{fmt(sit[r.key], r.digits)}</td>
                    <td className="num">{fmt(proy[r.key], r.digits)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="preview-gallery">
            {(preview.images || [])
              .slice()
              .sort((a, b) => {
                // topologia (mapa carga nueva) primero
                if (a.name === "topologia.png") return -1;
                if (b.name === "topologia.png") return 1;
                return a.name.localeCompare(b.name);
              })
              .map((img) => (
              <figure key={img.name} className={img.name === "topologia.png" ? "preview-hero" : undefined}>
                <img src={`${img.url}?t=${cacheBust}`} alt={img.name} />
                <figcaption>
                  {img.name === "topologia.png"
                    ? "Ubicación carga nueva (satélite)"
                    : img.name}
                  {img.required ? "" : img.name === "topologia.png" ? "" : " (opcional)"}
                </figcaption>
              </figure>
            ))}
          </div>

          {(preview.page_previews || []).length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h4 style={{ margin: "0 0 8px" }}>Informe renderizado (páginas)</h4>
              <div className="preview-gallery">
                {(preview.page_previews || []).map((pg) => (
                  <figure key={pg.name} style={{ maxWidth: 420 }}>
                    <img src={`${pg.url}?t=${cacheBust}`} alt={pg.name} />
                    <figcaption>{pg.name}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
          )}

          {(preview.word_replacements || []).length > 0 && (
            <details className="pathbox" style={{ marginTop: 12 }}>
              <summary>Sustituciones Word ({preview.word_replacements!.length})</summary>
              <ul className="muted" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                {preview.word_replacements!.slice(0, 20).map((r, i) => (
                  <li key={i}>
                    <code>{r.old}</code> → <code>{r.new}</code>
                    {r.count != null ? ` ×${r.count}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <h3>6.4 Cerrar entrega</h3>
      <p className="muted">
        Solo después de validar la vista preliminar. Un nuevo relleno invalida el cierre y obliga a revisar otra vez.
      </p>
      <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "10px 0" }}>
        <input
          type="checkbox"
          checked={validated}
          disabled={!preview?.preview_ok || Boolean(preview?.closed)}
          onChange={(e) => setValidated(e.target.checked)}
        />
        He revisado la vista preliminar y el informe es correcto
      </label>
      <div className="grid" style={{ maxWidth: 480 }}>
        <div>
          <label>Nota de cierre (opcional)</label>
          <input
            value={closeNote}
            disabled={Boolean(preview?.closed)}
            onChange={(e) => setCloseNote(e.target.value)}
            placeholder="Ej. revisado con ingeniería"
          />
        </div>
      </div>
      <div className="actions">
        <button
          type="button"
          disabled={busy || !preview?.preview_ok || !validated || Boolean(preview?.closed)}
          onClick={closeDelivery}
        >
          {preview?.closed ? "Entrega ya cerrada" : "Cerrar entrega"}
        </button>
        {preview?.closed && preview.confirm?.confirmed_at && (
          <span className="ok">Confirmada {preview.confirm.confirmed_at}</span>
        )}
      </div>

      <pre className="out muted">{msg}</pre>
    </section>
  );
}
