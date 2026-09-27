/**
 * Naming for a station's rendered takes, and reading them back out of the renderer's history.
 *
 * A take's file name carries what is needed to place it without its plan: the station, the song's
 * position, and whether it is instrumental. That is what lets a station recover the songs it has
 * already rendered — from browser storage or from the renderer's own history — and start playing
 * them instead of rendering a replacement first.
 *
 * The parsing is pure and free of the DOM and the network, so the smoke test can check both the name
 * grammar and the history shapes without a browser. ComfyUI has recorded a history entry's graph in
 * two different places across versions, and that is exactly the kind of thing a test should pin.
 */
import type { OutputFile } from "./comfy";

export interface TakeName {
  index: number;
  instrumental: boolean;
}

/** A take the renderer still remembers, with what its graph recorded. */
export interface ExistingTake extends OutputFile {
  /** The caption the take was rendered with, when the history still carries the graph. */
  caption: string;
  seed: number | null;
}

function escape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The position and kind in a take's file name, or null when it is not this station's take.
 *
 * The station id is anchored at the start rather than searched for, because one station's id can be
 * a prefix of another's — `neon-drive` and `neon-drive-b-sides` — and a loose match would file one
 * station's songs under the other.
 */
export function parseTakeName(stationId: string, filename: string): TakeName | null {
  const pattern = new RegExp(`^${escape(stationId)}-(\\d+)(-instrumental)?_\\d+\\.[A-Za-z0-9]+$`);
  const match = pattern.exec(filename);
  if (!match) return null;
  return { index: Number(match[1]), instrumental: Boolean(match[2]) };
}

/** The key a take is unique by in the renderer's output tree. */
export function takeKey(file: OutputFile): string {
  return `${file.subfolder}/${file.filename}`;
}

/**
 * The graph inside a history entry.
 *
 * ComfyUI has recorded the prompt as the bare API graph and, in other versions, as the queue tuple
 * `[number, prompt_id, graph, extra_data, outputs]`. Both are read here rather than betting on one,
 * because the two shapes are a version apart and a station that cannot read its own history would
 * silently re-render songs it already has.
 */
function graphOf(prompt: unknown): Record<string, { inputs?: Record<string, unknown> }> | null {
  if (Array.isArray(prompt)) {
    const graph = prompt.find(
      (part) => part && typeof part === "object" && !Array.isArray(part) && "4" in part,
    );
    return (graph as Record<string, { inputs?: Record<string, unknown> }> | undefined) ?? null;
  }
  if (prompt && typeof prompt === "object") {
    return prompt as Record<string, { inputs?: Record<string, unknown> }>;
  }
  return null;
}

/**
 * The rendered takes under one subfolder, from a `/history` payload.
 *
 * Only `output` files count — a preview lands in `temp` and is not a take — and the subfolder is
 * matched exactly rather than by prefix, so `radio/neon-drive` cannot collect a differently named
 * station's songs. Duplicates (the same file reported by two nodes) are collapsed by their path.
 */
export function takesFromHistory(history: unknown, subfolder: string): ExistingTake[] {
  if (!history || typeof history !== "object") return [];
  const out: ExistingTake[] = [];
  const seen = new Set<string>();

  for (const entry of Object.values(history as Record<string, unknown>)) {
    if (!entry || typeof entry !== "object") continue;
    const record = entry as {
      prompt?: unknown;
      outputs?: Record<string, Record<string, unknown>>;
    };
    const graph = graphOf(record.prompt);
    const caption = String(graph?.["4"]?.inputs?.tags ?? "");
    const rawSeed = graph?.["8"]?.inputs?.seed;
    const seed = typeof rawSeed === "number" ? rawSeed : null;

    for (const node of Object.values(record.outputs ?? {})) {
      if (!node || typeof node !== "object") continue;
      for (const value of Object.values(node)) {
        if (!Array.isArray(value)) continue;
        for (const item of value) {
          if (!item || typeof item !== "object" || !("filename" in item)) continue;
          const file = item as { subfolder?: string; filename: string; type?: string };
          const where = file.subfolder ?? "";
          if (where !== subfolder) continue;
          if ((file.type ?? "output") !== "output") continue;
          const take: ExistingTake = {
            filename: file.filename,
            subfolder: where,
            type: file.type ?? "output",
            caption,
            seed,
          };
          if (seen.has(takeKey(take))) continue;
          seen.add(takeKey(take));
          out.push(take);
        }
      }
    }
  }
  return out;
}
