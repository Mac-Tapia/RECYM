export type Json = Record<string, unknown>;

let activeFeeder = "";
let activeStudyPath = "";
let activeDatabaseMdb = "";
let activeNetwork = "";
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
}) {
  if (opts.feeder !== undefined) activeFeeder = (opts.feeder || "").trim();
  if (opts.network !== undefined) activeNetwork = (opts.network || "").trim();
  if (opts.studyPath !== undefined) activeStudyPath = (opts.studyPath || "").trim();
  if (opts.databaseMdb !== undefined) activeDatabaseMdb = (opts.databaseMdb || "").trim();
}

export function getActiveContext() {
  return {
    feeder: activeFeeder,
    network: activeNetwork,
    studyPath: activeStudyPath,
    databaseMdb: activeDatabaseMdb,
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

function withAuthHeaders(h: Headers) {
  const key = getApiKey();
  if (key && !h.has("X-Api-Key")) h.set("X-Api-Key", key);
  if (activeFeeder) h.set("X-Feeder", activeFeeder);
  if (activeStudyPath && !h.has("X-Study-Path")) h.set("X-Study-Path", activeStudyPath);
  if (activeDatabaseMdb && !h.has("X-Database-Mdb")) {
    h.set("X-Database-Mdb", activeDatabaseMdb);
  }
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
    if (!obj.feeders && ctx.feeder) obj.feeders = [ctx.feeder];
    return JSON.stringify(obj);
  } catch {
    return body;
  }
}

export async function api<T = Json>(
  path: string,
  opts: RequestInit & { timeoutMs?: number } = {}
): Promise<T> {
  await ensureApiAuth();
  const { timeoutMs = 120000, headers, ...rest } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const h = new Headers(headers || {});
  const method = String(rest.method || "GET").toUpperCase();
  let body = rest.body;
  if (method !== "GET" && method !== "HEAD" && !(body instanceof FormData)) {
    body = injectContextBody(body ?? "{}");
  }
  if (!h.has("Content-Type") && body && !(body instanceof FormData)) {
    h.set("Content-Type", "application/json");
  }
  withAuthHeaders(h);
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
  };
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
          resolve((job.result as Json) || job);
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
          if (job.status === "ok") resolve((job.result as Json) || job);
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
