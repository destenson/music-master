// Guards the readout arithmetic. Run with `node selftest.mjs`.
//
// This exists because the first version of jointSoftmax normalised each option separately,
// which made a two-way question read exactly 0.500 and a five-level question read exactly
// uniform -- for every input. The output was still a well-formed probability vector, so
// nothing about it looked broken. A test is the only thing that catches that class of bug.

import { jointSoftmax, vocabStats } from './readout.mjs';

let failures = 0;
function check(name, ok, detail = '') {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? ` -- ${detail}` : ''}`);
  if (!ok) failures++;
}

function fakeRow(entries, floor = -20) {
  // A vocabulary just large enough, with the named ids set to the given logits and every
  // other id at a floor value so the full-vocabulary mass is exercised too.
  const vocab = 64;
  const row = new Float32Array(vocab).fill(floor);
  for (const [id, v] of Object.entries(entries)) row[Number(id)] = v;
  return row;
}

console.log('jointSoftmax');

// A decisive two-way question. Per-option normalisation would return 0.5 here.
{
  const row = fakeRow({ 3: 10, 4: 0 });
  const { probs } = jointSoftmax(row, vocabStats(row), [{ ids: [3] }, { ids: [4] }]);
  check('decisive yes/no gives ~1.0, not 0.5', probs[0] > 0.999, `pYes=${probs[0].toFixed(6)}`);
  check('yes/no probabilities sum to 1', Math.abs(probs[0] + probs[1] - 1) < 1e-9);
}

// The off-canonical channel. The options can split decisively between themselves while
// holding almost none of the model's actual probability mass -- the model wanted to answer
// something else entirely. A readout that only ever sees the restricted distribution cannot
// tell this apart from the case above, which is why `mass` is reported alongside it.
{
  const row = fakeRow({ 3: -8, 4: -9 }, 0);
  const { probs, mass } = jointSoftmax(row, vocabStats(row), [{ ids: [3] }, { ids: [4] }]);
  check('restricted readout still looks decisive', probs[0] > 0.7, `pYes=${probs[0].toFixed(4)}`);
  check('while the option mass is near zero', mass < 0.01, `mass=${mass.toExponential(2)}`);
}

// A decisive preference for level 4 of 5. Per-option normalisation would return uniform.
{
  const groups = [1, 2, 3, 4, 5].map((i) => ({ ids: [i] }));
  const row = fakeRow({ 1: -4, 2: -4, 3: -4, 4: 6, 5: -4 });
  const { probs } = jointSoftmax(row, vocabStats(row), groups);
  const top = probs.indexOf(Math.max(...probs)) + 1;
  const expected = probs.reduce((a, p, i) => a + p * (i + 1), 0);
  check('the argmax lands on the favoured level', top === 4, `top=${top}`);
  check('the expectation tracks it, not 3.0', expected > 3.9, `E=${expected.toFixed(3)}`);
  check('the distribution sums to 1', Math.abs(probs.reduce((a, b) => a + b, 0) - 1) < 1e-9);
}

// Multi-token options: an option's probability is the sum over all of its token ids.
{
  const groups = [
    { ids: [7, 8] },
    { ids: [9] },
  ];
  const row = fakeRow({ 7: 5, 8: 5, 9: 5 });
  const { probs } = jointSoftmax(row, vocabStats(row), groups);
  check('a two-token option outweighs a one-token option at equal logits', Math.abs(probs[0] - 2 / 3) < 1e-6, `p=${probs[0].toFixed(4)}`);
}

// Invariance: adding a constant to every candidate logit must not move the distribution.
{
  const groups = [{ ids: [1] }, { ids: [2] }];
  const a = jointSoftmax(fakeRow({ 1: 1, 2: 3 }), vocabStats(fakeRow({ 1: 1, 2: 3 })), groups);
  const b = jointSoftmax(fakeRow({ 1: 101, 2: 103 }), vocabStats(fakeRow({ 1: 101, 2: 103 })), groups);
  check('shift invariance', Math.abs(a.probs[0] - b.probs[0]) < 1e-9);
}

console.log(failures ? `\n${failures} failure(s)` : '\nall checks passed');
process.exitCode = failures ? 1 : 0;
