/**
 * The Jev transport: the one call this page makes to TypeSafe, and the honest account of how it
 * failed when it does.
 *
 * In development the request goes to `/jev`, a same-origin relay in the dev server that adds the
 * key from its own environment. The key never enters the browser there, and the API's CORS refusal
 * — which makes a direct browser call impossible — never applies. A static build has no relay, so
 * the page calls the API directly and the user supplies a key, which is kept in this browser and
 * never rendered back after it is saved.
 *
 * The reason this module exists rather than a bare `fetch` is that the failures a user will hit are
 * easy to misread. A CORS block and a rejected key both leave `fetch` with no useful status, a
 * relay with no key in its environment looks like a service outage, and telling them apart is the
 * difference between "fix your key", "start the dev server with the variable set", and "this page
 * cannot call the API at all". The panel shows that distinction, so the transport has to make it.
 */

export const JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone";
export const JEV_MODEL = "jev-1.13.0";

/** Vite's dev-server middleware that injects the key; a static build has no such route. */
const DEV_ENDPOINT = "/jev";

/** 400 ms, then 1200 ms: long enough for a rate limit to clear, short enough not to feel hung. */
const RETRY_DELAYS_MS = [400, 1200];

const KEY_STORAGE = "mm.jev.key";
const REMEMBER_STORAGE = "mm.jev.remember";
const ENDPOINT_STORAGE = "mm.jev.endpoint";
const MODEL_STORAGE = "mm.jev.model";

/**
 * Storage access is wrapped because a browser can deny it — private modes, a blocked third-party
 * context — and not being able to remember a key is an acceptable outcome where throwing on load is
 * not.
 */
function read(store: Storage | undefined, key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function write(store: Storage | undefined, key: string, value: string): boolean {
  try {
    if (value) store?.setItem(key, value);
    else store?.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

function local(): Storage | undefined {
  return typeof localStorage === "undefined" ? undefined : localStorage;
}

function session(): Storage | undefined {
  return typeof sessionStorage === "undefined" ? undefined : sessionStorage;
}

/**
 * Vite replaces `import.meta.env` at build time, but the browserless smoke harness imports this
 * module under plain Node, where `import.meta.env` does not exist. Reading it defensively lets the
 * transport load there; outside a Vite build the answer is simply "not development", which is the
 * safe default because it assumes a key is needed.
 */
function isDev(): boolean {
  try {
    return Boolean(import.meta.env.DEV);
  } catch {
    return false;
  }
}

/** The relay in development; the API itself in a static build, which has nothing to relay through. */
function defaultEndpoint(): string {
  return isDev() ? DEV_ENDPOINT : JEV_ENDPOINT;
}

export function jevKey(): string {
  return read(local(), KEY_STORAGE) ?? read(session(), KEY_STORAGE) ?? "";
}

export function jevRemembered(): boolean {
  return read(local(), REMEMBER_STORAGE) === "1";
}

/**
 * Write the key to the store the user chose, and clear the other so a forgotten key cannot linger.
 * A remembered key that cannot reach local storage is kept for the tab instead: losing it would be
 * the worse failure, and the session store is what the default already uses.
 */
export function setJevKey(value: string, remember: boolean): void {
  const trimmed = value.trim();
  const primary = remember ? local() : session();
  const secondary = remember ? session() : local();
  if (write(primary, KEY_STORAGE, trimmed)) {
    write(secondary, KEY_STORAGE, "");
  } else if (remember && trimmed) {
    write(session(), KEY_STORAGE, trimmed);
  }
  write(local(), REMEMBER_STORAGE, remember ? "1" : "");
}

export function jevEndpoint(): string {
  return read(local(), ENDPOINT_STORAGE) ?? defaultEndpoint();
}

export function setJevEndpoint(value: string): void {
  write(local(), ENDPOINT_STORAGE, value.trim());
}

export function jevModel(): string {
  return read(local(), MODEL_STORAGE) ?? JEV_MODEL;
}

export function setJevModel(value: string): void {
  write(local(), MODEL_STORAGE, value.trim());
}

export interface JevCallError extends Error {
  kind: "no-key" | "cors" | "network" | "auth" | "validation" | "rate" | "overloaded" | "http";
  status: number | null;
  body: string | null;
  /** True when retrying the same request could plausibly succeed. */
  retryable: boolean;
}

function callError(
  kind: JevCallError["kind"],
  message: string,
  fields: { status?: number | null; body?: string | null; retryable?: boolean } = {},
): JevCallError {
  const error = new Error(message) as JevCallError;
  error.name = "JevCallError";
  error.kind = kind;
  error.status = fields.status ?? null;
  error.body = fields.body ?? null;
  error.retryable = fields.retryable ?? false;
  return error;
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

/** The page's own origin, which is what a CORS refusal is about. */
function pageOrigin(): string {
  try {
    return typeof window === "undefined" ? "this page" : window.location.origin;
  } catch {
    return "this page";
  }
}

/**
 * A rejected `fetch` with a `TypeError` is a CORS or Private Network Access refusal, not an offline
 * machine: the browser refuses before any request is sent, so the service never saw the key and no
 * amount of key-fixing helps.
 */
function corsMessage(endpoint: string): string {
  return (
    `The browser refused the call to ${endpoint} before it could reach TypeSafe, which is what a ` +
    `CORS block or a Private Network Access refusal looks like from JavaScript. This is TypeSafe's ` +
    `policy toward this page's origin (${pageOrigin()}), not a bad key: the request never reached ` +
    `the service, so TypeSafe cannot have seen the key. A page served from a browser origin cannot ` +
    `call this endpoint directly when its origin is not allowed; a server-side proxy, or serving ` +
    `the page from an allowed origin, is what fixes it.`
  );
}

/**
 * The dev relay answers 503 with the reason it has no key, and that reason is the whole story: the
 * dev server was started from a shell without TYPESAFE_API_KEY. Surfacing it verbatim — and not
 * retrying, since the environment will not change on its own — is what stops it being mistaken for
 * a rejected key.
 */
function relayError(body: string): string | null {
  try {
    const parsed = JSON.parse(body) as { error?: unknown };
    if (typeof parsed?.error === "string" && parsed.error.trim()) return parsed.error;
  } catch {
    /* not JSON: fall back to the generic report */
  }
  return null;
}

function failureFor(status: number, body: string, endpoint: string): JevCallError {
  const detail = body.trim() || "(no response body)";
  if (status === 401 || status === 403) {
    return callError("auth", `TypeSafe rejected the API key (HTTP ${status}).\n${detail}`, {
      status,
      body: body || null,
    });
  }
  if (status === 503) {
    const said = relayError(body);
    if (said) return callError("http", said, { status, body: body || null });
  }
  if (status === 422) {
    // A 422 means the request body was malformed, which is a bug in our question rather than a
    // verdict about the song — so the body, which names the offending field, is worth carrying.
    return callError(
      "validation",
      `TypeSafe refused the request as malformed (HTTP 422). This is a bug in the request this page ` +
        `built, not a judgement about the song:\n${detail}`,
      { status, body: body || null },
    );
  }
  if (status === 429) {
    return callError("rate", `TypeSafe rate-limited the request (HTTP 429).\n${detail}`, {
      status,
      body: body || null,
      retryable: true,
    });
  }
  if (status === 529) {
    return callError("overloaded", `TypeSafe is overloaded (HTTP 529).\n${detail}`, {
      status,
      body: body || null,
      retryable: true,
    });
  }
  return callError("http", `${endpoint} answered HTTP ${status}.\n${detail}`, {
    status,
    body: body || null,
    // A server-side failure may clear on its own; a 4xx will answer the same way every time.
    retryable: status >= 500,
  });
}

function isAbort(cause: unknown): boolean {
  return (
    typeof cause === "object" && cause !== null && (cause as { name?: string }).name === "AbortError"
  );
}

function abortReason(signal?: AbortSignal): unknown {
  if (signal?.reason !== undefined) return signal.reason;
  return new DOMException("The Jev call was aborted", "AbortError");
}

/** A sleep that ends early when the caller aborts, so a backoff cannot outlive the request. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortReason(signal));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortReason(signal));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function callJev(
  body: unknown,
  options: { key?: string; endpoint?: string; signal?: AbortSignal } = {},
): Promise<unknown> {
  const dev = isDev();
  const key = (options.key ?? jevKey()).trim();
  // In development the relay holds the key, so the page neither needs one nor sends one.
  if (!dev && !key) {
    throw callError(
      "no-key",
      "No TypeSafe API key is set. Enter one in the Compliance panel; it stays in this browser.",
    );
  }

  const endpoint = (options.endpoint ?? jevEndpoint()).trim().replace(/\/+$/, "");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (!dev && key) headers.Authorization = `Bearer ${key}`;

  // Two retries beyond the first attempt, for the failures a retry could plausibly clear.
  for (let attempt = 0; ; attempt += 1) {
    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: options.signal,
      });
    } catch (cause) {
      if (isAbort(cause)) throw cause;
      const error =
        cause instanceof TypeError
          ? callError("cors", corsMessage(endpoint))
          : callError("network", `Could not reach ${endpoint}: ${describe(cause)}`, {
              retryable: true,
            });
      if (error.retryable && attempt < RETRY_DELAYS_MS.length) {
        await sleep(RETRY_DELAYS_MS[attempt], options.signal);
        continue;
      }
      throw error;
    }

    let text: string;
    try {
      text = await response.text();
    } catch (cause) {
      if (isAbort(cause)) throw cause;
      throw callError("network", `The response from ${endpoint} was cut off: ${describe(cause)}`, {
        retryable: true,
      });
    }

    if (response.ok) {
      try {
        return JSON.parse(text) as unknown;
      } catch {
        throw callError(
          "http",
          `${endpoint} answered ${response.status} with a body that is not JSON: ${text.slice(0, 300)}`,
          { status: response.status, body: text.slice(0, 2000) },
        );
      }
    }

    const error = failureFor(response.status, text.slice(0, 2000), endpoint);
    if (error.retryable && attempt < RETRY_DELAYS_MS.length) {
      await sleep(RETRY_DELAYS_MS[attempt], options.signal);
      continue;
    }
    throw error;
  }
}
