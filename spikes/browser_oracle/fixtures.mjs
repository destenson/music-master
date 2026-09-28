// The question set, lifted from the design document's compliance battery
// (docs/design/compliance-architecture.md §7.2), crossed with four states whose expected
// answers are unambiguous by construction.
//
// This is a smoke-level benchmark, not a gauge. Nothing here comes from Jev, and no answer
// below is a measurement of the *design* -- it is a hand label on a case built so that a
// careful human reader would agree. Where a label is arguable, it says so, because a
// benchmark whose labels are secretly wrong measures nothing.
//
// The states vary one thing at a time so a failure can be attributed: A is the matched
// case, B changes only the lyrics, C changes only the caption, D changes only the caption.

const BRIEF = {
  theme: 'leaving a coastal town in autumn',
  genre: 'indie folk',
  era: 'contemporary',
  exclude_artist: 'Bon Iver',
};

// A: theme present, genre present, not pastiche, wistful.
const STATE_A = {
  brief: BRIEF,
  caption:
    'Sparse fingerpicked acoustic guitar, close female alto, brushed drums entering mid-song, ' +
    'autumn imagery, restrained dynamics, tape-like warmth',
  chords: 'F#m - D - A - E (verse); D - A - E - F#m (chorus)',
  measured: { duration_s: 184.2, tempo_bpm: 90.6, key: 'F# minor', lufs: -11.4 },
  lyrics: [
    '[Verse]',
    'Salt on the window, the last bus is boarding',
    'October is folding the light off the bay',
    'I packed the harbour into one coat pocket',
    'And left you the keys and the grey',
    '',
    '[Chorus]',
    'So long, low tide, I am going inland',
    'Autumn is closing the door on the coast',
    'Keep the town, keep the rain, keep the winter',
    'I will write when I know what I lost',
  ].join('\n'),
};

// B: same caption, different subject, different season. Only `lyrics` changed.
const STATE_B = {
  ...STATE_A,
  lyrics: [
    '[Verse]',
    'Neon is bleeding all over the carpet',
    'July in the city and nobody sleeps',
    'We are the loudest thing under the strobe light',
    'Dancing on glass till the morning comes cheap',
    '',
    '[Chorus]',
    'Turn it up, turn it up, we are not going home',
    'Sunrise is only a rumour they told us',
    'Hands in the air and the bass in our bones',
    'Nothing here ends and nothing here holds us',
  ].join('\n'),
};

// C: same lyrics as A, caption is club music. Only `caption` (and its chords) changed.
const STATE_C = {
  ...STATE_A,
  caption:
    'Four-on-the-floor kick at 128 BPM, sidechained supersaw stabs, pitched vocal chops, ' +
    'club mix, heavy compression, festival drop',
  chords: 'Am - F - C - G (loop)',
  measured: { duration_s: 184.2, tempo_bpm: 128.0, key: 'A minor', lufs: -7.1 },
};

// D: a deliberate reproduction of one artist's signature, for an indie-folk brief.
const STATE_D = {
  ...STATE_A,
  caption:
    "Dense stacked falsetto harmonies, heavy autotune and vocoder on every vocal layer, " +
    "fingerpicked guitar buried under cavernous reverb, a sparse kick drum heartbeat, " +
    "intimate close-mic'd delivery, deliberate lo-fi tape hiss",
  chords: 'D - A - E - F#m (throughout)',
};

export const STATES = { A: STATE_A, B: STATE_B, C: STATE_C, D: STATE_D };

// `expect` is the hand label. For noul: true/false. For score: the 1-5 level a careful
// reader would give, with `tolerance` because ordinal labels are not exact.
export const QUESTIONS = [
  {
    id: 'theme_present',
    type: 'noul',
    instructions:
      'Do `lyrics` and `caption` together convey a song about leaving a coastal town in ' +
      'autumn, rather than about a different subject?',
    criteria: {
      true: 'The departure, the coast, and the autumn season are all identifiable in the words or the described setting.',
      false: 'The song is about a different subject, time, or place.',
    },
    cases: { A: true, B: false, C: true, D: true },
    why: 'A states departure, coast and October. B is a nightclub in July. C keeps the lyrics. D keeps the lyrics.',
  },
  {
    id: 'genre_fidelity',
    type: 'score',
    levels: [
      'A different genre',
      'Same broad family, wrong corner',
      'Recognisably the genre',
      'A clear example of the genre',
      'A textbook example of the genre',
    ],
    instructions: 'How well does `caption`, `chords` and `measured` fit the genre named in `brief.genre`?',
    cases: { A: 4, B: 4, C: 1, D: 4 },
    tolerance: 1,
    why: 'Brief is indie folk. A/B/D are sparse acoustic fingerpicking. C is a 128 BPM supersaw club track.',
  },
  {
    id: 'artist_pastiche',
    type: 'noul',
    instructions:
      "Does the description in `caption`, together with `chords`, `lyrics` and `measured`, " +
      "read as a deliberate imitation of the specific artist named in the brief's exclusion, " +
      'rather than merely sharing a genre with them?',
    criteria: {
      true: "It reproduces that artist's distinctive signature closely enough to be heard as an imitation.",
      false: 'It shares a genre at most; nothing distinctive is reproduced.',
    },
    cases: { A: false, B: false, C: false, D: true },
    why: 'D stacks falsetto, autotune, cavernous reverb and a kick-drum heartbeat: a signature, not a genre. A is plain fingerpicked folk.',
  },
  {
    id: 'mood_wistful',
    type: 'score',
    levels: ['Not wistful at all', 'Slightly', 'Moderately wistful', 'Strongly wistful', 'Defined by wistfulness'],
    instructions: 'How wistful does `caption` and `lyrics` read?',
    cases: { A: 4, B: 1, C: 4, D: 4 },
    tolerance: 1,
    why: 'A/C/D carry loss and October light. B is a euphoric club lyric.',
  },
];

export function casesFor(questionId) {
  const q = QUESTIONS.find((x) => x.id === questionId);
  if (!q) throw new Error(`no such question: ${questionId}`);
  return Object.entries(q.cases).map(([state, expect]) => ({ state, expect }));
}
