/** Pure helpers over a selection set. Kept out of the components so the rules are testable. */
import type { Bin, BinSelection, Selections } from "./types";

export function chosen(selection: BinSelection | undefined): string[] {
  return selection?.options ?? [];
}

export function has(selection: BinSelection | undefined, optionId: string): boolean {
  return chosen(selection).includes(optionId);
}

/**
 * Toggle an option, respecting the bin's cap. At the cap, selecting another is refused rather than
 * silently evicting the oldest: the page shows the cap, so an invisible eviction would be a lie.
 */
export function toggle(
  selection: BinSelection | undefined,
  optionId: string,
  max?: number,
): BinSelection {
  const current = chosen(selection);
  let next: string[];
  if (current.includes(optionId)) {
    next = current.filter((id) => id !== optionId);
  } else if (max !== undefined && current.length >= max) {
    return { ...selection, options: current };
  } else {
    next = [...current, optionId];
  }
  return { ...selection, options: next };
}

export function setSingle(selection: BinSelection | undefined, optionId: string): BinSelection {
  return { ...selection, options: optionId ? [optionId] : [] };
}

export function setValue(selection: BinSelection | undefined, value: number): BinSelection {
  return { ...selection, value };
}

export function setText(selection: BinSelection | undefined, text: string): BinSelection {
  return { ...selection, text: text.trim() === "" ? null : text };
}

export function setKeyMode(
  selection: BinSelection | undefined,
  key: string | null,
  mode: string | null,
): BinSelection {
  return { ...selection, key, mode };
}

export function isBlank(selection: BinSelection | undefined): boolean {
  if (!selection) return true;
  return (
    chosen(selection).length === 0 &&
    (selection.value === undefined || selection.value === null) &&
    !selection.text &&
    !selection.key &&
    !selection.mode
  );
}

/** Bins in the order the vocabulary declares its groups, which is the order the form draws them. */
export function byGroup(bins: Bin[]): { group: string; bins: Bin[] }[] {
  const groups: { group: string; bins: Bin[] }[] = [];
  for (const bin of bins) {
    let entry = groups.find((g) => g.group === bin.group);
    if (!entry) {
      entry = { group: bin.group, bins: [] };
      groups.push(entry);
    }
    entry.bins.push(bin);
  }
  return groups;
}

export function selectedCount(selections: Selections): number {
  return Object.values(selections).reduce((total, sel) => total + chosen(sel).length, 0);
}

/**
 * The labels a bin currently holds, in the order the renderer would emit them.
 *
 * This is what lets a collapsed section stand in for its contents: the same labels the caption
 * shows, not an opaque "3 selected". Metadata bins contribute their value and key here even though
 * they reach no tag, because a collapsed "Tempo" that said nothing would be hiding a decision.
 */
export function labels(bin: Bin, selection: BinSelection | undefined): string[] {
  if (!selection) return [];
  const out: string[] = [];
  const known = new Map((bin.options ?? []).map((option) => [option.id, option.label]));
  for (const id of chosen(selection)) out.push(known.get(id) ?? id);
  if (selection.text) out.push(selection.text);
  if (selection.value !== undefined && selection.value !== null) {
    out.push(`${selection.value}${bin.unit ? ` ${bin.unit}` : ""}`);
  }
  const keyed = [selection.key, selection.mode].filter(Boolean).join(" ");
  if (keyed) out.push(keyed);
  return out;
}

/** Everything a group of bins contributes, as one line. */
export function summarise(bins: Bin[], selections: Selections): string {
  return bins.flatMap((bin) => labels(bin, selections[bin.id])).join(" · ");
}

/** How many bins in a group have been decided, for the collapsed count. */
export function setCount(bins: Bin[], selections: Selections): number {
  return bins.filter((bin) => !isBlank(selections[bin.id])).length;
}
