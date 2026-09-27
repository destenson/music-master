# Jev, and models like it

Research notes for the Music Master design. Two questions: what is Jev, and what else
could play the same role if the hosted service is not the right fit.

Sources: the live TypeSafe documentation (read directly — `docs.typesafe.ai`), the sibling
integrations on this machine (`~/src/llamas`, `~/src/lance`, `~/src/ai-experiments/opencaw`,
`~/src/ai-experiments/jev-use-cases.md`), and `~/src/TheoLeeCJ--SemIf-OpenJev`. Where a
number is "measured", it came from a run recorded in one of those repos; where it is "read",
it came from a published record.

## 1. What Jev is

Jev is a **System One model**: it takes a `state` (text, or a JSON object/array of text)
and a map of typed `questions`, and returns one typed answer per question. It does not
write prose, does not explain itself, and does not choose its own next action. It is a
decision model, not a chat model, and the design intent is that code keeps control flow
while the model supplies narrow common-sense judgments over unstructured input.

Endpoint: `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer`.

### The three primitives

| Primitive | Question it answers | Answer fields |
| --- | --- | --- |
| `noul` | Is this true? | `noul` — a probability in [0, 1]. No separate confidence |
| `choice` | Which of these options? | `choice`, `probabilities` (distribution), `confidence` |
| `score` | Which level on this scale? | `score` (can land between levels), `legend`, `probabilities`, `confidence` |

`choice` takes a `criteria` map of option → rubric description (max 255 options). `score`
takes an ordered array of levels (2–10). `noul` takes an optional `criteria` describing
what yes and no mean. `instructions` may be a string, object, or array, and can name parts
of the state by backticked dot-and-index path — `ticket.messages[0].text`. Question IDs
are for your code and are never sent to the model.

Two properties are the reason to use this at all rather than a prompting LLM:

- **Every answer is constrained to the options you supplied.** There is no prose to parse
  and no JSON repair path. Code receives a value in the schema it declared.
- **Questions in one request are independent and evaluated in parallel.** One question's
  answer never becomes hidden context for another. Adding questions costs their tokens and
  almost no latency.

### Limits, versions, price

| | |
| --- | --- |
| Model | `jev-1.13.0`; aliases `jev-latest` and `jev-preview` both point at it |
| Price | $42 per billion input tokens; output tokens are free (~$0.00004 per typical decision) |
| Rate limits | 250,000 tokens/sec, 1,200 requests/min — and explicitly dynamic, can change without notice |
| Context | 64k per request; 32k for `state` plus the longest question |
| Input | **Text only.** String, JSON object, or array of text. **No image, audio, or video** |
| Hosting | Hosted only. No open weights, no documented self-hosting |
| Data | Not trained on customer requests; zero-data-retention is an enterprise feature |

The text-only input is the single most important constraint for Music Master. It is not a
detail; it dictates the entire verification architecture (see the design document).

### Errors

`401` bad key, `422` malformed request (a request-construction bug, not retryable), `429`
rate limited, `529` overloaded. Retry `429` and `529` with exponential backoff, honouring
`retry-after` when present. Two construction details cost the sibling projects time and are
worth not rediscovering: a `uid` belongs *inside* an object `state` (a top-level `uid`
returns HTTP 400), and the request body is `{model, state, questions}` with `questions` a
map of question-ID to typed question.

## 2. What it is measured to do well, and badly

### Documented failure modes (TypeSafe's own jaggedness page for 1.13)

| Failure | Consequence for us |
| --- | --- |
| **Literal reading** — answers the question written, not the one meant | Questions must state the exact condition; boundary cases go in `criteria`; phrasing is the main tuning lever |
| **Math, counting, numeric precision** | Never ask it to count syllables, lines, bars, or compare BPM. All arithmetic in code |
| **Date and time comparison** | Not relevant here, but the same rule: extract in the model, compare in code |
| **Indirection** — multi-hop reasoning | One hop per question; point directly at the fields |
| **Large state with irrelevant detail** | Accuracy falls as unrelated content grows. Filter in code first |
| **Adversarial content** — state is not treated as hostile | A lyric could try to steer its own judge. Deterministic gates must be the hard ones |
| **Contradictory instructions and criteria** | Keep the instruction and its criteria aligned |
| **Structural invariants do not hold** | A `noul` and a `choice` over the same thing can disagree; the negation of a noul does not sum to 1. Never assume identities between questions |
| **Generation** | It cannot write the repair. A generative model does |

### Measured profile from the sibling projects

From `~/src/ai-experiments/jev-use-cases.md`, which aggregates three spikes
(`llamas/PRPs/prp-206`, `opencaw/docs/research/jev-decision-spike.md`,
`lance/docs/research/jev-lance-decision-spike.md`):

| Capability | Measured | Source |
| --- | --- | --- |
| Latency | p50 162–192 ms, max ~470 ms | all three |
| Cost | ~$0.00004 per decision | all three |
| Typed output | 0 decode failures across ~9,000+ calls | all three |
| Consistency | noul mean stdev 0.0043–0.0066 (TypeSafe's own cookbook benchmark: 0.0102) | lance, opencaw |
| Intent classification | 96% vs 67% for a rule classifier; 94.8–95.1% micro-accuracy at parity with cloud models at 8–23× less latency | llamas, opencaw |
| Semantic relevance ranking | AUC 0.916–0.979 vs BM25 0.713–0.880 | opencaw |
| Grounding / unsupported-claim detection | AUC 0.906, 85% accuracy; lexical checks caught 0/20 of the same negatives | opencaw |
| Contradiction ranking | AUC 0.909 ranking; absolute values miscalibrated low (means 0.42/0.09) | opencaw |
| Judge / best-of-N selection | 7/7 vs 4/7 for the incumbent "first" strategy; negative control correctly declined at 0.08–0.18 | lance |
| Graded rank scores | within-one-level 18/18, MAE 0.21; bucket boundaries unstable near cuts | lance |
| Adversarial resistance | 20/20 resisted (described in that repo as a smoke test, not a guarantee) | llamas, lance |
| Multilingual parity | 70/70 across es/de/fr/ja/zh/ar/ru | llamas |
| Batching | many nouls in one request held isolation accuracy at 1/10 the calls and ~9× less wall time | opencaw |

Three findings from that work are non-obvious and each contradicts what a naive
integration would assume:

1. **`confidence` is saturated and does not track correctness.** In the llamas spike, mean
   confidence on correct answers was 1.00 and on the incorrect answer 0.97 — a separation
   of about +0.03, and 0 of 29 answers fell below 0.5. The three-band confidence gating
   TypeSafe's own intent-routing pattern suggests would never have fired. The signal that
   discriminates is the **top-two probability margin**, which `confidence` collapses away.
2. **"None of these fit" and "I am unsure" are different signals.** In the same spike,
   `"can you redo that"` returned `unknown` at 0.93 confidence. A consumer must treat them
   separately.
3. **A `choice` must never be consumed without a companion `noul`.** In the negative
   control — a task no candidate could serve — the noul correctly returned 0.18 while the
   choice still named a winner. A choice is *relative*: it settles which option. A noul is
   *absolute* and can be low for all of them.
4. **Adversarial content can hold the pick while moving the absolute signal.** In the lance
   injection probe the `choice` pick did not move and its margin stayed wide (0.72), but
   the companion `noul` fell to 0.44 — inside the uncertainty band. A design that checked
   only the choice would have seen nothing wrong. This is a reason to keep an absolute
   signal on every important judgment and to treat a depressed noul under adversarial
   framing as a finding rather than noise.

One more measured limitation worth stating: an `escalate`-shaped question (asking the model
to decide *that* it is uncertain) came out 0/3 in the lance spike. Uncertainty is derived
from the margin and the band in code, not requested from the model.

The measured profile is a good match for Music Master's needs: cheap enough to check every
candidate against every requirement, fast enough to be interactive, typed enough that the
compliance report is assembled rather than parsed, and strong at exactly the judgments we
need — relevance, grounding, best-of-N selection, and graded ranking.

## 3. What the sibling projects already settled

Their convergence is worth stating plainly, because Music Master should not re-derive it:

- **`~/src/llamas` (PRP-206)** — Jev as an optional decision provider behind an async
  `DecisionProvider` trait held as `Option<Arc<dyn ...>>`, consulted only on the local
  path's uncertain branch, accepted only through a gate, with every failure degrading to
  the local path and a reason code logged. Config stores the env-var *name*, never the
  secret; `enabled: false` by default pending an explicit egress decision.
- **`~/src/lance` (PRP-J01, `spikes/jev`)** — a spike that measured four decisions against
  a privacy-routing constraint, plus a PRP specifying consumption without making a
  local-first architecture depend on a cloud call. Confirms the operating rules above and
  supplies the best-of-N judge evidence.
- **`~/src/ai-experiments/opencaw`** — a phased PRP plus a decision-provider registry
  design, proposing a **replay/mock provider** for tests and a host-supplied provider. Its
  evidence is the strongest for grounding and relevance ranking.
- **`~/src/ai-experiments/jev-use-cases.md`** — a ranked use-case inventory and the
  "operating manual" (below). Its closing suggestion is directly relevant: a single small
  shared client + gate library rather than each project re-deriving it. Three independent
  implementations of the same client already exist in Rust ×2 and Python ×1.

Their shared **operating manual**, which Music Master adopts wholesale:

1. Never consume a `choice` without a companion `noul`.
2. Use the top-two margin, not `confidence`.
3. Uncertainty is an explicit outcome: noul in `[0.30, 0.70]` → review; choice top
   probability below `0.60` → review.
4. Batch independent questions into one request; shortlist state in code first.
5. Pin `jev-1.13.0`, never the alias.
6. Never port a threshold between primitives, questions, or versions; re-measure.
7. Keep arithmetic, counting, dates, and generation in code.
8. Gate egress on the same privacy policy you would apply to any cloud provider.

### 3.1 What already exists to reuse

There is **no shared Jev client library** — `jev-use-cases.md` records that the three
spikes produced three independent implementations and proposes exactly such a library as
the obvious next step. So Music Master would be the fourth implementation unless it lifts
one of these:

| Language | Location | What it contains |
| --- | --- | --- |
| Python | `~/src/lance/spikes/jev/client.py` | `JevClient`, `Noul`/`Choice`/`Score` dataclasses, `Choice.top2_margin()`, `ranked()`, retry on 429/529 |
| Python | `~/src/lance/spikes/jev/run_spike.py` | The uncertainty band (`UNCERTAIN_LOW/HIGH = 0.30/0.70`), question builders, stability and AUC helpers |
| Rust | `~/src/llamas/examples/jev_decision_spike.rs` | `JevClient::ask`, typed `Answer::{Noul,Choice,Score}` decoding, `cost_usd` |
| Rust | `~/src/ai-experiments/opencaw/crates/caw-bench/src/jev.rs` | `caw_bench::jev`, the one genuinely shared module, behind an opt-in `jev` feature flag |
| Rust | `~/src/llamas/tests/jev_decision_regression.rs` | A live contract test pinning `jev-1.13.0`, plus `tests/fixtures/jev/multilingual.json` |
| Rust | `~/src/ai-experiments/jev-local/src/decision.rs` | A local analogue exposing a second uncertainty channel (node mass / off-canonical) that hosted Jev does not |

The Python `lance` client is the closest fit for Music Master's stack and is the natural
starting point. The opencaw module is the better model for *structure*: it wraps the client
behind a feature flag so that a build without the flag has no cloud dependency at all.

Everything else the PRPs propose — `DecisionProvider`, `JevBridge`, `IntentDecision`,
`ModelDecision`, `JevConfig`, a decision-provider registry — is designed but **not
implemented**, so Music Master gets to choose its own seam rather than inherit one.

## 4. The alternatives, if Jev is not the right fit

"Models like Jev" is a real category now, and the choice is not Jev-or-nothing. What
matters for Music Master is the shape of the interface: *typed questions in, calibrated
probabilities out, no generated text to parse*.

| Approach | Typed output | Calibration | Latency / cost | Egress | Notes |
| --- | --- | --- | --- | --- | --- |
| **Jev (hosted)** | By construction | Trained for it (RLCD) | ~100–200 ms, ~$0.00004/decision | Content leaves the machine | The quality reference. Closed, no self-hosting |
| **SemIf / OpenJev** (open, logit readout) | By construction — reads declared option probabilities from logits | Weaker out of the box; per-workload temperature calibration improved ECE from 0.068 to 0.038 | Direct readout 1.02 s for 21 criteria on one RTX 3090 with a 4B model; 20.03 decisions/s with a prefilled shared state; generated-JSON baseline took 5.33 s for the same 21 | **Fully local** | Reproduces the *interface pattern*, not Jev's model. Qwen3.5-4B: 0.813 authored balanced accuracy, 0.845 agreement on the public subset vs Jev's published 0.883. Qwen3-0.6B only 0.407 |
| **`jev-local`** (local analogue) | Yes, noul/choice/score as finite value sets over local llama.cpp logits | Adds a second uncertainty channel — answer-node mass / off-canonical — that hosted Jev does not expose | Local llama.cpp | **Fully local** | Not a Jev reproduction; interesting because the extra uncertainty channel is a real signal a hosted API cannot give you |
| **A fine-tuned small classifier** (ModernBERT/DeBERTa-style) | Yes, for a fixed label set | Reasonably, with calibration | Very fast, CPU-capable | Fully local | Only works for labels known at training time. Loses the "criteria arrive at runtime" property that makes Jev fit arbitrary briefs |
| **GLiNER / zero-shot span models** | Typed spans, not decisions | Not really | Fast | Local options exist | Good at extraction, not at "does this satisfy requirement R" |
| **Prompted LLM + constrained decoding** (grammar/JSON schema) | Yes, structurally | Usually overconfident; needs post-hoc calibration | Slow and expensive per decision | Local or hosted | The thing Jev exists to replace. Fine as a fallback |
| **LLM-as-judge** | No — prose verdicts | Poorly calibrated, position and verbosity biases | Slow, expensive | Usually hosted | Use only for the open-ended "is this actually good" question that no typed primitive captures |
| **Classical ML on Jev's probabilities** | Yes | Whatever you train | Trivial | Local | TypeSafe's own `autoresearch_feature_discovery` cookbook: use the probabilities as features once you have labels |

The practical conclusion for Music Master: **put the oracle behind one small interface and
ship three implementations** — hosted Jev, a local logit-readout model in the SemIf style,
and a replay fixture for tests. Then the egress decision, the quality/cost tradeoff, and
the test suite are all configuration rather than architecture. This is exactly the
provider-registry shape `opencaw` proposed, reduced to the single method the pipeline
actually needs.

The honest caveat: the local option is not parity. On the one public comparison available,
a 4B open baseline sits ~4 points below Jev on agreement and its smallest models are far
worse. A deployment that keeps lyrics on the machine should expect more `uncertain`
verdicts and should treat more requirements as human-review.

## 5. What this means for the design

- **Use Jev for the semantic half only.** Mechanical requirements are computed in code,
  both because code is exact and because Jev's documentation names counting and arithmetic
  as failure modes.
- **Batch aggressively.** A compliance pass over ~30 requirements is one request, roughly a
  fifth of a cent and a few hundred milliseconds — cheap enough to run per candidate in a
  best-of-N loop. Synthesis dominates the budget; the oracle is the cheap part that prevents
  expensive rework.
- **Never let it write.** Jev localises the failure; a generative model performs the repair;
  code routes between them from the failed question IDs.
- **Treat its answers as evidence, not truth.** The compliance report records the model
  version, the probabilities, the margin, and the state the question read, so a wrong
  verdict is traceable to a wrong input.
- **Resolve egress explicitly.** Lyrics carry private intent. Default to the local oracle,
  make the hosted oracle opt-in, never persist the key in config, and document what leaves
  the machine.
