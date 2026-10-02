import { useState } from "react";
import { api, runJob, type Json } from "../api/client";
import { SearchableSelect } from "../components/SearchableSelect";
import { useFeeder } from "../state/feeder";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

function fmtPu(value: unknown) {
  const n = Number(value);
  return value === null || value === undefined || !Number.isFinite(n) ? "—" : n.toFixed(4);
}

function TransferBaseline({ result }: { result: Json }) {
  const baseline = (result.baseline_peak as Record<string, Json> | undefined) || {};
  const recommendation = (result.recommendation as Json | undefined) || {};
  const rows: Array<[string, Json]> = [
    ["Origen", baseline.source || {}],
    ["Receptor", baseline.destination || {}],
  ];
  return (
    <div className="pathbox" style={{ marginTop: 10, overflowX: "auto" }}>
      <b>LoadFlow en máxima demanda</b>
      <table style={{ width: "100%", marginTop: 6 }}>
        <thead>
          <tr>
            <th>Rol</th>
            <th>Alimentador</th>
            <th>Vmin (pu)</th>
            <th>Vmax (pu)</th>
            <th>Equipos baja / alta V</th>
            <th>P (kW)</th>
            <th>Estado</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([role, row]) => (
            <tr key={role}>
              <td>{role}</td>
              <td>{String(row.feeder_short || row.network_id || "—")}</td>
              <td>{fmtPu(row.Vmin_pu)}</td>
              <td>{fmtPu(row.Vmax_pu)}</td>
              <td>{String(row.low_voltage_count ?? "—")} / {String(row.high_voltage_count ?? "—")}</td>
              <td>{row.P_kW == null ? "—" : String(row.P_kW)}</td>
              <td>
                {!row.ok
                  ? String(row.error || "sin LF")
                  : row.has_voltage_quality_issue
                    ? "Violación de tensión"
                    : "OK"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {recommendation.reason ? (
        <p className="muted" style={{ marginTop: 6 }}>
          Recomendación: {String(recommendation.reason)}
        </p>
      ) : null}
    </div>
  );
}

export function Step5Flujos() {
  const {
    feeder,
    network,
    studyPath,
    databaseMdb,
    studyMode,
    transferPeer,
    transferPeerNetwork,
    transferNode,
    transferSectionalizer,
    transferTieSwitch,
    setContext,
  } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [nodeQuery, setNodeQuery] = useState("");
  const [nodeId, setNodeId] = useState(transferNode);
  const [nodes, setNodes] = useState<Json[]>([]);
  const [transferDirection, setTransferDirection] = useState<"to-peer" | "to-primary">("to-peer");
  const [transferResult, setTransferResult] = useState<Json | null>(null);
  const pairReady = !!transferPeer && !!transferPeerNetwork;

  function nodeIdOf(node: Json) {
    return String(node.NodeID || node.node_id || node.id || "").trim();
  }

  async function searchTransferNodes() {
    if (!nodeQuery.trim()) {
      setMsg("Escriba un nodo o parte del identificador");
      return;
    }
    setBusy("5.2-search");
    try {
      const result = await api<{ nodes?: Json[]; results?: Json[] }>(
        `/api/nodos/buscar?q=${encodeURIComponent(nodeQuery.trim())}&limit=80`,
        { timeoutMs: 120000 }
      );
      const found = result.nodes || result.results || [];
      setNodes(found);
      const selected = found.length === 1 ? nodeIdOf(found[0]) : "";
      setNodeId(selected);
      if (selected) setContext({ transferNode: selected });
      setMsg(found.length ? `${found.length} nodo(s) encontrados` : "No se encontraron nodos");
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function prepareTransferAction() {
    if (!databaseMdb || !studyPath || !network || !transferPeer || !nodeId || !transferSectionalizer || !transferTieSwitch) {
      setMsg("Faltan contexto, alimentador, nodo, seccionador o punto de enlace");
      return;
    }
    if (!transferPeerNetwork) {
      setMsg("El par de transferencia no está preparado: confirme 1.1 en modo transferencia");
      return;
    }
    setTransferResult(null);
    setBusy("5.2");
    const source = transferDirection === "to-peer" ? feeder : transferPeer;
    const destination = transferDirection === "to-peer" ? transferPeer : feeder;
    setMsg(`Validando transferencia ${source} → ${destination} en nodo ${nodeId}…`);
    try {
      const result = await api<Json>("/api/cabecera/transfer-voltage-quality", {
        method: "POST",
        body: JSON.stringify({
          feeder,
          database_mdb: databaseMdb,
          study_path: studyPath,
          network_id: network,
          // Ambas redes: sin la del receptor el LF de destino no puede ejecutarse.
          network_ids: [network, transferPeerNetwork],
          transfer_pair: [source, destination],
          node_id: nodeId,
          sectionalizer_id: transferSectionalizer,
          tie_switch_id: transferTieSwitch,
          apply_switch: false,
          ensure_max_demand: false,
        }),
        timeoutMs: 900000,
      });
      setTransferResult(result);
      setMsg(
        result.ok
          ? String(result.msg || "Transferencia evaluada")
          : `ERROR · ${String(result.error || result.msg || "Transferencia no concluyente")}`
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

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

  async function runReportesInforme() {
    if (!hasCtx) {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §5.");
      return;
    }
    setBusy("5.1b");
    setMsg("5.1b · LoadFlow proyectado + coloreo (tensión/cargabilidad) + reportes CYMDIST…");
    try {
      const j = await runJob(
        "reportes_informe",
        { scenario: "proyectado" },
        (job) => setMsg(String(job.message || "5.1b"))
      );
      const captures = ((j.captures as Json | undefined)?.captures as Json[] | undefined) || [];
      const capturesLine = j.captures
        ? ` · capturas (tensión/cargabilidad) verificadas=${captures.filter((item) => item.ok).length}/2`
        : "";
      setMsg(
        (j.ok
          ? `5.1b OK · ${String(j.xlsx_target || "")}`
          : `5.1b · ${String(j.error || "No se pudo confirmar el metodo de reportes")}` +
            (j.discovery ? `\nAPI encontrada: ${JSON.stringify(j.discovery, null, 2).slice(0, 2000)}` : "")
        ) + capturesLine
      );
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
        <button type="button" className={"secondary" + (busy === "5.1b" ? " running" : "")}
          disabled={!!busy || !hasCtx} onClick={runReportesInforme}
          title="LoadFlow proyectado + captura nativa VoltageLevel/LoadingLevel (con la carga nueva de §4 conectada) + selección guardada en CYMDIST 'RECYM_Informe' (Barras/Cables/Cargas + Flujo de carga), exportado a Excel">
          5.1b · Reportes CYMDIST
        </button>
      </div>
      {studyMode === "transfer" ? <h3>5.2 · Transferencia de carga</h3> : null}
      {studyMode === "transfer" ? (
      <p className="muted">
        En §1 deben llegar cargados ambos alimentadores, con sus cargas actualizadas y las nuevas cargas conectadas.
        Aquí se prepara la transferencia y CYMDIST permanece abierto para revisar el seccionamiento.
      </p>
      ) : null}
      {studyMode === "transfer" ? (
      <div className="actions">
        <select value={transferDirection} disabled={!!busy || !hasCtx}
          onChange={(event) => setTransferDirection(event.target.value === "to-primary" ? "to-primary" : "to-peer")}>
          <option value="to-peer">{feeder} → {transferPeer || "segundo alimentador"}</option>
          <option value="to-primary">{transferPeer || "segundo alimentador"} → {feeder}</option>
        </select>
        <input value={nodeQuery} onChange={(event) => setNodeQuery(event.target.value)}
          disabled={!!busy || !hasCtx} placeholder="Nodo o punto de transferencia…" />
        <button type="button" className="ghost" disabled={!!busy || !hasCtx || !nodeQuery.trim()}
          onClick={() => void searchTransferNodes()}>
          Buscar nodo
        </button>
        {nodes.length > 1 ? (
          <SearchableSelect
            value={nodeId}
            options={nodes.map((node) => ({ value: nodeIdOf(node), label: nodeIdOf(node) }))}
            disabled={!!busy || !hasCtx}
            placeholder="Seleccionar nodo…"
            emptyLabel="— elegir —"
            onChange={(value) => {
              setNodeId(value);
              setContext({ transferNode: value });
            }}
          />
        ) : null}
        <input value={transferSectionalizer} disabled={!!busy || !hasCtx}
          placeholder="Seccionador a abrir" onChange={(event) => setContext({ transferSectionalizer: event.target.value })} />
        <input value={transferTieSwitch} disabled={!!busy || !hasCtx}
          placeholder="Punto de enlace a cerrar" onChange={(event) => setContext({ transferTieSwitch: event.target.value })} />
        <button type="button" className={"secondary" + (busy === "5.2" ? " running" : "")}
          disabled={!!busy || !hasCtx || !pairReady || !nodeId || !transferSectionalizer || !transferTieSwitch}
          onClick={() => void prepareTransferAction()}>
          5.2 · Transferir carga
        </button>
      </div>
      ) : null}
      {studyMode === "transfer" && !pairReady ? (
        <p className="muted">
          Par no preparado: en §1 elija el receptor y confirme 1.1 para cargar ambas redes con su máxima demanda.
        </p>
      ) : null}
      {studyMode === "transfer" && transferResult ? (
        <TransferBaseline result={transferResult} />
      ) : null}
      <pre className="out muted">{msg}</pre>
    </section>
  );
}
