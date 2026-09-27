/**
 * The optional model half of the generator.
 *
 * Nothing here is required: the scaffold and the brief come from the text tier and work with no
 * network at all. This is the one part of the page that talks to something outside it, and whatever
 * it is given leaves the machine — more so for a cloud model, which ollama routes to ollama.com
 * rather than running on the local GPU.
 */

export interface OllamaModel {
  name: string;
  /** True when ollama routes this model to ollama.com instead of running it here. */
  cloud: boolean;
  sizeBytes: number;
}

const STORAGE_KEY = "mm.ollama.base";

/** `/ollama` is the dev proxy; a static build has none, so it talks to the daemon directly. */
export function defaultBase(): string {
  return import.meta.env.DEV ? "/ollama" : "http://127.0.0.1:11434";
}

export function ollamaBase(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? defaultBase();
  } catch {
    return defaultBase();
  }
}

export function setOllamaBase(value: string): void {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, value);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* not remembering is an acceptable outcome */
  }
}

/**
 * The installed models, cloud first.
 *
 * Cloud first is deliberate: a local model competes for the GPU this machine also renders on, and
 * the cloud ones are the stronger writers. It is only a sort — nothing is hidden.
 */
export async function listModels(base: string = ollamaBase()): Promise<OllamaModel[]> {
  const response = await fetch(`${base}/api/tags`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} from ${base}/api/tags`);
  }
  const data = (await response.json()) as {
    models?: { name: string; size?: number; remote_host?: string }[];
  };
  return (data.models ?? [])
    .map((model) => ({
      name: model.name,
      cloud: Boolean(model.remote_host),
      sizeBytes: model.size ?? 0,
    }))
    .sort((a, b) => Number(b.cloud) - Number(a.cloud) || a.name.localeCompare(b.name));
}

export interface GenerateRequest {
  model: string;
  prompt: string;
  base?: string;
  signal?: AbortSignal;
  /** Called with the whole text so far, so the editor can show a draft as it arrives. */
  onText?: (text: string) => void;
}

/**
 * Stream a completion, returning the whole text. Throws on an ollama-reported error.
 *
 * The stream itself says when it is finished, and that is what ends the read. Waiting for the
 * connection to close instead would hang forever behind anything that keeps it open — a proxy, a
 * load balancer, an idle keep-alive — and the caller would never learn that the text it asked for
 * had already arrived.
 */
export async function generate({
  model,
  prompt,
  base = ollamaBase(),
  signal,
  onText,
}: GenerateRequest): Promise<string> {
  const response = await fetch(`${base}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, prompt, stream: true }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText} from ${base}/api/generate`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";

  /** Read one NDJSON line; true when it was the model's last. */
  const consume = (line: string): boolean => {
    if (!line.trim()) return false;
    const chunk = JSON.parse(line) as { response?: string; error?: string; done?: boolean };
    if (chunk.error) throw new Error(chunk.error);
    if (chunk.response) {
      text += chunk.response;
      onText?.(text);
    }
    return Boolean(chunk.done);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!consume(line)) continue;
      await reader.cancel().catch(() => undefined);
      return text;
    }
  }

  // A last line without a trailing newline is still a line. A partial one is not, and is dropped.
  try {
    consume(buffer);
  } catch {
    /* an incomplete trailing fragment is not an error worth failing a generation over */
  }
  return text;
}
