// Measures the readout method in Node (onnxruntime-node, CPU).
//
// This is deliberately NOT the browser number. It answers one question -- does reading
// option probabilities off a small model's logits yield usable typed answers on real
// battery questions? -- because if the answer is no, the browser question is moot. The
// browser run (browser_measure.mjs) measures latency and feasibility separately.

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { QUESTIONS, STATES } from './fixtures.mjs';
import { loadModel, readAnswer, readAnswerJson, UNCERTAIN_LOW, UNCERTAIN_HIGH } from './readout.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

const args = new Map(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, '').split('=');
    return [k, v.join('=') || 'true'];
  }),
);

const MODELS = (args.get('models') ?? 'onnx-community/Qwen3-0.6B-ONNX').split(',').map((s) => s.trim());
const DTYPE = args.get('dtype') ?? 'q8';
const WITH_JSON = args.get('json') !== 'false';
const CACHE = join(HERE, '.cache');

const cases = [];
for (const q of QUESTIONS) {
  for (const [stateKey, expect] of Object.entries(q.cases)) {
    cases.push({ question: q, stateKey, state: STATES[stateKey], expect });
  }
}

function pct(n, d) {
  return d === 0 ? '  n/a' : `${((100 * n) / d).toFixed(0).padStart(3)}%`;
}

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const i = Math.min(sorted.length - 1, Math.floor(q * sorted.length));
  return sorted[i];
}

// The score a model gets by answering the same thing every time and never reading the state.
// This is the number that matters: a small model that scores below it is not merely weak, it
// is anti-correlated with the input, and a compliance report built on it would be worse than
// no report at all. It is also a floor any published agreement number should be read against.
function constantBaseline(rowsForQuestion, question) {
  const n = rowsForQuestion.length;
  if (question.type === 'noul') {
    const yes = rowsForQuestion.filter((r) => r.expect === true).length;
    return Math.max(yes, n - yes);
  }
  let best = 0;
  for (let lvl = 1; lvl <= question.levels.length; lvl++) {
    const ok = rowsForQuestion.filter((r) => Math.abs(lvl - r.expect) <= (question.tolerance ?? 0)).length;
    best = Math.max(best, ok);
  }
  return best;
}

// A model in the ladder can fail to load for reasons that have nothing to do with the
// readout: an ONNX graph exported for a newer runtime than the one bundled here is simply
// not loadable, at any dtype. That is a result worth recording, so a failure is caught and
// turned into a row rather than ending the run.
async function loadWithFallback(modelId, dtype) {
  let lastErr;
  for (const d of [...new Set([dtype, 'q4', 'fp16', 'fp32'])]) {
    try {
      const loaded = await loadModel(modelId, { dtype: d, device: 'cpu', cacheDir: CACHE });
      if (d !== dtype) console.warn(`  ! using dtype=${d} (${dtype} was not loadable)`);
      return loaded;
    } catch (err) {
      lastErr = err;
      console.warn(`  ! dtype=${d}: ${err.message.split('\n')[0].slice(0, 140)}`);
    }
  }
  throw lastErr;
}

const summaries = [];

for (const modelId of MODELS) {
  console.log(`\n=== ${modelId} (dtype=${DTYPE}, cpu) ===`);
  let loaded;
  try {
    loaded = await loadWithFallback(modelId, DTYPE);
  } catch (err) {
    const msg = err.message.split('\n')[0];
    console.error(`  ! NOT LOADABLE by this runtime: ${msg}`);
    summaries.push({ modelId, error: msg });
    continue;
  }
  console.log(`loaded in ${(loaded.loadMs / 1000).toFixed(1)}s`);

  const rows = [];
  for (const c of cases) {
    const t0 = Date.now();
    const ans = await readAnswer(loaded, c.question, c.state);
    const ms = Date.now() - t0;

    let correct;
    let brier = null;
    if (c.question.type === 'noul') {
      correct = ans.top === (c.expect ? 'yes' : 'no');
      brier = (ans.noul - (c.expect ? 1 : 0)) ** 2;
    } else {
      correct = Math.abs(ans.level - c.expect) <= (c.question.tolerance ?? 0);
    }

    rows.push({ ...c, ans, ms, correct, brier });
    const shown =
      c.question.type === 'noul'
        ? `noul=${ans.noul.toFixed(3)} top=${ans.top}`
        : `level=${ans.level} exp=${ans.expected.toFixed(2)}`;
    console.log(
      `  ${c.question.id.padEnd(16)} ${c.stateKey}  ${shown.padEnd(28)} ` +
        `want=${String(c.expect).padEnd(5)} ${correct ? 'ok ' : 'MISS'} ` +
        `mass=${ans.optionMass.toFixed(3)} ${String(ms).padStart(5)}ms`,
    );
  }

  // Per-question agreement, each against the score a constant answer would have got.
  console.log('  --- agreement (vs. answering the same thing every time) ---');
  let nCorrect = 0;
  let nConstant = 0;
  const perQuestion = {};
  for (const q of QUESTIONS) {
    const r = rows.filter((x) => x.question.id === q.id);
    const ok = r.filter((x) => x.correct).length;
    const base = constantBaseline(r, q);
    nCorrect += ok;
    nConstant += base;
    perQuestion[q.id] = { correct: ok, total: r.length, constant: base };
    console.log(`    ${q.id.padEnd(16)} ${ok}/${r.length}   constant baseline ${base}/${r.length}`);
  }
  console.log(
    `    ${'OVERALL'.padEnd(16)} ${nCorrect}/${rows.length}   constant baseline ${nConstant}/${rows.length}` +
      `${nCorrect <= nConstant ? '  <-- does not beat a constant' : ''}`,
  );

  const lat = rows.map((r) => r.ms).sort((a, b) => a - b);
  const briers = rows.filter((r) => r.brier !== null).map((r) => r.brier);
  const nouls = rows.filter((r) => r.question.type === 'noul').map((r) => r.ans.noul);
  const uncertain = nouls.filter((p) => p >= UNCERTAIN_LOW && p <= UNCERTAIN_HIGH).length;
  const saturated = nouls.filter((p) => p > 0.95 || p < 0.05).length;
  const masses = rows.map((r) => r.ans.optionMass);
  const meanMass = masses.reduce((a, b) => a + b, 0) / masses.length;

  console.log(
    `  latency p50=${quantile(lat, 0.5)}ms p95=${quantile(lat, 0.95)}ms | ` +
      `noul brier=${(briers.reduce((a, b) => a + b, 0) / briers.length).toFixed(3)} | ` +
      `uncertain ${uncertain}/${nouls.length} saturated ${saturated}/${nouls.length} | ` +
      `mean option-mass=${meanMass.toFixed(3)}`,
  );

  let json = null;
  if (WITH_JSON) {
    console.log('  --- prompted-JSON baseline (same questions) ---');
    try {
      let jCorrect = 0;
      let jParsed = 0;
      const jLat = [];
      for (const c of rows) {
        const t0 = Date.now();
        const got = await readAnswerJson(loaded, c.question, c.state);
        jLat.push(Date.now() - t0);
        const v = got.parsed?.answer;
        if (v !== undefined && v !== null) {
          jParsed++;
          const okc =
            c.question.type === 'noul'
              ? String(v).toLowerCase().startsWith(c.expect ? 'y' : 'n')
              : Number(v) === c.expect;
          if (okc) jCorrect++;
        }
      }
      const js = jLat.sort((a, b) => a - b);
      console.log(
        `    parsed ${jParsed}/${rows.length}, correct ${jCorrect}/${rows.length} | ` +
          `latency p50=${quantile(js, 0.5)}ms p95=${quantile(js, 0.95)}ms`,
      );
      json = { parsed: jParsed, correct: jCorrect, p50: quantile(js, 0.5), p95: quantile(js, 0.95) };
    } catch (err) {
      // The readout numbers are the point of this run; a failure in the comparison baseline
      // must not take them down with it.
      console.warn(`    ! baseline failed: ${err.message.split('\n')[0]}`);
      json = { error: String(err.message).split('\n')[0] };
    }
  }

  summaries.push({
    modelId,
    dtype: loaded.dtype,
    loadMs: loaded.loadMs,
    overall: { correct: nCorrect, total: rows.length, constant: nConstant },
    perQuestion,
    latency: { p50: quantile(lat, 0.5), p95: quantile(lat, 0.95) },
    calibration: {
      brier: briers.reduce((a, b) => a + b, 0) / briers.length,
      uncertainNouls: uncertain,
      totalNouls: nouls.length,
      saturatedNouls: saturated,
      meanOptionMass: meanMass,
    },
    json,
    rows: rows.map((r) => ({
      question: r.question.id,
      state: r.stateKey,
      expect: r.expect,
      correct: r.correct,
      noul: r.ans.noul ?? null,
      level: r.ans.level ?? null,
      optionMass: r.ans.optionMass,
      usedTemplate: r.ans.usedTemplate,
      optionIds: r.ans.optionIds ?? null,
      promptTokens: r.ans.promptTokens,
      ms: r.ms,
    })),
  });

  await loaded.model.dispose?.();
}

mkdirSync(join(HERE, 'results'), { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const out = join(HERE, 'results', `node-${stamp}.json`);
writeFileSync(out, JSON.stringify({ dtype: DTYPE, withJson: WITH_JSON, summaries }, null, 2));
console.log(`\nwrote ${out}`);
