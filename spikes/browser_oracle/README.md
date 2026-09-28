# Browser oracle spike

Can a small open model running in the browser, with no API key and no server, answer the compliance
battery's semantic questions as typed probabilities that code can consume?

This spike answers the *mechanism* and the *runtime* halves of that question. It does not answer the
quality half on its own, because 16 hand-labelled cases are a smoke test and not a gauge — for that it
defers to the measured ladder in `~/src/TheoLeeCJ--SemIf-OpenJev` (see *Findings* 5).

## The readout

One forward pass over the state and the question, then read the declared option probabilities straight
off the logits at the final position. No token is sampled, nothing is generated, and nothing is parsed
afterwards. `readout.mjs` is environment-agnostic: the Node runner and the browser page import the same
module, so a difference between their numbers is the runtime and not the method.

Two quantities are reported for every answer:

- **the option distribution** — one softmax over the union of every option's token ids, with each
  option's probability being the sum over its own tokens;
- **the option mass** — the share of the model's *entire* next-token distribution that those option
  tokens hold. A model that wanted to answer something else scores low here even when the option
  distribution looks confident. Hosted Jev does not expose this channel; a local readout does.

## Running it

```bash
cd spikes/browser_oracle
npm install --cache ./.npm-cache      # the shared npm cache is outside the workspace here
node selftest.mjs                     # guards the readout arithmetic; needs no model
node node_measure.mjs --models=onnx-community/Qwen3-0.6B-ONNX --dtype=q8
node node_measure.mjs --models=onnx-community/Qwen3-0.6B-ONNX,onnx-community/Qwen3-1.7B-ONNX \
    --dtype=q8 --json=false
```

The browser run needs its own Chromium, kept inside the workspace:

```bash
PLAYWRIGHT_BROWSERS_PATH=./.pw-browsers npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=./.pw-browsers node browser_measure.mjs --device=wasm --dtype=q4f16
```

Model weights are cached under `.cache/`, Chromium under `.pw-browsers/`, and both are ignored by git.
The `page.html` import map points `@huggingface/transformers` at the locally installed
`dist/transformers.min.js`, a self-contained ES module bundle that embeds ONNX Runtime Web, so the page
needs no CDN and `readout.mjs` stays identical in both environments.

## The fixture

`fixtures.mjs` lifts the questions from `docs/design/compliance-architecture.md` §7.2 and crosses them
with four states that vary one thing at a time, so a failure can be attributed: **A** is the matched
case, **B** changes only the lyrics, **C** changes only the caption, **D** changes only the caption to a
deliberate reproduction of the excluded artist's signature. Every case carries a hand label and a
one-line justification, because a benchmark whose labels are secretly wrong measures nothing.

Every result also reports the **constant baseline**: the score a model would get by answering the same
thing every time and never reading the state. A model that scores below it is not merely weak, it is
anti-correlated with the input, and a compliance report built on it would be worse than no report.

## Findings

**1. The mechanism works, and it is about twice as cheap as generate-and-parse.** In Node on CPU, with
Qwen3-0.6B at q8, the readout answered in p50 659 ms against p50 1355 ms for the prompted-JSON baseline
on the same questions. The JSON baseline parsed 16/16 and scored 3/16 correct — the format was never
the problem.

**2. Normalising each option separately is a silent, total failure.** A per-option softmax sums to 1 by
construction, so a two-way question reads exactly `0.500` and a five-level question reads exactly
uniform for *every* input, while still emitting a well-formed probability vector that sums to 1.
`selftest.mjs` pins the joint normalisation, and it is the reason the answer contract needs to state
that the distribution is one softmax over the union of the option token ids.

**3. A confident answer can be one the model never made.** Qwen3-1.7B returned `noul = 1.000` with
`option-mass = 0.000` on several cases: the option distribution was maximally decisive while the model
placed essentially none of its probability mass on the options at all. Mean option mass *fell* from
0.722 at 0.6B to 0.454 at 1.7B even as agreement rose, so the mass is measuring something the
distribution does not. Any oracle should carry it, and treat a low mass as uncertainty regardless of
how decisive the option distribution looks.

**4. At these sizes quality is below a constant baseline.**

| Model | agreement | constant baseline | noul Brier | saturated nouls | p50 |
|---|---:|---:|---:|---:|---:|
| Qwen3-0.6B q8 | 6/16 | 12/16 | 0.482 | 6/8 | 659 ms |
| Qwen3-1.7B q8 | 9/16 | 12/16 | 0.389 | 6/8 | 1274 ms |

A Brier of 0.25 is what a constant `0.5` scores, so both models are worse than a coin flip: their
confidence is anti-correlated with their correctness, and 6 of 8 nouls are saturated beyond `0.95` or
below `0.05`. The improvement from 0.6B to 1.7B is real but does not cross the floor. This is
consistent with the 0.407 agreement the research document records for Qwen3-0.6B.

**5. The runtime decides viability, not the browser.** The in-browser run answered at **p50 16.1 s,
p95 26.0 s** per question (Qwen3-0.6B, q4f16, `device=wasm`, 24 s to load). That is not a browser
limit — it is `onnxruntime-web` under WASM. The sibling project `SemIf` runs the same class of readout
in the browser through **wllama 3.6.1** on WebGPU and measures direct readout at **0.704 s for
Qwen3-0.6B, 1.508 s for MiniCPM5-2B and 3.271 s for Qwen3.5-4B** (Chrome 152 headless, RTX 3090,
weights on local SSD). So the same idea is 5–20× faster on a different runtime, and `transformers.js`
is the wrong vehicle. SemIf also reports its quality ladder on the same interface, which is the number
this spike's own fixture is too small to establish:

| Model | authored144 | TypeSafe102 agreement |
|---|---:|---:|
| Qwen3-0.6B | 0.440 | 0.407 |
| MiniCPM5-2B | 0.686 | 0.637 |
| Qwen3.5-4B | 0.813 | 0.845 |
| Published Jev | — | 0.883 |
| Qwen3.8-27B exl3, local `exllamav3` server | 0.958 | — |

Read the columns separately: the 27B's 0.958 is on `authored144` and no 27B number exists for
TypeSafe102, so it is not a like-for-like comparison with Jev's 0.883.

**6. Not every model that claims `transformers.js` support will load.** `LFM2-700M-ONNX` fails in
Node at every dtype: `GatherBlockQuantized` carries a `bits` attribute the bundled runtime does not
recognise, and the fp32 export fails differently, with `GroupQueryAttention` given 11 inputs where the
bundled schema allows at most 9. Whether a model is loadable must be checked, not assumed.

**7. `q4f16` is a GPU format.** `onnxruntime-node` on CPU refuses it outright
(`Tensor.data must be a typed array (4) for float16 tensors, but got typed array (0)`), so the Node and
browser runs are not a controlled runtime comparison: the browser ran q4f16 and Node ran q8.

## What this does not settle

- **WebGPU latency on this machine was never measured.** The sandbox hides the GPU device nodes, so the
  in-browser run used `device=wasm`. The page takes `--device=webgpu`, and SemIf's numbers are the
  reason to run it that way under a GPU-visible sandbox.
- **Label scheme is untested.** This spike scores `yes`/`no` and the digits 1–5, both of which need
  several token variants. SemIf uses single-token letters (`A`…`T`) with a grammar that constrains the
  readout to those tokens — which removes the problem in Finding 3 by construction rather than
  reporting it. That comparison has not been run here.
- **No comparison against Jev.** No TypeSafe key is configured, so every label is a hand label.
- **Sixteen cases.** Enough to detect gross failure and nothing finer.
