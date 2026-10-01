/**
 * Naming for a station's rendered takes, reading them back out of the renderer's history, and
 * grouping takes that share a lyric.
 *
 * A take's file name carries what is needed to place it without its plan: the station, the song's
 * position, and whether it is instrumental. That is what lets a station recover the songs it has
 * already rendered — from browser storage or from the renderer's own history — and start playing
 * them instead of rendering a replacement first.
 *
 * A take's *identity* — its caption, lyrics, seed and tempo — is best read from the file itself,
 * which is what `mp3.ts` does; the graph in a history entry is the same information while the
 * renderer still remembers it. `tagsFromGraph` reads either shape. Because the lyrics are then
 * ordinary text, two takes that sing the same words can be found by comparison alone: a lyric
 * fingerprint decides what "the same words" means, and `renditionLabels` says which takes of a
 * group are renditions of one song.
 *
 * The parsing is pure and free of the DOM and the network, so the smoke test can check both the name
 * grammar and the history shapes without a browser. ComfyUI has recorded a history entry's graph in
 * two different places across versions, and that is exactly the kind of thing a test should pin.
 */
import type { OutputFile } from "./comfy";
import { tagsFromGraph, type TakeTags } from "./mp3.ts";

export interface TakeName {
  /** The take number the renderer gave the file, which is also the order it was rendered in. */
  order: number;
  instrumental: boolean;
}

/** A take the renderer still remembers, with what its graph recorded. */
export interface ExistingTake extends OutputFile {
  /** The caption the take was rendered with, when the history still carries the graph. */
  caption: string;
  /** The words the take sang, empty for an instrumental. */
  lyrics: string;
  seed: number | null;
}

/** Where a take sits among the takes that sing the same words. */
export interface Rendition {
  /** 1-based, in the order the takes were found. */
  position: number;
  total: number;
}

function escape(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The kind and number in a take's file name, or null when it is not this station's take.
 *
 * The station id is anchored at the start rather than searched for, because one station's id can be
 * a prefix of another's — `neon-drive` and `neon-drive-b-sides` — and a loose match would file one
 * station's songs under the other.
 *
 * The number is the renderer's own counter. It counts per prefix, and an instrumental take is a
 * different prefix, so a sung and an instrumental take can share a number; the kind in the name is
 * what tells them apart.
 */
export function parseTakeName(stationId: string, filename: string): TakeName | null {
  const pattern = new RegExp(`^${escape(stationId)}(-instrumental)?_(\\d+)\\.[A-Za-z0-9]+$`);
  const match = pattern.exec(filename);
  if (!match) return null;
  return { order: Number(match[2]), instrumental: Boolean(match[1]) };
}

/** The key a take is unique by in the renderer's output tree. */
export function takeKey(file: OutputFile): string {
  return `${file.subfolder}/${file.filename}`;
}

/**
 * The rendered takes under one subfolder, from a `/history` payload.
 *
 * Only `output` files count — a preview lands in `temp` and is not a take — and the subfolder is
 * matched exactly rather than by prefix, so `radio/neon-drive` cannot collect a differently named
 * station's songs. Duplicates (the same file reported by two nodes) are collapsed by their path.
 *
 * ComfyUI has recorded the prompt as the bare API graph and, in other versions, as the queue tuple
 * `[number, prompt_id, graph, extra_data, outputs]`. Both are read by `tagsFromGraph` rather than
 * betting on one, because the two shapes are a version apart and a station that cannot read its own
 * history would silently re-render songs it already has.
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
    const tags: TakeTags | null = tagsFromGraph(record.prompt);

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
            caption: tags?.caption ?? "",
            lyrics: tags?.lyrics ?? "",
            seed: tags?.seed ?? null,
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

/**
 * The words of a lyric, with the staging stripped out, or `null` when there are no words.
 *
 * Section markers (`[Chorus]`) and instrumental notes (`(instrumental)`) are directions to the
 * model, not words anyone sings, so two renditions of one song compare equal however each one was
 * staged — the same words in a different structure are the same song, arranged differently.
 *
 * The `null` is the important case. An instrumental take still carries a lyric of markers alone,
 * often the very same ones another instrumental was given, so a fingerprint over the raw text would
 * declare every instrumental of a genre — or of three genres — to be one song. A take with no words
 * belongs to no group.
 */
export function lyricFingerprint(lyrics: string): string | null {
  const words = lyrics
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\([^)]*\)/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  return words.length ? words.join(" ") : null;
}

/**
 * Where each take sits among the takes that sing the same words, aligned by index.
 *
 * A take with no words, or the only take of its words, gets `null`: it is not a rendition of
 * anything, and saying so is better than inventing a group of one. Positions follow the order the
 * takes were given in, so the earliest rendering of a lyric is the first rendition.
 */
export function renditionLabels(takes: readonly { lyrics?: string }[]): (Rendition | null)[] {
  const groups = new Map<string, number[]>();
  takes.forEach((take, index) => {
    const key = lyricFingerprint(take.lyrics ?? "");
    if (!key) return;
    const group = groups.get(key);
    if (group) group.push(index);
    else groups.set(key, [index]);
  });

  const labels: (Rendition | null)[] = takes.map(() => null);
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    group.forEach((index, position) => {
      labels[index] = { position: position + 1, total: group.length };
    });
  }
  return labels;
}
