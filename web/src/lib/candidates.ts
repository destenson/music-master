/**
 * Choosing between the drafts a model wrote for one song.
 *
 * A prompt is a question, and a model answers it differently every time it is asked, so the radio
 * asks more than once and keeps the answer it wants. "Wants" is a priority: correctness comes first,
 * then form, then the newest words.
 *
 * The comparison is pure and free of the model, the network and the DOM, so the smoke run checks the
 * priority directly as well as through a generation.
 */

export interface DraftGrade {
  text: string;
  /** Which attempt wrote it, so an exact tie is broken the same way every time. */
  attempt: number;
  /** The checker's errors, weighed before novelty. */
  errors: number;
  warnings: number;
  /** Sections the draft matched, from the conformance check. */
  matched: number;
  /** 0..1 from the text tier: 1 shares nothing with the station's earlier lyrics. */
  novelty: number;
}

/** Whether `a` should be kept over `b`: correctness, then form, then newness, then polish. */
export function better(a: DraftGrade, b: DraftGrade): boolean {
  if (a.errors !== b.errors) return a.errors < b.errors;
  if (a.matched !== b.matched) return a.matched > b.matched;
  if (a.novelty !== b.novelty) return a.novelty > b.novelty;
  if (a.warnings !== b.warnings) return a.warnings < b.warnings;
  // Everything else equal, the earlier attempt wins, so a run is reproducible from its seed.
  return a.attempt < b.attempt;
}

/** The draft to keep, or null when there are none. */
export function bestDraft(grades: readonly DraftGrade[]): DraftGrade | null {
  let best: DraftGrade | null = null;
  for (const grade of grades) {
    if (!best || better(grade, best)) best = grade;
  }
  return best;
}
