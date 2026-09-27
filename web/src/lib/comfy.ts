/**
 * The render target: which service runs the graph, and how to talk to it.
 *
 * There are two protocols, not one. A self-hosted ComfyUI speaks its own `POST /prompt` and
 * `/history/{id}`. Comfy API v2 — Comfy Cloud, a serverless deployment, or a self-hosted ComfyUI
 * behind `comfy-api-proxy` — speaks `POST /api/v2/jobs` with `Authorization: Bearer` and returns a
 * durable job with embedded follow-up links. Which one is in play is a property of the target, so it
 * is part of the target rather than guessed at.
 *
 * The API key is the awkward part and the interface says so: a page served over the web cannot keep
 * a secret, so a key typed here lives in this tab's session storage, is sent only to the service you
 * point it at, and is gone when the tab closes.
 */

export type ComfyProtocol = "native" | "v2";

export interface ComfyPreset {
  id: string;
  label: string;
  base: string;
  protocol: ComfyProtocol;
  needsKey: boolean;
  note: string;
}

/**
 * The surfaces worth offering by name. ComfyUI's own default is 8188; this project's scripts and
 * ComfyUI graphs have used 8288; the v2 proxy listens on 8189.
 */
export const PRESETS: ComfyPreset[] = [
  {
    id: "local-8288",
    label: "Local — this project's service (:8288)",
    base: "http://127.0.0.1:8288",
    protocol: "native",
    needsKey: false,
    note: "The port songs/*/build_and_submit.py defaults to.",
  },
  {
    id: "local-8188",
    label: "Local — ComfyUI's own default (:8188)",
    base: "http://127.0.0.1:8188",
    protocol: "native",
    needsKey: false,
    note: "Where a stock ComfyUI listens.",
  },
  {
    id: "proxy-8189",
    label: "Local — comfy-api-proxy (:8189, v2)",
    base: "http://127.0.0.1:8189",
    protocol: "v2",
    needsKey: false,
    note: "`pip install comfy-api-proxy` puts the v2 API in front of a local ComfyUI.",
  },
  {
    id: "cloud",
    label: "Comfy Cloud (cloud.comfy.org, v2)",
    base: "https://cloud.comfy.org",
    protocol: "v2",
    needsKey: true,
    note: "Needs a paid Comfy Cloud subscription and an API key. The graph leaves this machine.",
  },
  {
    id: "custom",
    label: "Custom…",
    base: "",
    protocol: "native",
    needsKey: false,
    note: "Any base URL, either protocol.",
  },
];

export function presetFor(base: string): ComfyPreset | undefined {
  return PRESETS.find((preset) => preset.base === base);
}

export interface ComfyTarget {
  base: string;
  protocol: ComfyProtocol;
  key?: string;
}

const BASE_KEY = "mm.comfy.base";
const PROTOCOL_KEY = "mm.comfy.protocol";
const KEY_KEY = "mm.comfy.key";

/** The address shown in the interface is always the real one; the dev proxy is an implementation
 * detail of `endpoint`, so nothing in the UI displays a `/comfy-…` path. */
export function defaultComfyBase(): string {
  return "http://127.0.0.1:8288";
}

function read(store: Storage | undefined, key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function loadTarget(): ComfyTarget {
  return {
    base: read(localStorage, BASE_KEY) ?? defaultComfyBase(),
    protocol: (read(localStorage, PROTOCOL_KEY) as ComfyProtocol | null) ?? "native",
    // Session, not local: a page cannot keep a secret, so the key should not outlive the tab either.
    key: read(sessionStorage, KEY_KEY) ?? "",
  };
}

export function saveTarget(target: ComfyTarget): void {
  try {
    if (target.base) localStorage.setItem(BASE_KEY, target.base);
    else localStorage.removeItem(BASE_KEY);
    localStorage.setItem(PROTOCOL_KEY, target.protocol);
  } catch {
    /* not remembering is an acceptable outcome */
  }
  try {
    if (target.key) sessionStorage.setItem(KEY_KEY, target.key);
    else sessionStorage.removeItem(KEY_KEY);
  } catch {
    /* as above */
  }
}

/**
 * In development two loopback ports are proxied by the dev server, so a local render needs no CORS
 * on the ComfyUI side. Any other address is used as given.
 */
const DEV_PROXY: Record<string, string> = {
  "http://127.0.0.1:8288": "/comfy-8288",
  "http://localhost:8288": "/comfy-8288",
  "http://127.0.0.1:8188": "/comfy-8188",
  "http://localhost:8188": "/comfy-8188",
};

export function endpoint(base: string): string {
  if (import.meta.env.DEV && DEV_PROXY[base]) return DEV_PROXY[base];
  return base.replace(/\/+$/, "");
}

function headers(target: ComfyTarget): Record<string, string> {
  const out: Record<string, string> = { "Content-Type": "application/json" };
  if (target.key) out.Authorization = `Bearer ${target.key}`;
  return out;
}

export interface Probe {
  ok: boolean;
  detail: string;
}

/** Whether anything is listening, and whether it will take this key. */
export async function probe(target: ComfyTarget): Promise<Probe> {
  const base = endpoint(target.base);
  const url = target.protocol === "v2" ? `${base}/api/v2/jobs` : `${base}/system_stats`;
  const response = await fetch(url, { headers: headers(target) });
  if (response.status === 401 || response.status === 403) {
    return { ok: false, detail: "reached, but it rejected the API key" };
  }
  if (!response.ok) {
    return { ok: false, detail: `answered HTTP ${response.status}` };
  }
  return { ok: true, detail: target.protocol === "v2" ? "v2 API reachable" : "native API reachable" };
}

export interface Queued {
  jobId: string;
  /** For v2, the link to follow; for native, the id is enough. */
  pollUrl: string;
}

async function failure(response: Response, what: string): Promise<Error> {
  const text = await response.text();
  let detail = text.slice(0, 1500);
  try {
    const parsed = JSON.parse(text) as { error?: { code?: string; message?: string } };
    if (parsed.error) detail = `${parsed.error.code ?? "error"}: ${parsed.error.message ?? ""}`;
  } catch {
    /* not JSON; the raw text is the most useful thing we have */
  }

  if (!detail.trim()) {
    // A bare status is not an explanation, and these two have one worth giving.
    if (response.status === 403) {
      detail =
        "ComfyUI answered 403 with no body. It refuses a POST to a loopback address whose Origin " +
        "host or port differs from its Host — a guard against a random site queueing renders " +
        "through 127.0.0.1. The dev server proxies :8288 and :8188, so this does not arise there. " +
        "A page served from anywhere else cannot post to a loopback ComfyUI at all: reach it at a " +
        "non-loopback address instead, with --enable-cors-header set for this page.";
    } else {
      detail = `no response body (${response.statusText || "no status text"})`;
    }
  }

  return new Error(`${what} (HTTP ${response.status}):\n${detail}`);
}

export async function submitWorkflow(target: ComfyTarget, workflow: unknown): Promise<Queued> {
  const base = endpoint(target.base);

  if (target.protocol === "v2") {
    const response = await fetch(`${base}/api/v2/jobs`, {
      method: "POST",
      headers: headers(target),
      body: JSON.stringify({ workflow }),
    });
    if (!response.ok) throw await failure(response, "The v2 API rejected the graph");
    const job = (await response.json()) as { id?: string; urls?: { self?: string } };
    if (!job.id) throw new Error("The v2 API returned a job with no id");
    // "Follow links, don't build URLs": the surface may be mounted under a prefix.
    const self = job.urls?.self ?? `/api/v2/jobs/${job.id}`;
    const pollUrl = new URL(self, `${base}/`).href;
    return { jobId: job.id, pollUrl };
  }

  const response = await fetch(`${base}/prompt`, {
    method: "POST",
    headers: headers(target),
    body: JSON.stringify({ prompt: workflow, client_id: CLIENT_ID }),
  });
  if (!response.ok) throw await failure(response, "ComfyUI rejected the graph");
  const text = await response.text();
  let parsed: { prompt_id?: string };
  try {
    parsed = JSON.parse(text) as { prompt_id?: string };
  } catch {
    throw new Error(`ComfyUI answered with something that is not JSON:\n${text.slice(0, 400)}`);
  }
  if (!parsed.prompt_id) throw new Error(`ComfyUI queued nothing:\n${text.slice(0, 800)}`);
  return { jobId: parsed.prompt_id, pollUrl: `${base}/history/${parsed.prompt_id}` };
}

export interface RenderOutput {
  name: string;
  url?: string;
}

export interface RenderOutcome {
  done: boolean;
  ok: boolean;
  status: string;
  outputs: RenderOutput[];
  messages: string[];
}

const TERMINAL = new Set(["succeeded", "failed", "canceled", "expired"]);

/** The render's state, or `{done: false}` while it is still going. */
export async function fetchOutcome(target: ComfyTarget, pollUrl: string): Promise<RenderOutcome> {
  const response = await fetch(pollUrl, { headers: headers(target) });
  if (!response.ok) throw await failure(response, "Could not read the render's state");

  if (target.protocol === "v2") {
    const job = (await response.json()) as {
      status?: string;
      outputs?: { name?: string; url?: string }[];
      error?: { code?: string; message?: string };
    };
    const status = String(job.status ?? "unknown");
    const outputs = (job.outputs ?? []).map((output) => ({
      name: output.name ?? "(unnamed)",
      // The v2 content route needs the key; a browser cannot open it unauthenticated.
      url: undefined,
    }));
    return {
      done: TERMINAL.has(status),
      ok: status === "succeeded",
      status,
      outputs,
      messages: job.error ? [`${job.error.code ?? "error"}: ${job.error.message ?? ""}`] : [],
    };
  }

  const history = (await response.json()) as Record<
    string,
    {
      status?: { status_str?: string; messages?: unknown[] };
      outputs?: Record<string, Record<string, unknown>>;
    }
  >;
  const entry = Object.values(history)[0];
  if (!entry) return { done: false, ok: false, status: "running", outputs: [], messages: [] };

  const outputs: RenderOutput[] = [];
  for (const node of Object.values(entry.outputs ?? {})) {
    for (const value of Object.values(node)) {
      if (!Array.isArray(value)) continue;
      for (const item of value) {
        if (item && typeof item === "object" && "filename" in item) {
          const file = item as { subfolder?: string; filename: string };
          outputs.push({
            name: file.subfolder ? `${file.subfolder}/${file.filename}` : file.filename,
          });
        }
      }
    }
  }

  const status = String(entry.status?.status_str ?? "unknown");
  return {
    done: status === "success" || status === "error",
    ok: status === "success",
    status,
    outputs,
    messages: (entry.status?.messages ?? []).slice(-3).map((m) => String(m).slice(0, 300)),
  };
}

/** One id per page load: ComfyUI groups a render's messages under it. */
const CLIENT_ID = `music-master-${Math.random().toString(36).slice(2, 10)}`;

/** A fresh seed, so a second render is a different take rather than the same one again. */
export function freshSeed(): number {
  return 1 + Math.floor(Math.random() * 0x7fffffff);
}
