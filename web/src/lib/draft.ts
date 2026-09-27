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
