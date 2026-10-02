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
  // `import.meta.env` is Vite's, so the dev proxy applies inside a Vite build; elsewhere the address
  // is used as given.
  const dev = import.meta.env?.DEV ?? false;
  if (dev && DEV_PROXY[base]) return DEV_PROXY[base];
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

export interface OutputFile {
  filename: string;
  subfolder: string;
  type: string;
}

export interface RenderOutput {
  name: string;
  url?: string;
  /** The parts the URL is built from, so a saved take can be re-addressed after a reload. */
  file?: OutputFile;
}

/** The playable URL of a file in the service's output or temp tree. */
export function viewUrl(base: string, file: OutputFile): string {
  const query = new URLSearchParams({
    filename: file.filename,
    subfolder: file.subfolder,
    type: file.type,
  });
  return `${endpoint(base)}/view?${query}`;
}

export interface RenderOutcome {
  done: boolean;
  ok: boolean;
  status: string;
  outputs: RenderOutput[];
  messages: RenderMessage[];
}

const TERMINAL = new Set(["succeeded", "failed", "canceled", "expired"]);

/** A line worth showing about a render, and whether it is trouble or just information. */
export interface RenderMessage {
  text: string;
  kind: "note" | "error";
}

/**
 * ComfyUI reports a run as `[event, payload]` pairs, so `String()` over one gives
 * `execution_start,[object Object]` — the payload thrown away and the event name kept, which is
 * exactly backwards: the name is the part you already know.
 *
 * Only the events that carry information survive, and each is described rather than dumped. Severity
 * is carried rather than assumed, because painting "5 nodes came from cache" in the same red as a
 * failed render would be a lie about what happened.
 */
export function describeMessages(messages: unknown[]): RenderMessage[] {
  const out: RenderMessage[] = [];
  for (const entry of messages) {
    if (!Array.isArray(entry) || typeof entry[0] !== "string") continue;
    const [name, payload] = entry as [string, Record<string, unknown> | undefined];
    const data = payload && typeof payload === "object" ? payload : {};

    if (name === "execution_start" || name === "execution_success") continue;

    if (name === "execution_cached") {
      const nodes = Array.isArray(data.nodes) ? data.nodes.length : 0;
      if (nodes) out.push({ kind: "note", text: `${nodes} node(s) came from ComfyUI's cache` });
      continue;
    }

    if (name === "execution_error") {
      const where = data.node_type ?? data.node_id ?? "an unnamed node";
      const kind = data.exception_type ?? "error";
      const why = data.exception_message ?? "";
      out.push({ kind: "error", text: `${kind} at ${where}: ${why}`.trim() });
      const trace = Array.isArray(data.traceback) ? data.traceback : [];
      const last = trace.length ? String(trace[trace.length - 1]).trim() : "";
      if (last) out.push({ kind: "error", text: last });
      continue;
    }

    // An event this code does not know is reported as a note rather than as a failure.
    out.push({ kind: "note", text: name });
  }
  return out.slice(-5).map((message) => ({ ...message, text: message.text.slice(0, 300) }));
}

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
      messages: job.error
        ? [{ kind: "error" as const, text: `${job.error.code ?? "error"}: ${job.error.message ?? ""}` }]
        : [],
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
          const file = item as { subfolder?: string; filename: string; type?: string };
          // A playable URL, so a preview can be listened to without writing anything: previews
          // come back from the temp directory, renders from output.
          const parts: OutputFile = {
            filename: file.filename,
            subfolder: file.subfolder ?? "",
            type: file.type ?? "output",
          };
          outputs.push({
            name: parts.subfolder ? `${parts.subfolder}/${parts.filename}` : parts.filename,
            url: viewUrl(target.base, parts),
            file: parts,
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
    messages: describeMessages(entry.status?.messages ?? []),
  };
}

/**
 * The renderer's own history, as it reports it.
 *
 * ComfyUI keeps this in memory, so it holds the takes the renderer still has in hand, including ones
 * this browser did not render. The listing route and the page's own record are the authority on what a
 * station has; this fills in around them. A v2 target has no such route.
 */
export async function fetchHistory(target: ComfyTarget, limit = 200): Promise<unknown> {
  if (target.protocol === "v2") return {};
  const response = await fetch(`${endpoint(target.base)}/history?max_items=${limit}`, {
    headers: headers(target),
  });
  if (!response.ok) throw await failure(response, "Could not read the renderer's history");
  return await response.json();
}

/** One id per page load: ComfyUI groups a render's messages under it. */
const CLIENT_ID = `music-master-${Math.random().toString(36).slice(2, 10)}`;

/** One file in the renderer's output tree, as the listing route reports it. */
export interface OutputListing {
  name: string;
  subfolder: string;
  path: string;
  type: string;
  content_type: string;
  size: number;
  mtime: number;
}

export interface OutputListRequest {
  subfolder?: string;
  content_type?: string;
  ext?: string;
  sort?: "mtime" | "name" | "size";
  order?: "asc" | "desc";
}

/**
 * What files exist under the renderer's output tree.
 *
 * MyToolbox serves `GET /mytoolbox/output_files`, which reads the output directory itself, so the
 * files on disk are the record and a station's takes are known as they stand on disk.
 *
 * Three answers, each meaning something different to the caller:
 *   - the files, when the route answers;
 *   - an empty list, when the route answers that the subfolder is absent, which is a station with
 *     nothing in it yet;
 *   - `null`, when no route answers — an older server, a v2 target, a refusal — so the caller uses
 *     the addresses the page remembers.
 *
 * The route reports a missing subfolder as a JSON error and an unknown path as an opaque 404, so the
 * second and third answers are told apart by the body.
 */
export async function listOutputFiles(
  target: ComfyTarget,
  request: OutputListRequest = {},
): Promise<OutputListing[] | null> {
  if (target.protocol === "v2") return null;
  const query = new URLSearchParams();
  if (request.subfolder !== undefined) query.set("subfolder", request.subfolder);
  if (request.content_type) query.set("content_type", request.content_type);
  if (request.ext) query.set("ext", request.ext);
  if (request.sort) query.set("sort", request.sort);
  if (request.order) query.set("order", request.order);

  let response: Response;
  try {
    response = await fetch(`${endpoint(target.base)}/mytoolbox/output_files?${query}`, {
      headers: headers(target),
    });
  } catch {
    return null;
  }

  if (response.ok) {
    try {
      const payload = (await response.json()) as { files?: OutputListing[] };
      return Array.isArray(payload.files) ? payload.files : [];
    } catch {
      return null;
    }
  }

  const body = await response.text().catch(() => "");
  try {
    const parsed = JSON.parse(body) as { error?: unknown };
    if (typeof parsed.error === "string") return [];
  } catch {
    /* not this route answering */
  }
  return null;
}

/** A fresh seed, so a second render is a different take rather than the same one again. */
export function freshSeed(): number {
  return 1 + Math.floor(Math.random() * 0x7fffffff);
}

/**
 * The seed a preview or an A/B renders with: the seed of the last take, never one that has not
 * produced a take.
 *
 * A render may generate a fresh seed — a preview must not. A preview exists to compare captions
 * against audio, so it holds the previous seed until a take has actually been rendered with a new
 * one; otherwise a preview of a tag and the take it is meant to explain would not be the same
 * arrangement. Hand-typing a seed does not move it either, for the same reason. Before any take has
 * been rendered there is nothing to hold, and the page's current seed is what a render would send.
 */
export function previewSeed(lastTake: number | null, current: number): number {
  return lastTake ?? current;
}
