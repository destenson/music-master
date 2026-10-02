/**
 * What a rendered take says about itself.
 *
 * ACE-Step renders through ComfyUI, and ComfyUI writes the graph it executed into the MP3's ID3 tags
 * as a `prompt` TXXX frame. That graph is the take's own record: the caption it was given, the lyrics
 * it sang, its seed and its tempo, and the file is the authority on all four.
 *
 * The parsing is pure and free of the DOM and the network, so the smoke run can pin it against
 * hand-built tag bytes without a renderer. Only `readTakeTags` touches IO, and it reads the front of
 * the file: the tag is at the start, so a Range request identifies a take cheaply. An unreadable
 * file, a foreign tag, or a graph from a different model comes back as `null`, and the take plays on
 * from its name and the history the page holds.
 */

/** The part of a take's graph that identifies the take to a listener. */
export interface TakeTags {
  caption: string;
  lyrics: string;
  seed: number | null;
  bpm: number | null;
}

/** A node of a ComfyUI API graph, as much of one as reading a take needs. */
interface GraphNode {
  class_type?: unknown;
  inputs?: Record<string, unknown>;
}

const ID3_HEADER = 10;
const FRAME_HEADER = 10;

/**
 * The most of a file worth reading for its tag.
 *
 * A graph carrying a full lyric is tens of kilobytes. This is a ceiling: the read stops as soon as
 * the tag is complete, so even a renderer that sends the whole file has the read end at the tag.
 */
const FRONT_LIMIT = 1 << 20;

/** An ID3v2 syncsafe integer: seven bits per byte, so a size can never look like a frame marker. */
function syncsafe(bytes: Uint8Array, at: number): number {
  return (
    ((bytes[at] & 0x7f) << 21) |
    ((bytes[at + 1] & 0x7f) << 14) |
    ((bytes[at + 2] & 0x7f) << 7) |
    (bytes[at + 3] & 0x7f)
  );
}

/** A plain big-endian integer, which is how ID3v2.3 sizes and v2.3 extended headers are written. */
function plain(bytes: Uint8Array, at: number): number {
  return (
    ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0
  );
}

/** A frame's text: an encoding byte, then a NUL-terminated description and the value. */
function text(payload: Uint8Array): string {
  if (payload.length < 2) return "";
  const encoding = payload[0];
  const body = payload.subarray(1);
  let label = "utf-8";
  if (encoding === 0) label = "latin1";
  else if (encoding === 1) {
    // UTF-16 with a byte-order mark, which the decoder does not always strip.
    label = body[0] === 0xfe && body[1] === 0xff ? "utf-16be" : "utf-16le";
  } else if (encoding === 2) label = "utf-16be";
  return new TextDecoder(label).decode(body).replace(/^\uFEFF/, "");
}

/** The description and value of a TXXX frame, split on the first NUL. */
function partition(value: string): [string, string] {
  const at = value.indexOf("\u0000");
  return at < 0 ? [value, ""] : [value.slice(0, at), value.slice(at + 1)];
}

/**
 * The first complete JSON object in a string.
 *
 * The frame's size is the authority, so normally this parses the whole value. A tag written by a
 * different tool can pad the frame with NULs or trailing bytes after the graph, and the object's own
 * closing brace ends the read.
 */
function firstJson(value: string): unknown {
  const trimmed = value.replace(/\u0000+$/, "").trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    /* find the object's end by hand */
  }
  const start = trimmed.indexOf("{");
  if (start < 0) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let at = start; at < trimmed.length; at++) {
    const character = trimmed[at];
    if (inString) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') inString = false;
      continue;
    }
    if (character === '"') inString = true;
    else if (character === "{") depth += 1;
    else if (character === "}" && --depth === 0) {
      try {
        return JSON.parse(trimmed.slice(start, at + 1));
      } catch {
        return null;
      }
    }
  }
  return null;
}

/**
 * The graph ComfyUI embedded in a file, or `null` when the file is not an ID3-tagged graph.
 *
 * Both ID3v2.3 and v2.4 frames are read, because the frame size is syncsafe in one and a plain
 * integer in the other and a take should not depend on which ComfyUI version wrote it.
 */
export function graphFromMp3(bytes: Uint8Array): unknown {
  if (bytes.length < ID3_HEADER) return null;
  if (bytes[0] !== 0x49 || bytes[1] !== 0x44 || bytes[2] !== 0x33) return null;
  const version = bytes[3];
  const flags = bytes[5];
  const end = Math.min(bytes.length, ID3_HEADER + syncsafe(bytes, 6));
  let at = ID3_HEADER;

  if (flags & 0x40 && at + 4 <= end) {
    // A v2.4 extended header's size includes itself; a v2.3 one's does not.
    at += version >= 4 ? syncsafe(bytes, at) : plain(bytes, at) + 4;
  }

  while (at + FRAME_HEADER <= end) {
    const id = String.fromCharCode(bytes[at], bytes[at + 1], bytes[at + 2], bytes[at + 3]);
    if (!/^[A-Z0-9]{4}$/.test(id)) break;
    const size = version >= 4 ? syncsafe(bytes, at + 4) : plain(bytes, at + 4);
    const frameFlags = (bytes[at + 8] << 8) | bytes[at + 9];
    // Compressed or encrypted frames are not text, and their size is not the text's size.
    if (frameFlags & 0x00c0) break;
    const start = at + FRAME_HEADER;
    if (size <= 0 || start + size > end) break;
    if (id === "TXXX") {
      const [description, value] = partition(text(bytes.subarray(start, start + size)));
      if (description === "prompt") return firstJson(value);
    }
    at = start + size;
  }
  return null;
}

/** The nodes of a graph, whether it is the bare API graph or a queue tuple that contains one. */
function nodes(graph: unknown): [string, GraphNode][] {
  if (!graph || typeof graph !== "object") return [];
  if (Array.isArray(graph)) {
    const embedded = graph.find(
      (part) =>
        part &&
        typeof part === "object" &&
        !Array.isArray(part) &&
        ("4" in (part as object) || "8" in (part as object)),
    );
    return embedded ? nodes(embedded) : [];
  }
  return Object.entries(graph as Record<string, unknown>)
    .filter(([, node]) => Boolean(node) && typeof node === "object")
    .map(([id, node]) => [id, node as GraphNode]);
}

/** A node's inputs, preferring an id and falling back to a class so a foreign graph still reads. */
function inputsFor(
  list: [string, GraphNode][],
  id: string,
  type: string,
): Record<string, unknown> | null {
  const byId = list.find(([key]) => key === id);
  if (byId) return byId[1].inputs ?? {};
  const byType = list.find(([, node]) => node.class_type === type);
  return byType ? byType[1].inputs ?? {} : null;
}

/** The first node carrying an input, for a graph whose ids this project did not assign. */
function inputsWith(list: [string, GraphNode][], key: string): Record<string, unknown> | null {
  const found = list.find(([, node]) => node.inputs && key in node.inputs);
  return found ? found[1].inputs ?? null : null;
}

function stringAt(inputs: Record<string, unknown> | null, key: string): string | null {
  const value = inputs?.[key];
  return typeof value === "string" ? value : null;
}

function numberAt(inputs: Record<string, unknown> | null, key: string): number | null {
  const value = inputs?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * The take's identity, read out of an embedded graph.
 *
 * The caption is the encoder's `tags`, which is what the rest of the page calls the caption; the
 * seed is the sampler's, which is the arrangement's seed rather than the language model's. A batch
 * graph carries several captions against one lyric and is read as its first row, which is the only
 * honest reading: one file is one take.
 */
export function tagsFromGraph(graph: unknown): TakeTags | null {
  const list = nodes(graph);
  if (!list.length) return null;

  const encoder =
    inputsFor(list, "4", "TextEncodeAceStepAudio1.5") ??
    inputsWith(list, "tags") ??
    inputsWith(list, "captions");
  if (!encoder) return null;

  const caption =
    stringAt(encoder, "tags") ?? (stringAt(encoder, "captions") ?? "").split("\n")[0].trim();
  const sampler = inputsFor(list, "8", "KSampler") ?? inputsWith(list, "seed");
  return {
    caption,
    lyrics: stringAt(encoder, "lyrics") ?? "",
    seed: numberAt(sampler, "seed") ?? numberAt(encoder, "seed"),
    bpm: numberAt(encoder, "bpm"),
  };
}

/** The take's identity, read out of its bytes. */
export function tagsFromMp3(bytes: Uint8Array): TakeTags | null {
  const graph = graphFromMp3(bytes);
  return graph === null ? null : tagsFromGraph(graph);
}

/** Join accumulated chunks, taking at most `total` bytes. */
function join(chunks: Uint8Array[], total: number): Uint8Array {
  const out = new Uint8Array(total);
  let at = 0;
  for (const chunk of chunks) {
    const take = Math.min(chunk.length, total - at);
    out.set(chunk.subarray(0, take), at);
    at += take;
    if (at >= total) break;
  }
  return out;
}

/**
 * How many bytes the tag occupies, once the header is readable; `0` when this is not an ID3 file.
 *
 * Reading can stop at that size, so the front read neither downloads a whole take nor guesses at a
 * frame length it has only partly seen.
 */
function tagSpan(chunks: Uint8Array[], total: number): number | null {
  if (total < ID3_HEADER) return null;
  const head = join(chunks, ID3_HEADER);
  if (head[0] !== 0x49 || head[1] !== 0x44 || head[2] !== 0x33) return 0;
  return ID3_HEADER + syncsafe(head, 6);
}

async function frontBytes(response: Response, limit: number): Promise<Uint8Array> {
  const reader = response.body?.getReader();
  if (!reader) return new Uint8Array(await response.arrayBuffer());
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
      const span = tagSpan(chunks, total);
      if (span !== null && total >= span) break;
      if (total >= limit) break;
    }
  } finally {
    // A renderer that ignored the Range header would keep sending otherwise.
    await reader.cancel().catch(() => undefined);
  }
  return join(chunks, total);
}

/**
 * Read a take's tags from its playable URL.
 *
 * Every failure is a `null`: a page pointed at a remote renderer may be refused the bytes by CORS,
 * and the station plays on from the history it holds.
 */
export async function readTakeTags(
  url: string,
  fetchImpl: typeof fetch = fetch,
): Promise<TakeTags | null> {
  let response: Response;
  try {
    response = await fetchImpl(url, { headers: { Range: `bytes=0-${FRONT_LIMIT - 1}` } });
  } catch {
    return null;
  }
  if (!response.ok) return null;
  const bytes = await frontBytes(response, FRONT_LIMIT);
  return tagsFromMp3(bytes);
}
