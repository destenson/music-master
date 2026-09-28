/**
 * The prompt handed to a model.
 *
 * The brief it embeds is the one the core prints, so every number in it — bars, seconds, line count,
 * syllable budget and ceiling, rhyme scheme, energy — was computed rather than guessed at. That is
 * the project's first rule applied to generation: the model is never asked to do arithmetic, only
 * the part that is irreducibly a judgement.
 */

export interface PromptInput {
  brief: string;
  /** The rendered caption, so the words agree with the sound the arrangement asks for. */
  caption: string;
  /** What the writer wants it to be about. The one part no amount of code can supply. */
  theme: string;
}

export function buildPrompt({ brief, caption, theme }: PromptInput): string {
  return `You are writing the lyric for a song. The brief below is a contract: every number in it was
computed from the arrangement, so honour those counts rather than inventing your own.

WHAT THE SONG SOUNDS LIKE
${caption}

WHAT IT SHOULD BE ABOUT
${theme.trim() || "(unspecified — take the strongest reading of the brief and commit to one idea)"}

${brief}

Write the finished lyric now.
- Put each section header on its own line, named exactly as the brief names it, in the brief's order.
- Keep the performance tags the brief lists under their header, one per line.
- Write the stated number of lines for each section and stay inside that section's syllable budget.
- Where the brief gives a rhyme scheme, follow it.
- Put the transition tag on the last line of the section it leaves, not the one it enters.
- Write words only for the singable sections; leave the instrumental ones without lyrics.
- The numbers in the brief — bar counts, seconds, syllable budgets, rhyme schemes, \`energy n/5\` — are
  instructions to you, not lyrics. Never write one into a section; music-master strips such a line
  from a finished draft, but a line you never write is a line it does not have to.
- A caesura marker (/ or |) inside a line marks a phrase break and is never sung. Use it when a line
  would otherwise carry too many syllables in one breath.
- Output the lyric and nothing else: no preamble, no explanation, no markdown fence.`;
}
