/**
 * Browser-local draft state.
 *
 * The song directory is the record — `docs/design/ui-plan.md` §7 — and a static page cannot write to
 * it. So what is kept here is explicitly *not* the record: it is a draft that survives a reload, is
 * labelled as a draft in the interface, and can be thrown away in one click to get back to what the
 * repository actually holds.
 */

const PREFIX = "mm.draft.";

export function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

export function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    /* storage can be denied or full; losing a draft is not worth failing a render over */
  }
}

export function clear(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key);
  } catch {
    /* nothing to undo */
  }
}

/**
 * JSON with object keys sorted at every depth.
 *
 * Two selection sets that mean the same thing must compare equal even when one of them gained a bin
 * key later, and plain `JSON.stringify` is insertion-ordered. This is also what makes the save effect
 * read every property, so a change deep inside a selection is noticed.
 */
export function stable(value: unknown): string {
  return JSON.stringify(sort(value));
}

function sort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, entry]) => [key, sort(entry)]),
    );
  }
  return value;
}

/**
 * Named drafts.
 *
 * The single autosave above exists so a reload does not lose an edit. These are the deliberate ones:
 * a name you choose, kept until you delete it, so several directions can exist at once and be
 * switched between. They live in the same browser storage and are equally not the record.
 */
export interface DraftSummary {
  name: string;
  savedAt: string;
  songId: string;
}

const LIBRARY = "names";
const ENTRY = (name: string) => `named.${name}`;

export function listSaved(): DraftSummary[] {
  const index = read<DraftSummary[]>(LIBRARY);
  return Array.isArray(index) ? index : [];
}

/** Store a snapshot under a name, newest first, and return the updated index. */
export function saveNamed(name: string, snapshot: unknown, songId: string): DraftSummary[] {
  write(ENTRY(name), snapshot);
  const index = [
    { name, savedAt: new Date().toISOString(), songId },
    ...listSaved().filter((entry) => entry.name !== name),
  ];
  write(LIBRARY, index);
  return index;
}

export function loadNamed<T>(name: string): T | null {
  return read<T>(ENTRY(name));
}

export function deleteNamed(name: string): DraftSummary[] {
  clear(ENTRY(name));
  const index = listSaved().filter((entry) => entry.name !== name);
  write(LIBRARY, index);
  return index;
}

/**
 * A name that is not already taken, so saving twice does not silently overwrite the first one.
 * Pure, so the rule can be tested without a browser.
 */
export function freeName(base: string, taken: string[]): string {
  const cleaned = base.trim() || "draft";
  if (!taken.includes(cleaned)) return cleaned;
  for (let n = 2; ; n += 1) {
    const candidate = `${cleaned} ${n}`;
    if (!taken.includes(candidate)) return candidate;
  }
}
