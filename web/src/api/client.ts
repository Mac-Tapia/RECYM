export type Json = Record<string, unknown>;

let activeFeeder = "";
let activeStudyPath = "";
let activeDatabaseMdb = "";
let activeNetwork = "";
let activeContextFingerprint = "";
let activeScenarioId = "";
let apiKey = "";
let bootstrapPromise: Promise<void> | null = null;

const KEY_STORAGE = "recym_api_key";

export function setActiveFeeder(feeder: string) {
  activeFeeder = (feeder || "").trim();
}

export function getActiveFeeder() {
  return activeFeeder;
}

/** Contexto §1 completo: cada job/CymPy debe usar esta BD+estudio, no un fijo. */
export function setActiveContext(opts: {
  feeder?: string;
  network?: string;
  studyPath?: string;
  databaseMdb?: string;
  contextFingerprint?: string;
  scenarioId?: string;
}) {
  if (opts.feeder !== undefined) activeFeeder = (opts.feeder || "").trim();
  if (opts.network !== undefined) activeNetwork = (opts.network || "").trim();
  if (opts.studyPath !== undefined) activeStudyPath = (opts.studyPath || "").trim();
  if (opts.databaseMdb !== undefined) activeDatabaseMdb = (opts.databaseMdb || "").trim();
  if (opts.contextFingerprint !== undefined) {
    activeContextFingerprint = (opts.contextFingerprint || "").trim().toLowerCase();
  }
  if (opts.scenarioId !== undefined) activeScenarioId = (opts.scenarioId || "").trim();
}

export function getActiveContext() {
  return {
    feeder: activeFeeder,
    network: activeNetwork,
    studyPath: activeStudyPath,
    databaseMdb: activeDatabaseMdb,
    contextFingerprint: activeContextFingerprint,
    scenarioId: activeScenarioId,
  };
}

export function setApiKey(key: string) {
  apiKey = (key || "").trim();
  try {
    if (apiKey) localStorage.setItem(KEY_STORAGE, apiKey);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* ignore */
  }
}

export function getApiKey() {
  if (apiKey) return apiKey;
  try {
    apiKey = (localStorage.getItem(KEY_STORAGE) || "").trim();
  } catch {
    apiKey = "";
  }
  return apiKey;
}

/** Obtiene API key desde bootstrap localhost (una vez). */
export async function ensureApiAuth(): Promise<void> {
  if (getApiKey()) return;
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = (async () => {
    try {
      const r = await fetch("/api/auth/bootstrap", { credentials: "same-origin" });
      const data = (await r.json()) as {
        ok?: boolean;
        api_key?: string;
        auth_required?: boolean;
      };
      if (data.ok && data.api_key) setApiKey(data.api_key);
    } catch {
      /* development loopback puede seguir sin key */
    }
  })();
  return bootstrapPromise;
}

function withAuthHeaders(h: Headers, includeContext = true) {
  const key = getApiKey();
  if (key && !h.has("X-Api-Key")) h.set("X-Api-Key", key);
  if (!includeContext) return;
  if (activeFeeder) h.set("X-Feeder", activeFeeder);
  if (activeNetwork) h.set("X-Network-Id", activeNetwork);
  if (activeStudyPath && !h.has("X-Study-Path")) h.set("X-Study-Path", activeStudyPath);
  if (activeDatabaseMdb && !h.has("X-Database-Mdb")) {
    h.set("X-Database-Mdb", activeDatabaseMdb);
  }
  if (activeContextFingerprint) {
    h.set("X-Context-Fingerprint", activeContextFingerprint);
  }
  if (activeScenarioId) h.set("X-Scenario-Id", activeScenarioId);
}

/** Inyecta feeder/estudio/BD de §1 en bodies JSON (POST/PUT/PATCH). */
function injectContextBody(body: BodyInit | null | undefined): BodyInit | null | undefined {
  if (body == null || typeof body !== "string") return body;
  try {
    const obj = JSON.parse(body) as Record<string, unknown>;
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return body;
    const ctx = getActiveContext();
    if (!obj.feeder && ctx.feeder) obj.feeder = ctx.feeder;
    if (!obj.feeder_id && ctx.feeder) obj.feeder_id = ctx.feeder;
    if (!obj.network_id && ctx.network) obj.network_id = ctx.network;
    if (!obj.study_path && ctx.studyPath) obj.study_path = ctx.studyPath;
    if (!obj.database_mdb && ctx.databaseMdb) obj.database_mdb = ctx.databaseMdb;
    if (!obj.context_fingerprint && ctx.contextFingerprint) {
      obj.context_fingerprint = ctx.contextFingerprint;
    }
    if (!obj.scenario_id && ctx.scenarioId) obj.scenario_id = ctx.scenarioId;
    if (!obj.feeders && ctx.feeder) obj.feeders = [ctx.feeder];
    return JSON.stringify(obj);
  } catch {
    return body;
  }
}

export async function api<T = Json>(
  path: string,
  opts: RequestInit & { timeoutMs?: number; detachedContext?: boolean } = {}
): Promise<T> {
  await ensureApiAuth();
  const { timeoutMs = 120000, detachedContext = false, headers, ...rest } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const h = new Headers(headers || {});
  const method = String(rest.method || "GET").toUpperCase();
  let body = rest.body;
  if (
    !detachedContext &&
    method !== "GET" &&
    method !== "HEAD" &&
    !(body instanceof FormData)
  ) {
    body = injectContextBody(body ?? "{}");
  }
  if (!h.has("Content-Type") && body && !(body instanceof FormData)) {
    h.set("Content-Type", "application/json");
  }
  withAuthHeaders(h, !detachedContext);
  try {
    const r = await fetch(path, {
      ...rest,
      body,
      headers: h,
      signal: ctrl.signal,
      credentials: "same-origin",
    });
    const text = await r.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      throw new Error(`Respuesta no JSON (${r.status}): ${text.slice(0, 200)}`);
    }
    if (!r.ok) {
      const err =
        data && typeof data === "object" && "error" in data
          ? String((data as { error?: unknown }).error || "")
          : "";
      throw new Error(err || `HTTP ${r.status} en ${path}`);
    }
    return data as T;
  } finally {
    clearTimeout(timer);
  }
}

function eventsUrl(jobId: string) {
  const key = getApiKey();
  const q = key ? `?api_key=${encodeURIComponent(key)}` : "";
  return `/api/jobs/${jobId}/events${q}`;
}

/** Descarga autenticada y contextual; evita anchors que pierden API key/identidad. */
export async function downloadApiFile(path: string, filename: string): Promise<void> {
  await ensureApiAuth();
  const headers = new Headers();
  withAuthHeaders(headers, true);
  const response = await fetch(path, {
    method: "GET",
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text || `HTTP ${response.status}`;
    try {
      const parsed = JSON.parse(text) as { error?: string };
      message = parsed.error || message;
    } catch {
      /* keep response text */
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

const PROTECTED_JOB_ACTIONS = new Set([
  "calidad_diagnosticar", "calidad_proponer", "calidad_aplicar",
  "calidad_convergencia", "calidad_hasta_limpio", "calidad_sistema",
  "calidad_eld", "distribucion", "flujo_situacional_34", "flujo", "clientes_activo_cymdist",
  "optimizacion_reclosers", "optimizacion_regulators", "optimizacion_capacitors",
  "suite_conexion", "suite_inventario_cargas", "suite_sync_equipos",
  "suite_fix_default", "suite_export_ascii", "suite_pipeline",
]);

export function verifyProtectedJobContext(
  action: string,
  result: Json,
  expectedFingerprint: string
): Json {
  if (!PROTECTED_JOB_ACTIONS.has(action)) return result;
  const expected = (expectedFingerprint || "").trim().toLowerCase();
  if (!expected) throw new Error("Contexto CYMDIST sin huella: complete y aplique §1.1");
  const actual = String(result?.context_fingerprint || "").trim().toLowerCase();
  if (!actual) throw new Error("Respuesta CYMDIST sin huella de contexto");
  if (actual !== expected) {
    throw new Error(`Respuesta de contexto distinto (esperado ${expected}, recibido ${actual})`);
  }
  return result;
}

export async function runJob(
  action: string,
  payload: Json = {},
  onUpdate?: (job: Json) => void
): Promise<Json> {
  const ctx = getActiveContext();
  const merged: Json = {
    ...payload,
    // Inyectar BD/estudio/alimentador activos de §1 si el caller no los pasó
    feeder: payload.feeder || ctx.feeder || undefined,
    feeder_id: payload.feeder_id || ctx.feeder || undefined,
    network_id: payload.network_id || ctx.network || undefined,
    study_path: payload.study_path || ctx.studyPath || undefined,
    database_mdb: payload.database_mdb || ctx.databaseMdb || undefined,
    context_fingerprint:
      payload.context_fingerprint || ctx.contextFingerprint || undefined,
    scenario_id: payload.scenario_id || ctx.scenarioId || undefined,
  };
  if (PROTECTED_JOB_ACTIONS.has(action) && !ctx.contextFingerprint) {
    throw new Error("Contexto CYMDIST sin huella: complete y aplique §1.1");
  }
  const created = await api<{ ok: boolean; job_id: string; error?: string }>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({
      action,
      payload: merged,
      feeder: activeFeeder || merged.feeder || undefined,
    }),
  });
  if (!created.ok || !created.job_id) {
    throw new Error(created.error || "No se pudo crear job");
  }
  const jobId = created.job_id;

  return new Promise((resolve, reject) => {
    const es = new EventSource(eventsUrl(jobId));
    es.onmessage = (ev) => {
      try {
        const job = JSON.parse(ev.data) as Json;
        onUpdate?.(job);
        const st = String(job.status || "");
        if (st === "ok") {
          es.close();
          resolve(
            verifyProtectedJobContext(
              action,
              (job.result as Json) || job,
              ctx.contextFingerprint
            )
          );
        } else if (st === "error") {
          es.close();
          const res = (job.result as Json) || {};
          reject(
            new Error(String(res.error || res.msg || job.message || "Job falló"))
          );
        }
      } catch (e) {
        es.close();
        reject(e);
      }
    };
    es.onerror = () => {
      es.close();
      api<{ job: Json }>(`/api/jobs/${jobId}`)
        .then((j) => {
          const job = j.job || {};
          onUpdate?.(job);
          if (job.status === "ok") {
            resolve(
              verifyProtectedJobContext(
                action,
                (job.result as Json) || job,
                ctx.contextFingerprint
              )
            );
          }
          else {
            const res = (job.result as Json) || {};
            reject(
              new Error(String(res.error || res.msg || job.message || "SSE error"))
            );
          }
        })
        .catch(reject);
    };
  });
}

export function buildDetachedJobEnvelope(action: string, payload: Json = {}) {
  return {
    action,
    payload: { ...payload },
  };
}

/** Job de descubrimiento: no hereda feeder, estudio, red ni MDB activos. */
export async function runDetachedJob(
  action: string,
  payload: Json = {},
  onUpdate?: (job: Json) => void
): Promise<Json> {
  const envelope = buildDetachedJobEnvelope(action, payload);
  const created = await api<{ ok: boolean; job_id: string; error?: string }>(
    "/api/jobs",
    {
      method: "POST",
      body: JSON.stringify(envelope),
      detachedContext: true,
    }
  );
  if (!created.ok || !created.job_id) {
    throw new Error(created.error || "No se pudo crear job desacoplado");
  }
  const jobId = created.job_id;
  return new Promise((resolve, reject) => {
    const es = new EventSource(eventsUrl(jobId));
    es.onmessage = (ev) => {
      try {
        const job = JSON.parse(ev.data) as Json;
        onUpdate?.(job);
        const status = String(job.status || "");
        if (status === "ok") {
          es.close();
          resolve((job.result as Json) || job);
        } else if (status === "error") {
          es.close();
          const result = (job.result as Json) || {};
          reject(new Error(String(result.error || result.msg || job.message || "Job falló")));
        }
      } catch (error) {
        es.close();
        reject(error);
      }
    };
    es.onerror = () => {
      es.close();
      api<{ job: Json }>(`/api/jobs/${jobId}`, { detachedContext: true })
        .then(({ job }) => {
          onUpdate?.(job || {});
          if (job?.status === "ok") resolve((job.result as Json) || job);
          else {
            const result = (job?.result as Json) || {};
            reject(
              new Error(String(result.error || result.msg || job?.message || "SSE error"))
            );
          }
        })
        .catch(reject);
    };
  });
}
