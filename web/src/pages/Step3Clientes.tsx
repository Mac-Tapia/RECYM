import { useEffect, useState } from "react";
import { api, runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";

type ActionId = "" | "3.1" | "3.2" | "3.3" | "files" | "incluir";

function truthy(v: unknown) {
  return v === true || v === "True" || v === "true" || v === "1" || v === 1;
}

function rowKey(r: Json) {
  return `${String(r.Suministro || "").trim()}|${String(r.SED || "").trim()}`;
}

export function Step3Clientes() {
  const { feeder } = useFeeder();
  const [suministro, setSuministro] = useState("");
  const [clientesFile, setClientesFile] = useState("");
  const [files, setFiles] = useState<{ suministro?: string[]; clientesimportantes?: string[] }>({});
  const [rows, setRows] = useState<Json[]>([]);
  const [activo, setActivo] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState<ActionId>("");

  /** Solo el botón activo se marca .running; los demás se bloquean sin parecer en ejecución. */
  function btnProps(id: ActionId, kind: "secondary" | "ghost" | "" = "") {
    const active = busy === id;
    return {
      className: `${kind}${active ? " running" : ""}`.trim(),
      disabled: Boolean(busy),
      "aria-busy": active,
    } as const;
  }

  function syncActivoFromRows(list: Json[]) {
    const map: Record<string, boolean> = {};
    for (const r of list) {
      map[rowKey(r)] = truthy(r.Activo ?? true);
    }
    setActivo(map);
  }

  function markAll(on: boolean) {
    const next: Record<string, boolean> = {};
    for (const r of rows) next[rowKey(r)] = on;
    setActivo(next);
  }

  function activoMapFromUi() {
    const map: Record<string, boolean> = {};
    for (const r of rows) {
      const key = rowKey(r);
      map[key] = activo[key] !== false;
    }
    return map;
  }

  const nIncluidas = rows.filter((r) => activo[rowKey(r)] !== false).length;
  const nExcluidas = rows.length - nIncluidas;

  async function loadFiles() {
    const j = await api<{ ok?: boolean; suministro?: string[]; clientesimportantes?: string[] }>(
      "/api/clientes/archivos"
    );
    setFiles(j);
    if (!suministro && j.suministro?.[0]) setSuministro(j.suministro[0]);
    if (!clientesFile && j.clientesimportantes?.[0]) setClientesFile(j.clientesimportantes[0]);
  }

  useEffect(() => {
    loadFiles().catch((e) => setMsg(String(e)));
  }, []);

  async function buildTable() {
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
      const j = await api<{
        ok?: boolean;
        error?: string;
        msg?: string;
        rows?: Json[];
        n_activos?: number;
        n_excluidos?: number;
      }>("/api/clientes/activo", {
        method: "POST",
        body: JSON.stringify({
          feeder: fid,
          feeders: [fid],
          activo: activoMapFromUi(),
          apply_cymdist: applyCymdist,
          merge_inventory: false,
        }),
        timeoutMs: applyCymdist ? 300000 : 60000,
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
    if (!fid) {
      setMsg("Defina el alimentador en §1 antes de cargar EA/Pot.");
      return;
    }
    setBusy("3.2");
    setMsg(
      `3.2 · ${fid} · liberando CI previos y cargando EA/Pot · ${nIncluidas} incluidas · ${nExcluidas} se desconectan…`
    );
    try {
      const j = await api<{
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
      }>("/api/clientes/aplicar", {
        method: "POST",
        body: JSON.stringify({
          suministro_file: suministro,
          clientes_file: clientesFile,
          feeders: [fid],
          feeder: fid,
          open_gui: true,
          rebuild: false,
          activo: activoMapFromUi(),
        }),
        timeoutMs: 300000,
      });
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
      setMsg(
        (j.msg ||
          `3.2 OK · EA→Consumo(KWH) ${j.ok_count} · excluidas ${j.excluido_count ?? 0} · sin SED ${j.sin_sed_count ?? 0} · KWH verificado ${j.kwh_verified ?? 0}`) +
          (nLib > 0 ? `\nLiberados previos: ${nLib} SED (anti-saturación)` : "") +
          (j.warn_kwh_count ? ` · WARN KWH ${j.warn_kwh_count}` : "") +
          (rep ? `\n${rep}` : "")
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
    // Limpiar consola previa al re-pulsar (evita mezclar resultados viejos)
    setMsg(
      `3.3 · ${fid || "alimentador"} · limpiando residual previo y redistribuyendo…`
    );
    try {
      const j = await runJob("distribucion", { feeder: fid || undefined }, (job) => {
        const m = String(job.message || "");
        if (m) setMsg(`3.3 · ${m}`);
      });
      const res = (j.result as Json) || j;
      const timing = (res.timing as Json) || {};
      const val = (res.validation as Json) || {};
      const cleared = (res.residual_cleared as Json) || {};
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

  return (
    <section className="panel">
      <h2>3 · Clientes importantes → SED + distribución</h2>
      <p className="muted">
        <b>3.1</b> cruzar NIS (libera CI previos fuera de tabla) ·{" "}
        <b>3.2</b> EA→Consumo(KWH) y Pot Locked (actualiza/sobrescribe) ·{" "}
        <b>3.3</b> = <b>API CYMDIST</b> (limpia residual y redistribuye) sobre el
        alimentador de §1: su estudio (<code>.zxst</code>) + BD del proyecto (
        <b>20260919</b>). No fijo a PA217.
        {" · "}Alimentador: <b>{feeder || "— (configure §1)"}</b>
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
        <button type="button" {...btnProps("3.1")} disabled={Boolean(busy) || !feeder} onClick={buildTable}>
          3.1 · Armar tabla (cruzar NIS)
        </button>
        <button
          type="button"
          {...btnProps("3.2", "secondary")}
          disabled={Boolean(busy) || !feeder}
          onClick={applyClientes}
        >
          3.2 · Cargar EA/Pot en CYMDIST
        </button>
        <button type="button" {...btnProps("3.3")} disabled={Boolean(busy)} onClick={runDistrib}>
          3.3 · Ejecutar distribución de carga
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
        {rows.length} filas
      </p>
      <div className="actions">
        <button type="button" className="ghost" disabled={Boolean(busy) || !rows.length} onClick={() => markAll(true)}>
          Marcar todas
        </button>
        <button type="button" className="ghost" disabled={Boolean(busy) || !rows.length} onClick={() => markAll(false)}>
          Desmarcar todas
        </button>
        <button
          type="button"
          {...btnProps("incluir", "secondary")}
          disabled={Boolean(busy) || !rows.length}
          onClick={() => saveIncluir(true)}
        >
          Guardar Incluir → desconectar en CYMDIST
        </button>
      </div>
      <div className="wrap">
        <table>
          <thead>
            <tr>
              <th>Incluir</th>
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
                <td colSpan={8}>
                  Sin filas. Pulse <b>3.1 · Armar tabla (cruzar NIS)</b> para el alimentador{" "}
                  <b>{feeder || "activo"}</b>.
                </td>
              </tr>
            )}
            {rows.slice(0, 200).map((r, i) => {
              const key = rowKey(r);
              const on = activo[key] !== false;
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
