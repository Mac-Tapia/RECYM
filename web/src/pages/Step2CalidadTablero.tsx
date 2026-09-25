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

/** Resultado 2.7 / 2.8 — no alimenta el tablero por feeder. */
type SystemDiag = {
  scope?: string;
  label?: string;
  n_problems?: number;
  n_errors?: number;
  n_warnings?: number;
  n_hints?: number;
  n_networks_ok?: number;
  n_networks_fail?: number;
  n_networks_requested?: number;
  by_code?: Record<string, number>;
  per_feeder?: Json[];
  top_errors?: Json[];
  errors_by_net?: Record<string, unknown>;
  csv?: string;
  json?: string;
  timestamp?: string;
  ready?: boolean;
};

function systemDiagFromResult(result: Json): SystemDiag | null {
  const sd = result?.system_diag;
  if (sd && typeof sd === "object") {
    const raw = sd as SystemDiag & { per_feeder?: unknown };
    return {
      ...raw,
      per_feeder: normalizePerFeeder(raw.per_feeder),
    };
  }
  const summary = result?.summary;
  if (!summary || typeof summary !== "object") return null;
  const s = summary as SystemDiag & Json;
  return {
    scope: String(s.scope || ""),
    label: String(result?.msg || "").slice(0, 40),
    n_problems: Number(s.n_problems ?? 0),
    n_errors: Number(s.n_errors ?? 0),
    n_warnings: Number(s.n_warnings ?? 0),
    n_hints: Number(s.n_hints ?? 0),
    n_networks_ok: Number(s.n_networks_ok ?? 0),
    n_networks_fail: Number(s.n_networks_fail ?? 0),
    n_networks_requested: Number(
      s.n_networks_requested ?? s.n_networks_loaded ?? 0
    ),
    by_code: (s.by_code as Record<string, number>) || {},
    per_feeder: normalizePerFeeder(s.per_feeder),
    top_errors: Array.isArray(s.top_errors) ? s.top_errors : [],
    errors_by_net: (s.errors_by_net as Record<string, unknown>) || {},
    csv: s.csv ? String(s.csv) : undefined,
    json: s.json ? String(s.json) : undefined,
    timestamp: s.timestamp ? String(s.timestamp) : undefined,
    ready: Boolean(s.ready_model_system ?? s.ready_model_eld ?? s.ready),
  };
}

/** per_feeder llega como dict {id: info} o lista. */
function normalizePerFeeder(raw: unknown): Json[] {
  if (Array.isArray(raw)) return raw as Json[];
  if (raw && typeof raw === "object") {
    return Object.entries(raw as Record<string, Json>)
      .map(([fid, info]) => ({
        ...(typeof info === "object" && info ? info : {}),
        feeder_id: fid,
      }))
      .sort(
        (a, b) =>
          Number((b as Json).n_problems || 0) - Number((a as Json).n_problems || 0)
      );
  }
  return [];
}

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
  const { feeder, network, studyPath, databaseMdb, setContext } = useFeeder();
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const [gate, setGate] = useState<Json | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [systemDiag, setSystemDiag] = useState<SystemDiag | null>(null);
  const [activo, setActivo] = useState<Record<string, boolean>>({});

  const studyFile = (studyPath || "").split(/[/\\]/).pop() || "";
  const dbFile = (databaseMdb || "").split(/[/\\]/).pop() || "";
  const hasCtx = Boolean(feeder && (studyPath || databaseMdb));

  const refreshGate = useCallback(async () => {
    const j = await api<Json>("/api/calidad/estado");
    setGate(j);
    // Hidratar contexto §1 desde servidor si la SPA aún no lo tiene
    if (
      (!feeder || !studyPath || !databaseMdb) &&
      (j?.feeder_id || j?.study_path || j?.ui_study_path || j?.database_mdb)
    ) {
      setContext({
        feeder: String(j.feeder_id || feeder || ""),
        network: String(j.network_id || network || ""),
        studyPath: String(j.ui_study_path || j.study_path || studyPath || ""),
        databaseMdb: String(j.database_mdb || databaseMdb || ""),
      });
    }
    return j;
  }, [feeder, network, studyPath, databaseMdb, setContext]);

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
    setBoard((prev) => {
      // No pisar diagnóstico fresco del job 2.1 si el disco aún aparece vacío
      if (
        !clear &&
        j.before?.empty === true &&
        prev?.has_diagnostic &&
        prev?.before &&
        prev.before.empty !== true
      ) {
        return {
          ...j,
          before: prev.before,
          after: prev.after || prev.before,
          has_diagnostic: true,
          voltage_opt: prev.voltage_opt || j.voltage_opt,
        };
      }
      return { ...j };
    });
    const map: Record<string, boolean> = {};
    for (const r of j.clientes?.rows || []) {
      const key = `${String(r.Suministro || "").trim()}|${String(r.SED || "").trim()}`;
      map[key] = truthy(r.Activo ?? true);
    }
    setActivo(map);
    return j;
  }, []);

  useEffect(() => {
    // Al entrar a §2: sincronizar BD/estudio del §1 y tablero de ese alimentador
    (async () => {
      try {
        const j = await api<{
          ok?: boolean;
          current_feeder?: string;
          current_network?: string;
          current_study?: string;
          current_database?: string;
        }>("/api/contexto/archivos", { timeoutMs: 30000 });
        if (j?.ok) {
          setContext({
            feeder: j.current_feeder || feeder || "",
            network: j.current_network || "",
            studyPath: j.current_study || studyPath || "",
            databaseMdb: j.current_database || databaseMdb || "",
          });
        }
      } catch {
        /* gate/tablero abajo */
      }
    })();
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
    if (!hasCtx) {
      setMsg("Elija BD + estudio en §1 y pulse 1.1 Aplicar antes de §2.");
      return;
    }
    setBusy(label);
    setMsg(
      `${label} · ${feeder || "?"} · estudio ${studyFile || "—"} · BD ${dbFile || "—"}…`
    );
    // Solo 2.1 vacía y luego rellena las tablas del tablero con el diagnóstico nuevo
    const isDiag21 = action === "calidad_diagnosticar";
    if (isDiag21) {
      setBoard((prev) => wipeBoardDiag(prev));
      setMsg(
        `2.1 · Diagnosticando ${feeder} · estudio ${studyFile} (CYMDIST)…`
      );
    }
    try {
      const result = await runJob(
        action,
        {
          ...payload,
          feeder: feeder || undefined,
          feeder_id: feeder || undefined,
          network_id: network || undefined,
          study_path: studyPath || undefined,
          database_mdb: databaseMdb || undefined,
        },
        (j) => {
          setMsg(String(j.message || label));
        }
      );

      if (isDiag21) {
        // 1) Pintar al instante códigos / muestra / totales desde el job
        setBoard((prev) => applyDiagResult(prev, result));
        const n = Number(
          (result?.tablero as Json)?.total_messages ??
            (result?.summary as Json)?.total_messages ??
            0
        );
        const nProb = Number(
          (result?.summary as Json)?.n_problems ??
            (result?.tablero as Json)?.before?.n_problems ??
            0
        );
        setMsg(
          String(result?.msg || "") ||
            (nProb === 0
              ? "Diagnóstico listo · DiagnosticTool limpio (0 Error/Warning/Hint) · tablero actualizado"
              : `Diagnóstico listo · ${n} msgs · tablero actualizado`)
        );
        await refreshGate();
        // 2) Releer tablero.json regenerado (tablas definitivas en disco)
        try {
          const j = await refreshBoard(1, false, false);
          const vopt = (result?.voltage_opt as Json) || (result?.tablero as Json)?.voltage_opt;
          if (vopt) {
            setBoard((prev) => ({ ...(prev || j || {}), ...(j || {}), voltage_opt: vopt }));
          }
          // Si el disco quedó vacío, refreshBoard ya preservó el snapshot del job
          const msgs = j?.before?.empty === true ? n : (j?.before?.total_messages ?? n);
          const recMsg = vopt && (vopt as Json).triggered
            ? `\n${String((vopt as Json).msg || "")}`
            : "";
          setMsg(
            msgs === 0 && nProb === 0
              ? `2.1 OK · DiagnosticTool limpio (0 problemas) · tablas actualizadas${recMsg}`
              : `2.1 OK · antes=${j?.before?.total_messages ?? n} · después=${j?.after?.total_messages ?? n} · tablas actualizadas${recMsg}`
          );
          if (j?.before?.empty === true) {
            setBoard((prev) => applyDiagResult(prev, result));
          }
        } catch {
          setBoard((prev) => applyDiagResult(prev, result));
        }
      } else if (action === "calidad_sistema" || action === "calidad_eld") {
        // 2.7 / 2.8: panel sistema/ELD — NO pisar tablero del alimentador
        const sd = systemDiagFromResult(result);
        setSystemDiag(sd);
        setMsg(
          String(result?.msg || "") ||
            (sd && Number(sd.n_problems || 0) === 0
              ? `${label} · DiagnosticTool limpio (0 Error/Warning/Hint)`
              : `${label} · problemas=${sd?.n_problems ?? "?"}`)
        );
        await refreshGate();
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
        // Preservar diagnóstico: refreshBoard mergea si disco vacío
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
    const needCtx = !["2.5", "2.7", "2.8", "tablero"].includes(id);
    const active = busy === id;
    return {
      className: `${kind}${active ? " running" : ""}`,
      disabled: Boolean(busy) || (needCtx && !hasCtx),
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

  const sysCodes = useMemo(() => {
    if (!systemDiag?.by_code) return [] as string[];
    return Object.keys(systemDiag.by_code).sort();
  }, [systemDiag]);
  const sysTop = (systemDiag?.top_errors || []).slice(0, 40);
  const sysFeeders = (systemDiag?.per_feeder || []).slice(0, 40);

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
          Vinculado al <b>estudio y BD de §1</b>. 2.1–2.6 analizan el alimentador activo
          con DiagnosticTool (códigos CYMDIST). 2.7/2.8 diagnostican todo el sistema o ELD
          y muestran un panel aparte — no el tablero del feeder.
        </p>
        <p className="muted" style={{ marginTop: 0 }}>
          <b>Gate LISTO</b> = calidad/convergencia del alimentador (listo para §3),{" "}
          <em>no</em> cargabilidad ni perfiles de tensión. Esas vistas
          (VoltageLevel / LoadingLevel) se generan en{" "}
          <a href="/5">§5 LoadFlow</a> e informe.
        </p>
        <div className="hdr-bar">
          <span className={"badge" + (ready ? " ready" : "")} title="Calidad/convergencia del alimentador activo — no implica perfiles LF">
            {ready ? "Gate LISTO" : "Gate pendiente"}
          </span>
          <span className="muted" title={studyPath || ""}>
            {feeder || "sin alimentador"}
            {studyFile ? ` · ${studyFile}` : ""}
            {dbFile ? ` · ${dbFile}` : ""}
          </span>
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
        {!hasCtx ? (
          <p className="muted" style={{ color: "#b45309" }}>
            Configure BD + estudio en §1 y pulse <b>1.1 Aplicar</b> para habilitar §2.
          </p>
        ) : null}
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

      {systemDiag && (
        <section className="panel">
          <h2>
            Diagnóstico sistema / ELD
            {systemDiag.scope ? ` · ${systemDiag.scope}` : ""}
          </h2>
          <p className="muted" style={{ marginTop: 0 }}>
            Resultado de 2.7/2.8 (DiagnosticTool multi-red). No modifica el tablero del
            alimentador activo arriba. Cargabilidad y perfiles de tensión →{" "}
            <a href="/5">§5 LoadFlow</a>.
          </p>
          <div className="cards">
            <div className="card">
              Problemas
              <b className={Number(systemDiag.n_problems || 0) > 0 ? "bad" : ""}>
                {systemDiag.n_problems ?? 0}
              </b>
            </div>
            <div className="card">Errores<b>{systemDiag.n_errors ?? 0}</b></div>
            <div className="card">Warnings<b>{systemDiag.n_warnings ?? 0}</b></div>
            <div className="card">Hints<b>{systemDiag.n_hints ?? 0}</b></div>
            <div className="card">
              Redes OK
              <b>
                {systemDiag.n_networks_ok ?? 0}
                {systemDiag.n_networks_requested != null
                  ? ` / ${systemDiag.n_networks_requested}`
                  : ""}
              </b>
            </div>
            <div className="card">Redes fail<b>{systemDiag.n_networks_fail ?? 0}</b></div>
          </div>
          {Number(systemDiag.n_problems || 0) === 0 && (
            <p className="muted">DiagnosticTool limpio (0 Error/Warning/Hint).</p>
          )}
          {systemDiag.timestamp ? (
            <p className="muted" style={{ marginTop: 4 }}>
              {systemDiag.timestamp}
              {systemDiag.csv ? ` · ${String(systemDiag.csv).split(/[/\\]/).pop()}` : ""}
            </p>
          ) : null}

          <h3>Códigos (sistema)</h3>
          <div className="wrap">
            <table>
              <thead>
                <tr><th>Código</th><th>Cantidad</th></tr>
              </thead>
              <tbody>
                {sysCodes.length === 0 && (
                  <tr><td colSpan={2}>Sin códigos</td></tr>
                )}
                {sysCodes.map((c) => (
                  <tr key={c}>
                    <td>{c}</td>
                    <td>{systemDiag.by_code?.[c] ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Problemas por red / alimentador</h3>
          <div className="wrap">
            <table>
              <thead>
                <tr>
                  <th>Red / Feeder</th>
                  <th>Problemas</th>
                  <th>Msgs</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                {sysFeeders.length === 0 && (
                  <tr><td colSpan={4}>Sin desglose por red</td></tr>
                )}
                {sysFeeders.map((f, i) => (
                  <tr key={i}>
                    <td>
                      {String(f.feeder_id || f.Feeder || f.network_id || f.NetworkID || "")}
                    </td>
                    <td>{String(f.n_problems ?? f.problems ?? "")}</td>
                    <td>{String(f.n_messages ?? f.total_messages ?? "")}</td>
                    <td>
                      {f.error
                        ? String(f.error)
                        : Number(f.n_problems || 0) > 0
                          ? "con problemas"
                          : "OK"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h3>Muestra de errores (sistema)</h3>
          <div className="wrap">
            <table>
              <thead>
                <tr>
                  <th>Red</th>
                  <th>Código</th>
                  <th>Tipo</th>
                  <th>ID</th>
                  <th>Mensaje</th>
                </tr>
              </thead>
              <tbody>
                {sysTop.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      {Number(systemDiag.n_problems || 0) === 0
                        ? "Sin errores (limpio)"
                        : "Sin muestra"}
                    </td>
                  </tr>
                )}
                {sysTop.map((e, i) => (
                  <tr key={i}>
                    <td>{String(e.Feeder || e.Network || e.feeder_id || e.NetworkID || "")}</td>
                    <td>{String(e.Codigo || "")}</td>
                    <td>{String(e.Tipo || "")}</td>
                    <td>{String(e.ID_CYMDIST || "")}</td>
                    <td>{String(e.Mensaje || "").slice(0, 180)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Tablero dinámico</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Solo alimentador activo · DiagnosticTool. Para cargabilidad / perfiles de
          tensión en todos los alimentadores use <a href="/5">§5 LoadFlow</a>.
        </p>
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
            : Number(before.n_problems || 0) === 0 && Number(before.total_messages || 0) === 0
              ? `DiagnosticTool limpio (0 problemas) · Actualizado: ${board?.refreshed_at || board?.generated_at || before.timestamp || "—"}`
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
