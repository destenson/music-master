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
  /**
   * How to tell it: the voice, the address, the way in. A radio station rotates one per song, so a
   * subject that comes back comes back told a different way. Hand-built songs usually have none.
   */
  angle?: string;
  /**
   * What the song is made of — a place, an object, a form. A station rotates one per song, so a
   * subject and a telling that meet again do not meet as the same song. Hand-built songs have none.
   */
  detail?: string;
}

export function buildPrompt({ brief, caption, theme, angle, detail }: PromptInput): string {
  const about =
    theme.trim() || "(unspecified — take the strongest reading of the brief and commit to one idea)";
  const told = (angle ?? "").trim();
  const made = (detail ?? "").trim();
  return `You are writing the lyric for a song. The brief below is a contract: every number in it was
computed from the arrangement, so honour those counts rather than inventing your own.

WHAT THE SONG SOUNDS LIKE
${caption}

WHAT IT SHOULD BE ABOUT
${about}
${told ? `\nHOW IT IS TOLD\n${told}\n` : ""}${made ? `\nWHAT IT IS MADE OF\n${made}\n` : ""}
${brief}

Write the finished lyric now.
- Put each section header on its own line, named exactly as the brief names it, in the brief's order.
- Write every direction as a tag in square brackets, exactly as the brief writes it: \`[Verse 1]\`,
  \`[rap]\`, \`[low energy]\`. Text without brackets is words and gets sung, so a direction written
  bare — \`low energy\` on its own line — is a line the vocalist will sing as a lyric.
- Keep the performance tags the brief lists under their header, one per line, each one bracketed.
- Write the stated number of lines for each section and stay inside that section's syllable budget.
- Where the brief gives a rhyme scheme, follow it.
- Put the transition tag on its own line at the end of the section it leaves, not on the same line
  as the last lyric line, and not in the section it enters.
- Leave the instrumental sections empty: no words, and no \`(instrumental)\` or other note. Nothing
  but a bracketed tag belongs in a section that is not sung.
- A caption word — a genre, an instrument, a delivery or a hook name — is not a lyric. The caption
  above already carries the sound, so never write those words into a section as a line.
${told ? `- Take the angle above as this song's way in: open on the moment or image it names rather than a
  general statement about the subject, and let it decide the hook.
` : ""}${made ? `- Build the song out of the detail above: the place, the object or the form it names is what the
  verses are made of, not something mentioned once on the way to a general statement.
` : ""}- The numbers in the brief — bar counts, seconds, syllable budgets, rhyme schemes, \`energy n/5\` — are
  instructions to you, not lyrics. Never write one into a section; music-master strips such a line
  from a finished draft, but a line you never write is a line it does not have to.
- A caesura marker (/ or |) inside a line marks a phrase break and is never sung. Use it when a line
  would otherwise carry too many syllables in one breath.
- Output the lyric and nothing else: no preamble, no explanation, no markdown fence.`;
}
