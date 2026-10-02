import { useEffect, useState } from "react";
import { api, downloadApiFile, runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";
import { sortByPeriodDesc } from "../context/periodFiles";
import { ContextBind, useHasSectionContext } from "../components/ContextBind";

type ActionId = "" | "3.1" | "3.2" | "3.3" | "3.3b" | "3.4" | "3.4b" | "files" | "incluir";

function truthy(v: unknown) {
  return v === true || v === "True" || v === "true" || v === "1" || v === 1;
}

function rowKey(r: Json) {
  return `${String(r.Suministro || "").trim()}|${String(r.SED || "").trim()}`;
}

export function Step3Clientes() {
  const { feeder } = useFeeder();
  const hasCtx = useHasSectionContext();
  const [suministro, setSuministro] = useState("");
  const [clientesFile, setClientesFile] = useState("");
  const [files, setFiles] = useState<{ suministro?: string[]; clientesimportantes?: string[] }>({});
  const [rows, setRows] = useState<Json[]>([]);
  const [activo, setActivo] = useState<Record<string, boolean>>({});
  const [restarCab, setRestarCab] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState<ActionId>("");

  /** Solo el botón activo se marca .running; los demás se bloquean sin parecer en ejecución. */
  function btnProps(id: ActionId, kind: "secondary" | "ghost" | "" = "") {
    const active = busy === id;
    return {
      className: `${kind}${active ? " running" : ""}`.trim(),
      disabled: Boolean(busy) || !hasCtx,
      "aria-busy": active,
    } as const;
  }

  function syncActivoFromRows(list: Json[]) {
    const map: Record<string, boolean> = {};
    const rmap: Record<string, boolean> = {};
    for (const r of list) {
      const key = rowKey(r);
      map[key] = truthy(r.Activo ?? true);
      rmap[key] = truthy(r.RestarCabecera ?? false);
    }
    setActivo(map);
    setRestarCab(rmap);
  }

  function markAll(on: boolean) {
    const next: Record<string, boolean> = {};
    for (const r of rows) next[rowKey(r)] = on;
    setActivo(next);
  }

  function markAllRestar(on: boolean) {
    const next: Record<string, boolean> = {};
    for (const r of rows) next[rowKey(r)] = on;
    setRestarCab(next);
  }

  function activoMapFromUi() {
    const map: Record<string, boolean> = {};
    for (const r of rows) {
      const key = rowKey(r);
      map[key] = activo[key] !== false;
    }
    return map;
  }

  function restarCabMapFromUi() {
    const map: Record<string, boolean> = {};
    for (const r of rows) {
      const key = rowKey(r);
      map[key] = restarCab[key] === true;
    }
    return map;
  }

  const nIncluidas = rows.filter((r) => activo[rowKey(r)] !== false).length;
  const nExcluidas = rows.length - nIncluidas;
  const nRestanCab = rows.filter(
    (r) => activo[rowKey(r)] === false && restarCab[rowKey(r)] === true
  ).length;

  async function loadFiles() {
    const j = await api<{ ok?: boolean; suministro?: string[]; clientesimportantes?: string[] }>(
      "/api/clientes/archivos"
    );
    // Al iniciar o tras Actualizar: lectura del periodo más reciente (MMAA).
    const sum = sortByPeriodDesc(j.suministro || []);
    const ci = sortByPeriodDesc(j.clientesimportantes || []);
    setFiles({ ...j, suministro: sum, clientesimportantes: ci });
    if (!suministro && sum[0]) setSuministro(sum[0]);
    if (!clientesFile && ci[0]) setClientesFile(ci[0]);
  }

  useEffect(() => {
    loadFiles().catch((e) => setMsg(String(e)));
  }, []);

  async function buildTable() {
    if (!hasCtx) {
      setMsg("Seleccione MDB, alimentador y estudio; aplique 1.1 antes de armar la tabla");
      return;
    }
    const fid = (feeder || "").trim();
    if (!fid) {
      setMsg("Defina el alimentador en §1 (1.1 · Aplicar) antes de armar la tabla.");
      return;
    }
    if (!clientesFile) {
      setMsg("Seleccione un archivo de clientesimportantes.");
      return;
    }
    setBusy("3.1");
    // Limpiar tabla/consola previas al re-pulsar (anti-saturación UI + modelo)
    setRows([]);
    setActivo({});
    setRestarCab({});
    setMsg(`3.1 · ${fid} · limpiando CI previos en CYMDIST y cruzando NIS…`);
    try {
      const j = await api<{
        ok?: boolean;
        error?: string;
        rows?: Json[];
        msg?: string;
        cymdist_refresh?: Json;
      }>("/api/clientes/tabla", {
        method: "POST",
        body: JSON.stringify({
          suministro_file: suministro,
          clientes_file: clientesFile,
          feeders: [fid],
          feeder: fid,
        }),
        timeoutMs: 180000,
      });
      if (!j.ok) throw new Error(j.error || "Error armar tabla");
      const list = j.rows || [];
      setRows(list);
      syncActivoFromRows(list);
      const ref = (j.cymdist_refresh as Json) || {};
      const nLib = Number(ref.n_liberados ?? 0);
      setMsg(
        (j.msg || `3.1 OK · Tabla cruzada: ${list.length} filas · ${fid} · todas Incluir`) +
          (nLib > 0 ? `\nCYMDIST: liberados ${nLib} SED previos (Unlocked/0)` : "")
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function saveIncluir(applyCymdist = false) {
    const fid = (feeder || "").trim();
    if (!hasCtx) {
      setMsg("Aplique 1.1 al contexto actual antes de guardar Incluir");
      return;
    }
    if (!fid) {
      setMsg("Defina el alimentador en §1.");
      return;
    }
    if (!rows.length) {
      setMsg("No hay tabla. Ejecute 3.1 primero.");
      return;
    }
    setBusy("incluir");
    setMsg(
      applyCymdist
        ? "Guardando Incluir y desconectando excluidas en CYMDIST…"
        : "Guardando selección Incluir…"
    );
    try {
      type SaveResult = {
        ok?: boolean;
        error?: string;
        msg?: string;
        rows?: Json[];
        n_activos?: number;
        n_excluidos?: number;
      };
      const payload = {
        feeder: fid,
        feeders: [fid],
        activo: activoMapFromUi(),
        restar_cabecera: restarCabMapFromUi(),
        apply_cymdist: applyCymdist,
        merge_inventory: false,
      };
      const j = applyCymdist
        ? (await runJob("clientes_activo_cymdist", payload)) as SaveResult
        : await api<SaveResult>("/api/clientes/activo", {
            method: "POST",
            body: JSON.stringify(payload),
            timeoutMs: 60000,
          });
      if (!j.ok) throw new Error(j.error || "Error guardar Incluir");
      if (j.rows?.length) {
        setRows(j.rows);
        syncActivoFromRows(j.rows);
      }
      setMsg(
        j.msg ||
          `Incluir OK · incluidas ${j.n_activos ?? nIncluidas} · excluidas ${j.n_excluidos ?? nExcluidas}`
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function applyClientes() {
    const fid = (feeder || "").trim();
    if (!hasCtx) {
      setMsg("Aplique 1.1 al contexto actual antes de cargar EA/Pot en CYMDIST");
      return;
    }
    if (!fid) {
      setMsg("Defina el alimentador en §1 antes de cargar EA/Pot.");
      return;
    }
    setBusy("3.2");
    setMsg(
      `3.2 · ${fid} · liberando CI previos y cargando EA/Pot · ${nIncluidas} incluidas · ${nExcluidas} se desconectan…`
    );
    try {
      // Job aislado: CymPy corre en proceso hijo (un crash de Cyme no tumba la API)
      // y el progreso llega por SSE; la GUI se reabre desde la API al terminar.
      const j = (await runJob(
        "clientes_aplicar",
        {
          suministro_file: suministro,
          clientes_file: clientesFile,
          feeders: [fid],
          feeder: fid,
          open_gui: true,
          rebuild: false,
          activo: activoMapFromUi(),
          restar_cabecera: restarCabMapFromUi(),
        },
        (job) => {
          const m = String(job.message || "");
          if (m) setMsg(`3.2 · ${m}`);
        }
      )) as {
        ok?: boolean;
        error?: string;
        msg?: string;
        ok_count?: number;
        excluido_count?: number;
        sin_sed_count?: number;
        warn_kwh_count?: number;
        kwh_verified?: number;
        n_liberados?: number;
        from_saved_table?: boolean;
        rows?: Json[];
        report?: Json[];
        P_kW?: number;
        Q_kvar?: number;
        P_kW_medicion?: number;
        P_kW_excluidas_restadas?: number;
        cabecera_ajustada?: Json;
        plantilla_distribucion?: { ok?: boolean; error?: string; errors?: string[] };
      };
      if (!j.ok) throw new Error(j.error || "Error aplicar");
      if (j.rows?.length) {
        setRows(j.rows);
        syncActivoFromRows(j.rows);
      }
      const rep = (j.report || [])
        .slice(0, 20)
        .map((r) => {
          const st = String(r.Estado || "");
          const sed = String(r.SED || "");
          const kwh = r.KWH_despues != null ? r.KWH_despues : "";
          return `${st} ${sed} KWH=${kwh}`;
        })
        .join("\n");
      const nLib = Number(j.n_liberados ?? 0);
      const tpl = j.plantilla_distribucion || {};
      const tplLine = tpl.ok
        ? "\nDistribución lista para 3.3: Consumo (kWh) · modelo y parámetros DEFAULT · demanda sin «Conectado»"
        : `\nAVISO plantilla de distribución: ${tpl.error || (tpl.errors || []).join("; ") || "no verificada"}`;
      setMsg(
        (j.msg ||
          `3.2 OK · EA→Consumo(KWH) ${j.ok_count} · excluidas ${j.excluido_count ?? 0} · sin SED ${j.sin_sed_count ?? 0} · KWH verificado ${j.kwh_verified ?? 0}`) +
          (nLib > 0 ? `\nLiberados previos: ${nLib} SED (anti-saturación)` : "") +
          (j.warn_kwh_count ? ` · WARN KWH ${j.warn_kwh_count}` : "") +
          (Number(j.P_kW_excluidas_restadas || 0) > 0 && j.P_kW != null
            ? `\n→ Cabecera lista para 3.3: P=${j.P_kW} kW` +
              (j.Q_kvar != null ? ` · Q=${j.Q_kvar} kvar` : "")
            : "") +
          tplLine +
          (rep ? `\n${rep}` : "")
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  /** 3.3b · Excel de verificación: lee el estudio guardado tras 3.3 (solo lectura). */
  async function downloadDistribution() {
    const fid = (feeder || "").trim();
    if (!hasCtx || !fid) {
      setMsg("Aplique 1.1 y ejecute 3.3 antes de descargar la distribución");
      return;
    }
    setBusy("3.3b");
    setMsg(`3.3b · ${fid} · leyendo cargas del estudio…`);
    try {
      const j = await runJob("distribucion_reporte", {}, (job) => {
        const m = String(job.message || "");
        if (m) setMsg(`3.3b · ${m}`);
      });
      if (!j.ok) throw new Error(String(j.error || "No se pudo generar el reporte"));
      const fileName = String(j.file_name || `distribucion_carga_${fid}.xlsx`);
      await downloadApiFile(
        `/api/clientes/distribucion/archivo?feeder=${encodeURIComponent(fid)}`,
        fileName
      );
      const s = (j.summary as Json) || {};
      setMsg(
        `3.3b OK · ${fileName} · ${s.n_cargas ?? "?"} cargas · ${s.n_clientes_importantes ?? 0} clientes importantes · ` +
          `${s.n_revisar ?? 0} a REVISAR · Σ cargas ${s.P_total_cargas_kW ?? "?"} kW vs cabecera ${s.P_cabecera_kW ?? "?"} kW`
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function runDistrib() {
    setBusy("3.3");
    const fid = (feeder || "").trim();
    setMsg(
      `3.3 · ${fid || "alimentador"} · desconectar no-Incluir + Restar cab. + módulo CYMDIST LoadAllocation…`
    );
    try {
      if (rows.length && fid) {
        await api("/api/clientes/activo", {
          method: "POST",
          body: JSON.stringify({
            feeder: fid,
            feeders: [fid],
            activo: activoMapFromUi(),
            restar_cabecera: restarCabMapFromUi(),
            apply_cymdist: false,
            merge_inventory: false,
          }),
          timeoutMs: 60000,
        });
      }
      const j = await runJob(
        "distribucion",
        {
          feeder: fid || undefined,
          activo: activoMapFromUi(),
          restar_cabecera: restarCabMapFromUi(),
        },
        (job) => {
          const m = String(job.message || "");
          if (m) setMsg(`3.3 · ${m}`);
        }
      );
      const res = (j.result as Json) || j;
      const timing = (res.timing as Json) || {};
      const val = (res.validation as Json) || {};
      const cleared = (res.residual_cleared as Json) || {};
      const cabAdj = (res.cabecera_ajustada as Json) || {};
      const fails = (val.fails as Json[] | undefined) || [];
      const failLines = fails
        .slice(0, 12)
        .map((r) => `${r.Estado} ${r.tipo} ${r.LoadID} kW=${r.kW} KWH=${r.KWH} · ${r.Detalle}`)
        .join("\n");
      const nFail = Number(val.n_fail ?? 0);
      const nWarn = Number(val.n_warn ?? 0);
      const status = String(res.status || "");
      const usedFallback = status.includes("fallback") || String(res.method || "").includes("fallback");
      const label =
        val.ok === false || nFail > 0
          ? nFail > 0
            ? "FAIL validación"
            : "con avisos"
          : usedFallback
            ? "OK (fallback KWH)"
            : nWarn > 0
              ? "OK con WARN"
              : "OK";
      const nCleared = Number(cleared.n_clear ?? 0);
      const disc = (res.excluidas_disconnected as Json) || {};
      const nDisc = Number(disc.n_ok ?? 0);
      const cabLine =
        Number(res.P_kW_excluidas_restadas || 0) > 0
          ? `\nCabecera: P_med=${res.P_kW_medicion ?? "?"} - Restar cab.=${res.P_kW_excluidas_restadas} -> P=${res.P_cabecera_kW} kW`
          : cabAdj.msg
            ? `\n${String(cabAdj.msg)}`
            : "";
      const discLine =
        nDisc > 0
          ? `\nDesconectadas en CYMDIST (Incluir off): ${nDisc} · ${String(disc.msg || "")}`
          : "";
      const scaleLine =
        res.aviso_fijos_vs_cabecera
          ? `\n${String(res.aviso_fijos_vs_cabecera)}`
          : "";
      setMsg(
        `3.3 ${label} · ${String(res.feeder_id || feeder || "")}` +
          ` · ${String(res.method || res.status || "")}` +
          ` · total ${String(timing.total_sec ?? "?")}s` +
          ` (Run ${String(timing.loadallocation_run_sec ?? "?")}s` +
          ` · locks ${String(timing.locks_sec ?? "?")}s` +
          ` · val ${String(timing.validation_sec ?? "?")}s` +
          ` · save ${String(timing.save_sec ?? "0")}s)` +
          (nCleared > 0
            ? `\nResidual previo limpiado: ${nCleared} SED → 0 kW (fijos intactos)`
            : "") +
          cabLine +
          discLine +
          scaleLine +
          `\n${String(val.msg || res.aviso || "")}` +
          ` · OK ${String(val.n_ok ?? 0)} · WARN ${String(val.n_warn ?? 0)} · FAIL ${String(val.n_fail ?? 0)}` +
          ` · ceros fijos ${String(val.n_zero_fixed ?? 0)} · ceros residual ${String(val.n_zero_residual ?? 0)}` +
          (val.balance_msg ? `\n${String(val.balance_msg)}` : "") +
          (failLines ? `\n${failLines}` : "")
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function runSituacional34() {
    setBusy("3.4");
    setMsg("3.4 · LoadFlow situacional + capturas nativas VoltageLevel/LoadingLevel…");
    try {
      const result = await runJob("flujo_situacional_34", {}, (job) => {
        if (job.message) setMsg(String(job.message));
      });
      const captures = (result.captures as Json[] | undefined) || [];
      setMsg(
        `3.4 ${result.ok ? "OK" : "FALLO"} · estado restaurado=${String(result.state_restored)}` +
          ` · capturas verificadas=${captures.filter((item) => item.ok).length}/2` +
          (result.saved_to ? `\nEvidencia: ${String(result.saved_to)}` : "")
      );
    } catch (error) {
      setMsg(String(error));
    } finally {
      setBusy("");
    }
  }

  /** 3.4b · Reportes CYMDIST (sin proyecto): misma seleccion RECYM_Informe de §5.1b, pero
   * sobre el estado situacional (sin la carga nueva de §4) · alimenta el informe. */
  async function runReportesInformeSinProyecto() {
    setBusy("3.4b");
    setMsg("3.4b · generando reportes CYMDIST (RECYM_Informe, sin proyecto)…");
    try {
      const j = await runJob(
        "reportes_informe",
        { scenario: "situacional" },
        (job) => setMsg(String(job.message || "3.4b"))
      );
      setMsg(
        j.ok
          ? `3.4b OK · ${String(j.xlsx_target || "")}`
          : `3.4b · ${String(j.error || "No se pudo confirmar el metodo de reportes")}` +
            (j.discovery ? `\nAPI encontrada: ${JSON.stringify(j.discovery, null, 2).slice(0, 2000)}` : "")
      );
    } catch (error) {
      setMsg(String(error));
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <h2>3 · Clientes importantes → SED + distribución</h2>
      <ContextBind hint="EA/Pot y distribución se escriben en CYMDIST sobre el estudio de §1" />
      <p className="muted">
        <b>3.1</b> cruzar NIS · <b>3.2</b> EA→Consumo(KWH) y Pot Locked ·{" "}
        <b>3.3</b> antes del módulo: desconecta en CYMDIST las no Incluir y resta Pot (Restar
        cab.) de P máx §1; luego ejecuta solo <b>Load Allocation</b> de CYMDIST. <b>3.4</b>{" "}
        genera el estado situacional con coloreo nativo de tensión y cargabilidad y restaura el estudio.
      </p>

      <div className="grid">
        <div>
          <label>suministrocliente</label>
          <select value={suministro} onChange={(e) => setSuministro(e.target.value)} disabled={Boolean(busy)}>
            <option value="">—</option>
            {(files.suministro || []).map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
        <div>
          <label>clientesimportantes</label>
          <select value={clientesFile} onChange={(e) => setClientesFile(e.target.value)} disabled={Boolean(busy)}>
            <option value="">—</option>
            {(files.clientesimportantes || []).map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="actions">
        <button type="button" {...btnProps("3.1")} disabled={Boolean(busy) || !hasCtx || !feeder} onClick={buildTable}>
          3.1 · Armar tabla (cruzar NIS)
        </button>
        <button
          type="button"
          {...btnProps("3.2", "secondary")}
          disabled={Boolean(busy) || !hasCtx || !feeder}
          onClick={applyClientes}
        >
          3.2 · Cargar EA/Pot en CYMDIST
        </button>
        <button type="button" {...btnProps("3.3")} disabled={Boolean(busy) || !hasCtx} onClick={runDistrib}>
          3.3 · Ejecutar módulo Load Allocation (CYMDIST)
        </button>
        <button type="button" {...btnProps("3.3b", "ghost")} disabled={Boolean(busy) || !hasCtx} onClick={downloadDistribution}
          title="Excel por SED: esperado vs actual en CYMDIST (clientes importantes y distribución por kWh)">
          3.3b · Descargar distribución (Excel)
        </button>
        <button type="button" {...btnProps("3.4", "secondary")} disabled={Boolean(busy) || !hasCtx} onClick={runSituacional34}>
          3.4 · Estado situacional + capturas nativas
        </button>
        <button type="button" {...btnProps("3.4b", "ghost")} disabled={Boolean(busy) || !hasCtx} onClick={runReportesInformeSinProyecto}
          title="Ejecuta la selección guardada en CYMDIST 'RECYM_Informe' (Barras/Cables/Cargas + Flujo de carga) sobre el estado situacional (sin la carga nueva de §4) y exporta a Excel">
          3.4b · Reportes CYMDIST (sin proyecto)
        </button>
        <button
          type="button"
          {...btnProps("files", "ghost")}
          onClick={() => {
            setBusy("files");
            loadFiles()
              .then(() => setMsg("Archivos actualizados"))
              .catch((e) => setMsg(String(e)))
              .finally(() => setBusy(""));
          }}
        >
          Actualizar archivos
        </button>
      </div>
      <pre className="out muted">{msg}</pre>

      <h3>Tabla cruzada (NIS)</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Incluidas: <b>{nIncluidas}</b> · Excluidas (se desconectan): <b>{nExcluidas}</b>
        {" · "}
        Restan cabecera: <b>{nRestanCab}</b>
        {" · "}
        {rows.length} filas
      </p>
      <p className="muted" style={{ marginTop: 0 }}>
        <b>Incluir</b> off = desconectar en CYMDIST. <b>Restar cab.</b> = además restar Pot de
        P(kW) máx §1 (carga que ya no pertenece al alimentador). Si solo olvidaron actualizar
        EA/Pot, desmarque Incluir y deje Restar cab. off.
      </p>
      <div className="actions">
        <button type="button" className="ghost" disabled={Boolean(busy) || !hasCtx || !rows.length} onClick={() => markAll(true)}>
          Marcar todas
        </button>
        <button type="button" className="ghost" disabled={Boolean(busy) || !hasCtx || !rows.length} onClick={() => markAll(false)}>
          Desmarcar todas
        </button>
        <button
          type="button"
          className="ghost"
          disabled={Boolean(busy) || !hasCtx || !rows.length}
          onClick={() => markAllRestar(true)}
        >
          Restar cab. todas
        </button>
        <button
          type="button"
          className="ghost"
          disabled={Boolean(busy) || !hasCtx || !rows.length}
          onClick={() => markAllRestar(false)}
        >
          Restar cab. ninguna
        </button>
        <button
          type="button"
          {...btnProps("incluir", "secondary")}
          disabled={Boolean(busy) || !hasCtx || !rows.length}
          onClick={() => saveIncluir(true)}
        >
          Guardar Incluir → desconectar en CYMDIST
        </button>
      </div>
      <div className="wrap">
        <table>
          <thead>
            <tr>
              <th title="Incluir: conectada con EA/Pot. Off = desconectar">Incluir</th>
              <th title="Si Incluir off: restar Pot de P máx §1. Off = solo desconectar">
                Restar cab.
              </th>
              <th>RADIAL</th>
              <th>Suministro</th>
              <th>Cliente</th>
              <th>SED</th>
              <th>EA</th>
              <th>Pot</th>
              <th>LoadID</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9}>
                  Sin filas. Pulse <b>3.1 · Armar tabla (cruzar NIS)</b> para el alimentador{" "}
                  <b>{feeder || "activo"}</b>.
                </td>
              </tr>
            )}
            {rows.slice(0, 200).map((r, i) => {
              const key = rowKey(r);
              const on = activo[key] !== false;
              const restar = restarCab[key] === true;
              return (
                <tr key={key || i} style={on ? undefined : { opacity: 0.55 }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={Boolean(busy)}
                      title={on ? "Incluida en modelo" : "Excluida → Disconnected en CYMDIST"}
                      onChange={(e) => setActivo({ ...activo, [key]: e.target.checked })}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      checked={restar}
                      disabled={Boolean(busy)}
                      title={
                        restar
                          ? "Al desmarcar Incluir: restar Pot de cabecera §1"
                          : "Solo desconectar; no tocar P(kW) máx §1"
                      }
                      onChange={(e) => setRestarCab({ ...restarCab, [key]: e.target.checked })}
                    />
                  </td>
                  <td>{String(r.RADIAL || "")}</td>
                  <td>{String(r.Suministro || "")}</td>
                  <td>{String(r.Cliente || "")}</td>
                  <td>{String(r.SED || "")}</td>
                  <td className="num">{String(r.EA ?? "")}</td>
                  <td className="num">{String(r.Pot ?? "")}</td>
                  <td>{String(r.LoadID_CYMDIST || "")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > 200 && (
        <p className="muted">Mostrando 200 / {rows.length} filas.</p>
      )}
    </section>
  );
}
