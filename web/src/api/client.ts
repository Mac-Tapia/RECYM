export type Json = Record<string, unknown>;

let activeFeeder = "";

export function setActiveFeeder(feeder: string) {
  activeFeeder = (feeder || "").trim();
}

export function getActiveFeeder() {
  return activeFeeder;
}

export async function api<T = Json>(
  path: string,
  opts: RequestInit & { timeoutMs?: number } = {}
): Promise<T> {
  const { timeoutMs = 120000, headers, ...rest } = opts;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const h = new Headers(headers || {});
  if (!h.has("Content-Type") && rest.body && !(rest.body instanceof FormData)) {
    h.set("Content-Type", "application/json");
  }
  if (activeFeeder) h.set("X-Feeder", activeFeeder);
  try {
    const r = await fetch(path, { ...rest, headers: h, signal: ctrl.signal });
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

export async function runJob(
  action: string,
  payload: Json = {},
  onUpdate?: (job: Json) => void
): Promise<Json> {
  const created = await api<{ ok: boolean; job_id: string; error?: string }>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ action, payload, feeder: activeFeeder || undefined }),
  });
  if (!created.ok || !created.job_id) {
    throw new Error(created.error || "No se pudo crear job");
  }
  const jobId = created.job_id;

  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
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
          reject(new Error(String(
            res.error || res.msg || job.message || "Job falló"
          )));
        }
      } catch (e) {
        es.close();
        reject(e);
      }
    };
    es.onerror = () => {
      es.close();
      // fallback poll
      api<{ job: Json }>(`/api/jobs/${jobId}`)
        .then((j) => {
          const job = j.job || {};
          onUpdate?.(job);
          if (job.status === "ok") resolve((job.result as Json) || job);
          else {
            const res = (job.result as Json) || {};
            reject(new Error(String(res.error || res.msg || job.message || "SSE error")));
          }
        })
        .catch(reject);
    };
  });
}
