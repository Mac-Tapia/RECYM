import { useCallback, useEffect, useMemo, useState } from "react";
import { api, runJob, type Json } from "../api/client";
import { useFeeder } from "../state/feeder";

type DiagSnap = {
  total_messages?: number;
  n_problems?: number;
  by_code?: Record<string, number>;
  top_errors?: Json[];
  timestamp?: string;
  empty?: boolean;
  phase?: string;
};

type Board = {
  ok?: boolean;
  error?: string;
  feeder_id?: string;
  utility?: string;
  generated_at?: string;
  refreshed_at?: string;
  has_diagnostic?: boolean;
  diag_refresh?: Json;
  before?: DiagSnap;
  after?: DiagSnap;
  voltage_opt?: Json;
  clientes?: {
    n?: number;
    n_activos?: number;
    n_excluidos?: number;
    rows?: Json[];
    meta?: Json;
  };
};

function truthy(v: unknown) {
  return v === true || v === "True" || v === "true" || v === "1" || v === 1;
}

/** Snapshot en cero — el tablero no debe arrastrar diagnósticos viejos. */
function emptyDiag(phase = "empty"): DiagSnap {
  return {
    empty: true,
    total_messages: 0,
    n_problems: 0,
    by_code: {},
    top_errors: [],
    phase,
    timestamp: undefined,
  };
}

function wipeBoardDiag(prev: Board | null): Board {
  return {
    ...(prev || {}),
    ok: true,
    has_diagnostic: false,
    refreshed_at: undefined,
    generated_at: undefined,
    before: emptyDiag("before"),
    after: emptyDiag("after"),
    clientes: prev?.clientes,
  };
}

/** Normaliza el summary del job 2.1 → snapshot de tablero (códigos + muestra). */
function snapFromDiag(raw: unknown, phase: string): DiagSnap {
  const s = (raw && typeof raw === "object" ? (raw as DiagSnap & Json) : {}) as DiagSnap & {
    rows?: Json[];
  };
  let top = Array.isArray(s.top_errors) ? s.top_errors : [];
  if (!top.length && Array.isArray(s.rows)) {
    top = s.rows.slice(0, 40).map((r) => ({
      Codigo: r.Codigo,
      Tipo: r.Tipo,
      ID_CYMDIST: r.ID_CYMDIST,
      Severidad: r.Severidad,
      Mensaje: String(r.Mensaje || "").slice(0, 180),
    }));
  }
  const byCode =
    s.by_code && typeof s.by_code === "object"
      ? (s.by_code as Record<string, number>)
      : {};
  return {
    empty: false,
    phase,
    total_messages: Number(s.total_messages ?? top.length ?? 0),
    n_problems: Number(s.n_problems ?? 0),
    by_code: byCode,
    top_errors: top,
    timestamp: s.timestamp ? String(s.timestamp) : undefined,
  };
}

function applyDiagResult(prev: Board | null, result: Json): Board {
  const tab = (result.tablero as Json) || null;
  const summary =
    (result.summary as Json) ||
    (tab?.before as Json) ||
    null;
  const before = snapFromDiag(tab?.before || summary, "before");
  const after = snapFromDiag(tab?.after || summary || before, "after");
  return {
    ...(prev || {}),
    ok: true,
    has_diagnostic: true,
    error: undefined,
    refreshed_at: new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 15),
    generated_at: new Date().toISOString(),
    before,
    after,
    voltage_opt: (result.voltage_opt as Json) || (tab?.voltage_opt as Json) || (summary as Json)?.voltage_opt,
    clientes: prev?.clientes,
  };
}

export function Step2CalidadTablero() {
  const { feeder } = useFeeder();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [gate, setGate] = useState<Json | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [activo, setActivo] = useState<Record<string, boolean>>({});

  const refreshGate = useCallback(async () => {
    const j = await api<Json>("/api/calidad/estado");
    setGate(j);
  }, []);

  const refreshBoard = useCallback(async (rebuild = 0, refreshDiag = false, clear = false, seedLoads = false) => {
    const bust = Date.now();
    const parts = [`_=${bust}`];
    if (clear) parts.push("clear=1");
    if (seedLoads && !clear) parts.push("seed_loads=1");
    if (rebuild > 0 && !clear) parts.push("rebuild=1");
    if (refreshDiag && !clear) parts.push("refresh_diag=1");
    const j = await api<Board>(`/api/tablero?${parts.join("&")}`, {
      timeoutMs: refreshDiag || seedLoads ? 300000 : 120000,
    });
    if (!j.ok && j.error) throw new Error(String(j.error));
    setBoard({ ...j });
    const map: Record<string, boolean> = {};
    for (const r of j.clientes?.rows || []) {
      const key = `${String(r.Suministro || "").trim()}|${String(r.SED || "").trim()}`;
      map[key] = truthy(r.Activo ?? true);
    }
    setActivo(map);
    return j;
  }, []);

  useEffect(() => {
    if (!feeder) return;
    // Al cambiar alimentador: vaciar UI y regenerar desde inventario de ESE radial
    setBoard({
      ok: true,
      has_diagnostic: false,
      before: emptyDiag("before"),
      after: emptyDiag("after"),
      clientes: { n: 0, n_activos: 0, n_excluidos: 0, rows: [] },
    });
    setActivo({});
    refreshGate().catch((e) => setMsg(String(e)));
    refreshBoard(1, false, false, true).catch((e) => setMsg(String(e)));
  }, [feeder, refreshGate, refreshBoard]);

  async function job(action: string, label: string, payload: Json = {}) {
    setBusy(label);
    setMsg(`${label}…`);
    // Solo 2.1 vacía y luego rellena las tablas del tablero con el diagnóstico nuevo
    const isDiag21 = action === "calidad_diagnosticar";
    if (isDiag21) {
      setBoard((prev) => wipeBoardDiag(prev));
      setMsg("2.1 · Diagnosticando… el tablero se actualizará al terminar");
    }
    try {
      const result = await runJob(action, payload, (j) => {
        setMsg(String(j.message || label));
      });

      if (isDiag21) {
        // 1) Pintar al instante códigos / muestra / totales desde el job
        setBoard((prev) => applyDiagResult(prev, result));
        const n = Number(
          (result?.tablero as Json)?.total_messages ??
            (result?.summary as Json)?.total_messages ??
            0
        );
        setMsg(
          String(result?.msg || "") ||
            `Diagnóstico listo · ${n} msgs · tablero actualizado`
        );
        await refreshGate();
        // 2) Releer tablero.json regenerado (tablas definitivas en disco)
        try {
          const j = await refreshBoard(1, false, false);
          const vopt = (result?.voltage_opt as Json) || (result?.tablero as Json)?.voltage_opt;
          if (vopt) {
            setBoard((prev) => ({ ...(prev || j || {}), ...(j || {}), voltage_opt: vopt }));
          }
          if (j?.before?.empty !== true) {
            const recMsg = vopt && (vopt as Json).triggered
              ? `\n${String((vopt as Json).msg || "")}`
              : "";
            setMsg(
              `2.1 OK · antes=${j?.before?.total_messages ?? n} · después=${j?.after?.total_messages ?? n} · tablas actualizadas${recMsg}`
            );
          } else {
            // Disco vacío pero job trajo datos → mantener snapshot del job
            setBoard((prev) => applyDiagResult(prev, result));
          }
        } catch {
          setBoard((prev) => applyDiagResult(prev, result));
        }
      } else if (action === "calidad_convergencia") {
        const conv = String(result?.converge || "—").toUpperCase();
        const line =
          String(result?.msg || "") ||
          (conv === "SI"
            ? `2.4 · Converge = SI · ${feeder || result?.feeder_id || ""}`
            : `2.4 · Converge = ${conv} · ${String(result?.error || "")}`);
        setMsg(line);
        await refreshGate();
        await refreshBoard(1, false, false);
      } else {
        // Otras acciones calidad: no borrar tablas de 2.1; solo refrescar gate/msg
        const tab = (result?.tablero as Json) || null;
        const summary = (result?.summary as Json) || null;
        if (tab || summary) {
          setBoard((prev) => applyDiagResult(prev, result));
        }
        setMsg(
          String(result?.msg || "") ||
            JSON.stringify(result, null, 2).slice(0, 1500)
        );
        await refreshGate();
        await refreshBoard(1, false, false);
      }
    } catch (e) {
      const text = String(e);
      setMsg(text.startsWith("Error: ") ? text : `Error: ${text}`);
      if (isDiag21) {
        setBoard((prev) => wipeBoardDiag(prev));
      }
    } finally {
      setBusy("");
    }
  }

  async function runLocal(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setMsg(`${label}…`);
    try {
      await fn();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  async function saveActivo() {
    setBusy("guardar");
    try {
      // Mapa desde filas visibles (no solo keys previas de activo)
      const map: Record<string, boolean> = {};
      for (const r of rows) {
        const key = rowKey(r);
        map[key] = activo[key] !== false;
      }
      const j = await api<{
        ok?: boolean;
        error?: string;
        n_activos?: number;
        n_excluidos?: number;
        n?: number;
        rows?: Json[];
        msg?: string;
      }>("/api/clientes/activo", {
        method: "POST",
        body: JSON.stringify({
          activo: map,
          apply_cymdist: true,
          draw: true,
        }),
        timeoutMs: 180000,
      });
      if (!j.ok) throw new Error(j.error || "Error");
      if (j.rows?.length) {
        const next: Record<string, boolean> = {};
        for (const r of j.rows) {
          next[rowKey(r)] = truthy(r.Activo ?? true);
        }
        setActivo(next);
      }
      setMsg(
        j.msg ||
          `Guardado · incluidas ${j.n_activos || 0} · excluidas ${j.n_excluidos || 0} · dibujadas en CYMDIST`
      );
      await refreshBoard(1, false);
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  function rowKey(r: Json) {
    return `${String(r.Suministro || "").trim()}|${String(r.SED || "").trim()}`;
  }

  function markAll(on: boolean) {
    const next: Record<string, boolean> = {};
    for (const r of rows) {
      next[rowKey(r)] = on;
    }
    if (!rows.length) {
      Object.keys(activo).forEach((k) => {
        next[k] = on;
      });
    }
    setActivo(next);
  }

  /** Solo el botón activo se marca .running; los demás se bloquean sin parecer en ejecución. */
  function btnProps(id: string, kind: "secondary" | "ghost" = "ghost") {
    const active = busy === id;
    return {
      className: `${kind}${active ? " running" : ""}`,
      disabled: Boolean(busy),
      "aria-busy": active,
    } as const;
  }

  const before = board?.before || emptyDiag("before");
  const after = board?.after || emptyDiag("after");
  // Hay diagnóstico si empty !== true (2.1 escribió datos) o has_diagnostic
  const hasDiag =
    board?.has_diagnostic === true ||
    before.empty === false ||
    (before.empty !== true &&
      ((before.total_messages || 0) > 0 ||
        Object.keys(before.by_code || {}).length > 0 ||
        (before.top_errors || []).length > 0));
  // Si explícitamente vacío (clear / regenerar), forzar sin diag
  const showDiag = before.empty === true ? false : hasDiag;
  const codes = useMemo(() => {
    if (!showDiag) return [] as string[];
    const keys = new Set([
      ...Object.keys(before.by_code || {}),
      ...Object.keys(after.by_code || {}),
    ]);
    return Array.from(keys).sort();
  }, [before, after, showDiag]);

  const top = showDiag
    ? (after.top_errors || before.top_errors || []).slice(0, 30)
    : [];
  const rows = board?.clientes?.rows || [];
  const ready = Boolean(gate?.ready);
  const nIncluidas = rows.filter((r) => activo[rowKey(r)] !== false).length;
  const vopt = (board?.voltage_opt || {}) as Json;
  const voptTriggered = Boolean(vopt.triggered);
  const voptRecs = (Array.isArray(vopt.recommendations) ? vopt.recommendations : []) as Json[];

  async function runOptFromRec(rec: Json) {
    const action = String(rec.action || "");
    const step = String(rec.step || "");
    if (!action) return;
    const label = `${step} · ${String(rec.title || action)}`;
    setBusy(label);
    setMsg(`${label} · ejecutando módulo CYMDIST (equipo ${String(rec.equipment_id || "")})…`);
    try {
      const j = await api<Json>(`/api/optimizacion/${action}`, {
        method: "POST",
        body: JSON.stringify({ force: true }),
        timeoutMs: 600000,
      });
      setMsg(
        `${label}: ${String(j.msg || (j.ok ? "OK" : j.error) || "")}` +
          (j.equipment_id ? ` · equipo ${j.equipment_id}` : "") +
          (j.resolved_module ? ` · módulo ${j.resolved_module}` : "")
      );
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <section className="panel">
        <h2>2 · Calidad del modelo + Tablero</h2>
        <p className="muted">
          NetworkDiagnostic (códigos 220000–220053). Gate antes de §3. Cada botón ejecuta solo su acción.
        </p>
        <div className="hdr-bar">
          <span className={"badge" + (ready ? " ready" : "")}>
            {ready ? "Gate LISTO" : "Gate pendiente"}
          </span>
          <span className="muted">{feeder || "sin alimentador"}</span>
          <span
            className={
              "badge" +
              (String(gate?.converge || "").toUpperCase() === "SI" ? " ready" : "")
            }
            title="Resultado de 2.4 · Verificar convergencia"
          >
            Converge: {String(gate?.converge || "—")}
          </span>
        </div>
        <div className="actions">
          <button type="button" {...btnProps("2.1", "secondary")}
            onClick={() => job("calidad_diagnosticar", "2.1")}>2.1 · Diagnosticar</button>
          <button type="button" {...btnProps("2.2")}
            onClick={() => job("calidad_proponer", "2.2")}>2.2 · Proponer</button>
          <button type="button" {...btnProps("2.3", "secondary")}
            onClick={() => job("calidad_aplicar", "2.3")}>2.3 · Aplicar</button>
          <button type="button" {...btnProps("2.4")}
            onClick={() => job("calidad_convergencia", "2.4")}>2.4 · Verificar convergencia</button>
          <button type="button" {...btnProps("2.5")}
            onClick={() =>
              runLocal("2.5", async () => {
                await refreshGate();
                setMsg("Estado actualizado");
              })
            }>2.5 · Actualizar estado</button>
          <button type="button" {...btnProps("2.6")}
            onClick={() => job("calidad_hasta_limpio", "2.6", { max_iters: 4 })}>2.6 · Corregir hasta limpio</button>
          <button type="button" {...btnProps("2.7", "secondary")}
            onClick={() => job("calidad_sistema", "2.7")}>2.7 · Diagnosticar sistema (96)</button>
          <button type="button" {...btnProps("2.8", "secondary")}
            onClick={() => job("calidad_eld", "2.8")}>2.8 · Diagnosticar ELD</button>
        </div>
        <pre className="out muted">{msg}</pre>
        {voptTriggered && (
          <div className="panel" style={{ marginTop: 12, borderLeft: "3px solid #0f766e" }}>
            <h3 style={{ marginTop: 0 }}>Recomendación ante caídas de tensión</h3>
            <p className="muted" style={{ marginTop: 0 }}>
              {String(vopt.msg || "")}
              {" · "}Problemas de tensión: <b>{String(vopt.n_voltage_issues ?? 0)}</b>
              {" "}(umbral {String(vopt.threshold ?? 3)}). Orden: primero capacitores, luego reguladores.
              Usa equipos ya creados en CYMDIST y sus módulos de ubicación óptima.
            </p>
            <div className="actions">
              {voptRecs.map((rec) => (
                <button
                  key={String(rec.step || rec.action)}
                  type="button"
                  className="secondary"
                  disabled={Boolean(busy)}
                  title={String(rec.reason || "")}
                  onClick={() => runOptFromRec(rec)}
                >
                  {String(rec.priority || "")}. {String(rec.step)} · {String(rec.title || rec.action)}
                  {rec.equipment_id ? ` (${String(rec.equipment_id)})` : ""}
                </button>
              ))}
              <a className="ghost" href="/7" style={{ alignSelf: "center" }}>
                Ir a §7 Opt
              </a>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Tablero dinámico</h2>
        <div className="actions">
          <button type="button" {...btnProps("tablero")}
            onClick={() =>
              runLocal("tablero", async () => {
                setBoard((prev) => wipeBoardDiag(prev));
                setMsg("Vaciando tablero…");
                await refreshBoard(0, false, true);
                setMsg("Tablero en cero · ejecute 2.1 · Diagnosticar para llenar códigos/errores");
              })
            }>
            Regenerar tablero
          </button>
        </div>
        {board?.error && <p className="bad">{board.error}</p>}
        <p className="muted" style={{ marginTop: 4 }}>
          {!showDiag
            ? "Sin diagnóstico — valores en 0. Pulse 2.1 · Diagnosticar para cargar códigos y muestra de errores en las tablas."
            : `Actualizado: ${board?.refreshed_at || board?.generated_at || before.timestamp || after.timestamp || "—"}`}
          {showDiag && (after.timestamp || before.timestamp)
            ? ` · diag: ${after.timestamp || before.timestamp}`
            : ""}
        </p>
        <div className="cards">
          <div className="card">Errores antes<b className={showDiag ? "bad" : ""}>{showDiag ? (before.total_messages ?? 0) : 0}</b></div>
          <div className="card">Errores después<b>{showDiag ? (after.total_messages ?? 0) : 0}</b></div>
          <div className="card">220052 antes<b>{showDiag ? (before.by_code?.["220052"] ?? 0) : 0}</b></div>
          <div className="card">220052 después<b>{showDiag ? (after.by_code?.["220052"] ?? 0) : 0}</b></div>
          <div className="card">220047 antes<b>{showDiag ? (before.by_code?.["220047"] ?? 0) : 0}</b></div>
          <div className="card">220047 después<b>{showDiag ? (after.by_code?.["220047"] ?? 0) : 0}</b></div>
          <div className="card">Incluidas<b>{nIncluidas}</b></div>
        </div>

        <h3>Códigos (antes / después)</h3>
        <div className="wrap">
          <table>
            <thead>
              <tr><th>Código</th><th>Antes</th><th>Después</th></tr>
            </thead>
            <tbody>
              {codes.length === 0 && (
                <tr><td colSpan={3}>Sin datos de diagnóstico</td></tr>
              )}
              {codes.map((c) => (
                <tr key={c}>
                  <td>{c}</td>
                  <td>{before.by_code?.[c] ?? 0}</td>
                  <td>{after.by_code?.[c] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Muestra de errores</h3>
        <div className="wrap">
          <table>
            <thead>
              <tr><th>Código</th><th>Tipo</th><th>ID</th><th>Mensaje</th></tr>
            </thead>
            <tbody>
              {top.length === 0 && (
                <tr><td colSpan={4}>Sin errores</td></tr>
              )}
              {top.map((e, i) => (
                <tr key={i}>
                  <td>{String(e.Codigo || "")}</td>
                  <td>{String(e.Tipo || "")}</td>
                  <td>{String(e.ID_CYMDIST || "")}</td>
                  <td>{String(e.Mensaje || "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3>Clientes · Incluir</h3>
        <p className="muted">
          Capacidad SED (aviso 260044) <b>no limita</b> Incluir. Las SpotLoad del
          alimentador activo (<b>{feeder || "—"}</b>) aparecen aquí; al guardar se
          conectan y se dibujan en CYMDIST.
          {" · "}Incluidas: <b>{nIncluidas}</b> / {rows.length}
        </p>
        <div className="actions">
          <button type="button" className="ghost" disabled={!!busy || !rows.length}
            onClick={() => markAll(true)}>Marcar todas</button>
          <button type="button" className="ghost" disabled={!!busy || !rows.length}
            onClick={() => markAll(false)}>Desmarcar todas</button>
          <button type="button" {...btnProps("guardar", "secondary")} onClick={saveActivo}>
            Guardar selección Incluir
          </button>
          <button type="button" className="ghost" disabled={!!busy || !feeder}
            onClick={() =>
              runLocal("seed", async () => {
                const j = await refreshBoard(1, false, false, true);
                const n = j?.clientes?.n ?? j?.clientes?.rows?.length ?? 0;
                setMsg(
                  n
                    ? `SpotLoads de ${feeder}: ${n} filas (inventario del modelo)`
                    : `Sin SpotLoad en inventario de ${feeder}. Genere inventario o verifique el estudio.`
                );
              })
            }>
            Cargar SpotLoads del modelo
          </button>
        </div>
        <div className="wrap">
          <table>
            <thead>
              <tr>
                <th>Incluir</th><th>RADIAL</th><th>Suministro</th><th>Cliente</th>
                <th>SED</th><th>EA</th><th>Pot</th><th>LoadID</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    Sin filas para <b>{feeder || "este alimentador"}</b>. Pulse{" "}
                    <b>Cargar SpotLoads del modelo</b> o arme la tabla en §3.
                  </td>
                </tr>
              )}
              {rows.map((r) => {
                const key = rowKey(r);
                const on = activo[key] !== false;
                return (
                  <tr key={key + String(r.LoadID_CYMDIST || "")} className={on ? "" : "off"}>
                    <td>
                      <input
                        type="checkbox"
                        checked={on}
                        disabled={!!busy}
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
      </section>
    </>
  );
}
