// The Jev-like primitive, implemented the way SemIf/OpenJev does it: one forward pass over
// the state and the question, then read the declared option probabilities straight off the
// logits. No token is sampled, nothing is generated, and nothing is parsed afterwards.
//
// This file is environment-agnostic on purpose: the Node runner and the browser page import
// the same module, so a difference between their numbers is the runtime, not the method.

import { AutoTokenizer, AutoModelForCausalLM, env } from '@huggingface/transformers';

export const UNCERTAIN_LOW = 0.3;
export const UNCERTAIN_HIGH = 0.7;

// --- model loading ---------------------------------------------------------------------

export async function loadModel(modelId, { dtype = 'q8', device = 'cpu', cacheDir, progress_callback } = {}) {
  if (cacheDir && env.cacheDir !== undefined) env.cacheDir = cacheDir;
  const t0 = Date.now();
  const tokenizer = await AutoTokenizer.from_pretrained(modelId);
  const model = await AutoModelForCausalLM.from_pretrained(modelId, { dtype, device, progress_callback });
  return { modelId, tokenizer, model, loadMs: Date.now() - t0, dtype, device };
}

// --- prompt construction ---------------------------------------------------------------

function renderState(state, maxLyricLines = 24) {
  const lines = [];
  for (const [k, v] of Object.entries(state.brief)) lines.push(`brief.${k}: ${v}`);
  for (const [k, v] of Object.entries(state.measured ?? {})) lines.push(`measured.${k}: ${v}`);
  lines.push(`caption: ${state.caption}`);
  if (state.chords) lines.push(`chords: ${state.chords}`);
  if (state.lyrics) {
    const lyric = state.lyrics.split('\n').slice(0, maxLyricLines).join('\n');
    lines.push(`lyrics:\n${lyric}`);
  }
  return lines.join('\n');
}

function answerInstruction(question) {
  if (question.type === 'noul') {
    const c = question.criteria ?? {};
    const t = c.true ? ` Yes means: ${c.true}` : '';
    const f = c.false ? ` No means: ${c.false}` : '';
    return `Answer with one word, "yes" or "no".${t}${f}`;
  }
  if (question.type === 'score') {
    const opts = question.levels.map((l, i) => `${i + 1} = ${l}`).join('; ');
    return `Answer with a single digit from 1 to 5. ${opts}`;
  }
  throw new Error(`unsupported question type: ${question.type}`);
}

export function buildMessages(question, state) {
  return [
    {
      role: 'system',
      content:
        'You are a strict judge of song descriptions. You answer the question you are given ' +
        'about the supplied state, using only that state. You never explain or add commentary.',
    },
    {
      role: 'user',
      content:
        `State\n-----\n${renderState(state)}\n\n` +
        `Question\n--------\n${question.instructions}\n\n` +
        `${answerInstruction(question)}`,
    },
  ];
}

export function buildPrompt(tokenizer, question, state) {
  const messages = buildMessages(question, state);
  if (typeof tokenizer.apply_chat_template === 'function') {
    try {
      const tpl = tokenizer.apply_chat_template(messages, {
        tokenize: false,
        add_generation_prompt: true,
        enable_thinking: false,
      });
      if (typeof tpl === 'string') return { text: tpl, usedTemplate: true };
    } catch {
      // fall through to the plain rendering below
    }
  }
  const body = messages.map((m) => `${m.role}: ${m.content}`).join('\n\n');
  return { text: `${body}\n\nassistant:`, usedTemplate: false };
}

// --- one forward pass ------------------------------------------------------------------

export function vocabStats(row) {
  let max = -Infinity;
  for (let i = 0; i < row.length; i++) if (row[i] > max) max = row[i];
  let sumExp = 0;
  for (let i = 0; i < row.length; i++) sumExp += Math.exp(row[i] - max);
  return { max, sumExp };
}

// Return logits at the final position, plus the two constants a stable softmax needs, so
// both the restricted-over-options softmax and the full-vocabulary mass can be computed
// from one pass instead of two.
export async function forwardLastRow(loaded, promptText) {
  const inputs = loaded.tokenizer(promptText);
  const out = await loaded.model(inputs);
  const logits = out.logits;
  const dims = logits.dims; // [batch, seq, vocab]
  const [, seq, vocab] = dims;
  const data = logits.data;
  const row = data.subarray((seq - 1) * vocab, seq * vocab);
  return { row, vocab, ...vocabStats(row), promptTokens: seq, dims };
}

function candidateIds(tokenizer, variants) {
  const ids = new Set();
  const first = [];
  for (const text of variants) {
    const enc = tokenizer.encode(text, { add_special_tokens: false });
    const id = Array.isArray(enc) ? enc[0] : enc?.[0];
    if (typeof id === 'number') {
      ids.add(id);
      first.push({ text, id });
    }
  }
  return { ids: [...ids], variants: first };
}

// The declared-option distribution: ONE softmax over the union of every option's token ids,
// with each option's probability being the sum over its own tokens.
//
// Normalising each option on its own is the failure this function exists to prevent, and it
// is a quiet one: a per-option softmax sums to 1 by construction, so a two-way question
// always reads 0.500 and a five-level question always reads uniform, whatever the model
// computed. The output is still a well-formed probability vector.
export function jointSoftmax(row, { max, sumExp }, groups) {
  const all = groups.flatMap((g) => g.ids);
  let m = -Infinity;
  for (const i of all) if (row[i] > m) m = row[i];
  let sum = 0;
  const exps = all.map((i) => {
    const e = Math.exp(row[i] - m);
    sum += e;
    return e;
  });
  const probs = new Array(groups.length).fill(0);
  let k = 0;
  for (let g = 0; g < groups.length; g++) {
    for (let j = 0; j < groups[g].ids.length; j++) probs[g] += exps[k++] / sum;
  }
  // `mass` is the share of the model's *entire* next-token distribution that the declared
  // options hold. A model that wanted to answer something else scores low here even when the
  // restricted distribution looks confident -- the off-canonical channel that hosted Jev
  // does not expose.
  let mass = 0;
  for (const i of all) mass += Math.exp(row[i] - max) / sumExp;
  return { probs, mass };
}

const YES = ['yes', 'Yes', 'YES', ' yes', ' Yes', ' yes.', 'yes.'];
const NO = ['no', 'No', 'NO', ' no', ' No', ' no.', 'no.'];

export async function readNoul(loaded, question, state) {
  const { text, usedTemplate } = buildPrompt(loaded.tokenizer, question, state);
  const fwd = await forwardLastRow(loaded, text);
  const yesIds = candidateIds(loaded.tokenizer, YES);
  const noIds = candidateIds(loaded.tokenizer, NO);
  const { probs, mass } = jointSoftmax(fwd.row, fwd, [yesIds, noIds]);
  const pYes = probs[0];

  const top = pYes >= 0.5 ? 'yes' : 'no';
  return {
    kind: 'noul',
    noul: pYes,
    top,
    uncertain: pYes >= UNCERTAIN_LOW && pYes <= UNCERTAIN_HIGH,
    optionMass: mass,
    optionIds: { yes: yesIds.ids, no: noIds.ids },
    usedTemplate,
    promptTokens: fwd.promptTokens,
    raw: { pYes, pNo: probs[1] },
  };
}

export async function readScore(loaded, question, state) {
  const { text, usedTemplate } = buildPrompt(loaded.tokenizer, question, state);
  const fwd = await forwardLastRow(loaded, text);
  const n = question.levels.length;
  const groups = [];
  for (let i = 1; i <= n; i++) {
    groups.push(candidateIds(loaded.tokenizer, [`${i}`, ` ${i}`, `${i}.`, `${i}:`]));
  }
  const { probs: dist, mass: optionMass } = jointSoftmax(fwd.row, fwd, groups);
  const topIdx = dist.indexOf(Math.max(...dist));
  const expected = dist.reduce((acc, p, i) => acc + p * (i + 1), 0);

  return {
    kind: 'score',
    level: topIdx + 1,
    expected: expected,
    distribution: dist,
    uncertain: dist[topIdx] < 0.6,
    optionMass,
    usedTemplate,
    promptTokens: fwd.promptTokens,
  };
}

export async function readAnswer(loaded, question, state) {
  return question.type === 'noul'
    ? readNoul(loaded, question, state)
    : readScore(loaded, question, state);
}

// --- the baseline the design exists to replace ------------------------------------------

// Ask for JSON and parse it. This is the "prompted LLM + constrained decoding" row of the
// research table, and it is here only to measure the cost the readout avoids.
export async function readAnswerJson(loaded, question, state) {
  const messages = buildMessages(question, state);
  const want = question.type === 'noul' ? '{"answer": "yes"} or {"answer": "no"}' : '{"answer": 1} through {"answer": 5}';
  messages[1] = {
    ...messages[1],
    content: `${messages[1].content}\n\nReply with only the JSON object, nothing else. Example: ${want}`,
  };
  let text;
  try {
    text = loaded.tokenizer.apply_chat_template(messages, {
      tokenize: false,
      add_generation_prompt: true,
      enable_thinking: false,
    });
  } catch {
    text = `${messages.map((m) => `${m.role}: ${m.content}`).join('\n\n')}\n\nassistant:`;
  }
  const inputs = loaded.tokenizer(text);
  const t0 = Date.now();
  const out = await loaded.model.generate({
    ...inputs,
    max_new_tokens: 24,
    do_sample: false,
  });
  const ms = Date.now() - t0;
  const decoded = loaded.tokenizer.batch_decode(out.slice(null, [inputs.input_ids.dims[1], null]), {
    skip_special_tokens: true,
  })[0];
  let parsed = null;
  try {
    parsed = JSON.parse(decoded.trim().match(/\{[^}]*\}/)?.[0] ?? '');
  } catch {
    parsed = null;
  }
  return {
    kind: question.type,
    parsed,
    value: question.type === 'noul' ? parsed?.answer : parsed?.answer,
    decoded: decoded.trim().slice(0, 80),
    generatedMs: ms,
  };
}
