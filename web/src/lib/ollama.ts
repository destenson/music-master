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
const TEMPERATURE_KEY = "mm.ollama.temperature";

/**
 * The knobs that decide *which* answer a model gives.
 *
 * A prompt is a question; the sampling is how the model is allowed to answer it. With none sent, the
 * server's defaults decide, and a model at a low temperature answers the same question with the same
 * words every time — so a second Generate press, or a second song that drew a similar prompt, came
 * back as the same lyric. That is the whole reason these are sent rather than left alone.
 */
export interface Sampling {
  temperature?: number;
  top_p?: number;
  repeat_penalty?: number;
  presence_penalty?: number;
  frequency_penalty?: number;
  seed?: number;
}

/**
 * What a song is written with unless the writer says otherwise.
 *
 * A temperature above the usual default is the point: the brief pins the counts and the rhyme
 * scheme, so the words are the free variable, and the checker catches a draft that drifted too far.
 * The repeat penalty is mild, because a chorus is *meant* to repeat its hook.
 */
export const WRITING_SAMPLING: Sampling = {
  temperature: 1.05,
  top_p: 0.95,
  repeat_penalty: 1.05,
};

/** The temperature actually used, from the writer's setting or the default. */
export function loadTemperature(): number {
  try {
    const raw = localStorage.getItem(TEMPERATURE_KEY);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? Math.min(2, Math.max(0, value)) : (WRITING_SAMPLING.temperature as number);
  } catch {
    return WRITING_SAMPLING.temperature as number;
  }
}

export function saveTemperature(value: number): void {
  try {
    localStorage.setItem(TEMPERATURE_KEY, String(Math.min(2, Math.max(0, value))));
  } catch {
    /* not remembering is an acceptable outcome */
  }
}

/**
 * The seed for a song's nth attempt.
 *
 * The song decides it and the attempt moves it, so a take is reproducible from what was recorded —
 * but asking again after a collision is a different request even when the prompt is the same. 7919
 * is only a stride that is coprime with any power of two, so successive attempts spread out.
 */
export function writingSeed(songSeed: number, attempt: number): number {
  return (Math.abs(Math.trunc(songSeed)) + Math.max(0, Math.trunc(attempt)) * 7919) % 0x7fffffff;
}

/** A seed for a one-off generation, so pressing Generate again asks a different question. */
export function freshWritingSeed(): number {
  return 1 + Math.floor(Math.random() * 0x7fffffff);
}

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
  /**
   * Whether a thinking model may reason before answering, where the server supports the field.
   *
   * It is left off the request entirely when unset, so a server that does not know it never sees
   * it. A thinking model spends tens of seconds reasoning before writing anything — measured at
   * 35 s and 34 KB of reasoning for one song's lyric, against 1.8 s with it off — which is time
   * nothing downstream can use, since the lyric is the whole answer.
   */
  think?: boolean;
  /**
   * How the model is allowed to answer. Left off the request entirely when unset, so a caller that
   * wants the server's defaults still gets them.
   */
  sampling?: Sampling;
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
  think,
  sampling,
}: GenerateRequest): Promise<string> {
  const response = await fetch(`${base}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      prompt,
      stream: true,
      ...(think === undefined ? {} : { think }),
      ...(sampling ? { options: sampling } : {}),
    }),
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
