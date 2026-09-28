<script lang="ts">
  import { tick } from "svelte";
  import type { MusicMasterCore } from "./core";
  import {
    callJev,
    jevEndpoint,
    jevKey,
    jevModel,
    jevRemembered,
    setJevEndpoint,
    setJevKey,
    setJevModel,
  } from "./jev";
  import type {
    ComplianceCounts,
    ComplianceReport,
    ComplianceVerdict,
    MechanicalVerdict,
    Selections,
  } from "./types";

  let {
    core,
    songId,
    selections,
    bpm,
    duration,
    templateId,
    lyrics,
    caption,
    theme,
    artistReferences,
    onRepair,
  }: {
    core: MusicMasterCore;
    songId: string;
    selections: Selections;
    bpm: number;
    duration: number | null;
    templateId: string;
    lyrics: string;
    /** The rendered caption, which the battery's semantic questions quote. */
    caption: string;
    theme: string;
    /** The comma-separated exclusions the page holds, already split into fields. */
    artistReferences: string[];
    /**
     * Rewrite the lyric from code-derived repair instructions, and resolve with the text it wrote.
     * Absent when no generator is configured, in which case the report still suggests the change and
     * offers no button.
     */
    onRepair?: (instructions: string) => Promise<string | void> | string | void;
  } = $props();

  // The key is never read back into the input: a saved secret rendered on screen is no longer a
  // secret, so the field starts empty and the stored state is reported instead of shown.
  let keyInput = $state("");
  let remember = $state(jevRemembered());
  let hasKey = $state(jevKey() !== "");
  let endpoint = $state(jevEndpoint());
  let modelValue = $state(jevModel());

  // In development the dev server relays the call and holds the key, so the page neither shows a
  // key field nor needs one. A static build has no relay, so there the user supplies a key.
  const dev = import.meta.env.DEV;

  let busy = $state(false);
  let report = $state<ComplianceReport | null>(null);
  let errorText = $state<string | null>(null);
  let controller: AbortController | null = null;

  // The check always runs: the caption's properties are decided in code and need no key. Only the
  // lyric questions need the oracle, and their absence is a degradation the report states rather
  // than a reason to disable the button.
  const canCheck = $derived(!!core && !busy);

  const keyState = $derived(
    dev
      ? "key from the dev server"
      : hasKey
        ? remember
          ? "remembered on this device"
          : "saved for this tab"
        : "no key yet",
  );

  const counts = $derived.by((): Required<ComplianceCounts> | null => {
    if (!report) return null;
    const derived = deriveCounts(report.verdicts);
    return {
      met: report.counts?.met ?? derived.met,
      total: report.counts?.total ?? derived.total,
      decided_by_measurement: report.counts?.decided_by_measurement ?? derived.decided_by_measurement,
      decided_by_description: report.counts?.decided_by_description ?? derived.decided_by_description,
      uncertain: report.counts?.uncertain ?? derived.uncertain,
      unverified: report.counts?.unverified ?? derived.unverified,
    };
  });

  const unverifiedRows = $derived(
    (report?.verdicts ?? []).filter((verdict) => verdict.verdict === "unverified"),
  );

  /** What the user has to act on, worst first: an unmet hard requirement before an uncertain soft one. */
  const attentionRows = $derived.by(() => {
    const rank = (verdict: ComplianceVerdict) =>
      (verdict.severity === "hard" || verdict.severity === "policy" ? 0 : 2) +
      (verdict.verdict === "unmet" ? 0 : 1);
    return (report?.verdicts ?? [])
      .filter((verdict) => verdict.verdict === "unmet" || verdict.verdict === "uncertain")
      .sort((a, b) => rank(a) - rank(b));
  });

  /** The subset a rewrite can satisfy, which is what the auto-fix button acts on. */
  const repairable = $derived(attentionRows.filter((verdict) => (verdict.repair_instruction ?? "").trim() !== ""));

  let repairing = $state(false);
  /** What the last repair actually achieved, so a rewrite that changed nothing says so. */
  let notice = $state<string | null>(null);

  /** The hard and policy requirements the report does not pass, which is what a repair is for. */
  function failingIds(): string[] {
    return (report?.verdicts ?? [])
      .filter(
        (verdict) =>
          verdict.verdict !== "met" &&
          (verdict.severity === "hard" || verdict.severity === "policy"),
      )
      .map((verdict) => verdict.requirement_id);
  }

  /**
   * Rewrite the lyric from the code-derived instructions, then check it.
   *
   * The suggestions come from `musicmaster.repairs`, so the generator is told exactly what the
   * failed checks localised rather than being asked to critique its own output. The text the repair
   * returns is checked directly rather than read back off the prop, and the report's digest says
   * which text was judged, so "it ran again and nothing changed" can be told apart from "it judged
   * the same text again".
   */
  /** What the last repair actually achieved, said plainly rather than left to be inferred. */
  function reportOutcome(failingBefore: string[], digestBefore: string | null): void {
    const digestAfter = report?.checked ?? null;
    if (!report) {
      notice = "The re-check did not run, so nothing here is about the new lyric.";
    } else if (digestBefore && digestAfter === digestBefore) {
      notice = "The rewrite came back with the same text, so the check judged the same lyric again.";
    } else {
      const still = failingIds().filter((id) => failingBefore.includes(id));
      if (still.length) notice = `The rewrite did not resolve: ${still.join(", ")}.`;
    }
  }

  async function autoFix(): Promise<void> {
    if (!onRepair || repairing || repairable.length === 0) return;
    repairing = true;
    errorText = null;
    notice = null;
    const failingBefore = failingIds();
    const digestBefore = report?.checked ?? null;
    const lyricsBefore = lyrics;
    try {
      const instructions = repairable.map((verdict) => `- ${verdict.repair_instruction}`).join("\n");
      const rewritten = await onRepair(instructions);
      await tick();
      await check(typeof rewritten === "string" && rewritten.trim() ? rewritten : undefined);
      reportOutcome(failingBefore, digestBefore);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      // A repair can stream a new lyric and then fail. Check what is actually there rather than
      // leaving the report describing the text from before it.
      await tick();
      if (lyrics !== lyricsBefore) await check();
      errorText = message;
    } finally {
      repairing = false;
    }
  }

  /** The counts are derived from the verdicts rather than trusted, so a report without them still
   * shows the numbers the design is built around. */
  function deriveCounts(verdicts: ComplianceVerdict[]): Required<ComplianceCounts> {
    const of = (value: ComplianceVerdict["verdict"]) =>
      verdicts.filter((verdict) => verdict.verdict === value).length;
    const metBy = (evidence: ComplianceVerdict["evidence_class"]) =>
      verdicts.filter((verdict) => verdict.verdict === "met" && verdict.evidence_class === evidence)
        .length;
    return {
      met: of("met"),
      total: verdicts.length,
      decided_by_measurement: metBy("measurement"),
      decided_by_description: metBy("description"),
      uncertain: of("uncertain"),
      unverified: of("unverified"),
    };
  }

  function persistKey(): void {
    const value = keyInput.trim();
    if (!value) return;
    setJevKey(value, remember);
    keyInput = "";
    hasKey = jevKey() !== "";
  }

  function toggleRemember(next: boolean): void {
    remember = next;
    const value = keyInput.trim() || jevKey();
    if (value) {
      setJevKey(value, remember);
      keyInput = "";
      hasKey = jevKey() !== "";
    } else {
      setJevKey("", remember);
    }
  }

  function isAbort(cause: unknown): boolean {
    return (
      typeof cause === "object" &&
      cause !== null &&
      (cause as { name?: string }).name === "AbortError"
    );
  }

  /**
   * The whole flow: the page's draft becomes a spec and a Jev body, the body is posted, and the
   * answers (or the reason there are none) become the report. A failed call still produces a
   * report, because "the oracle was not reached" is a verdict about every semantic requirement and
   * the honest one to show.
   */
  async function check(lyricsOverride?: string): Promise<void> {
    if (!core || busy) return;
    const typed = keyInput.trim();
    if (!dev) persistKey();
    // Persist an edited endpoint or model, but only when it differs from what is stored: writing
    // the development default to storage would follow the browser into a static build.
    if (endpoint !== jevEndpoint()) setJevEndpoint(endpoint);
    if (modelValue !== jevModel()) setJevModel(modelValue);
    const key = typed || jevKey();

    busy = true;
    errorText = null;
    notice = null;
    report = null;
    controller = new AbortController();

    let spec: unknown = null;
    let state: unknown = null;
    let mechanical: MechanicalVerdict[] = [];
    let answerModel = modelValue;
    let response: unknown = null;
    let failure: string | null = null;

    try {
      const prepared = core.jevRequest({
        selections,
        bpm,
        duration_s: duration,
        template_id: templateId || null,
        lyrics: lyricsOverride ?? lyrics,
        caption,
        theme,
        artist_references: artistReferences,
        model: modelValue,
      });
      spec = prepared.spec;
      state = prepared.request.state;
      mechanical = prepared.mechanical ?? [];
      answerModel = prepared.request.model || modelValue;

      if (dev || key) {
        try {
          response = await callJev(prepared.request, { key, endpoint, signal: controller.signal });
        } catch (cause) {
          if (isAbort(cause)) return;
          failure = cause instanceof Error ? cause.message : String(cause);
          errorText = failure;
        }
      } else {
        // No key is not a failure. The caption's properties are decided in code whatever happens,
        // and the lyric questions report `unverified` with this as their reason rather than the
        // page refusing to run.
        failure = "no oracle key, so the lyrics were not judged; the caption was checked in code";
      }

      try {
        report = core.complianceReport({
          spec,
          state,
          model: answerModel,
          response,
          error: failure,
          song_id: songId,
          mechanical,
        });
      } catch (cause) {
        errorText = errorText ?? (cause instanceof Error ? cause.message : String(cause));
      }
    } catch (cause) {
      // The request could not be built, so there is no spec for a report to describe.
      errorText = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
      controller = null;
    }
  }
</script>

<div class="stack">
  <section class="card">
    <div class="row">
      <h2>Pre-render check</h2>
      <span class="chip" class:meta={!hasKey}>{keyState}</span>
    </div>

    <p class="small" style="margin:0">
      Checks the two text artifacts before a render is spent on them. The <strong>caption</strong> is
      decided in code — every tag you selected has to appear in the string that will be sent — and
      needs no key. The <strong>lyrics</strong> are judged one requirement at a time, and those rows
      are <code>unverified</code> whenever the oracle is not reached.
    </p>

    {#if dev}
      <p class="small" style="margin:0">
        In development the lyric request goes through this page's own dev server at <code>/jev</code>,
        which adds <code>TYPESAFE_API_KEY</code> from its environment — the key never enters this
        browser, and the call is same-origin so CORS does not apply. The caption and the lyrics still
        leave this machine for <code>api.typesafe.ai</code>.
      </p>
    {:else}
      <p class="small" style="margin:0">
        Pressing <strong>check</strong> sends the song's caption and lyrics to <code>{endpoint}</code>
        for a Jev judgement; the caption is checked here either way. Nothing else leaves this machine:
        the key, the selections and the draft stay in this browser.
      </p>

      <div class="row">
        <label class="row small">
          key
          <input
            type="password"
            style="width:22rem"
            placeholder="TypeSafe API key"
            autocomplete="off"
            bind:value={keyInput}
            onchange={persistKey}
          />
        </label>
        <label class="row small">
          <input
            type="checkbox"
            checked={remember}
            onchange={(event) => toggleRemember(event.currentTarget.checked)}
          />
          remember this key on this device
        </label>
      </div>
    {/if}

    <div class="row">
      <label class="row small">
        endpoint
        <input
          type="text"
          style="width:20rem"
          bind:value={endpoint}
          onchange={() => setJevEndpoint(endpoint)}
        />
      </label>
      <label class="row small">
        model
        <input
          type="text"
          style="width:10rem"
          bind:value={modelValue}
          onchange={() => setJevModel(modelValue)}
        />
      </label>
    </div>

    <div class="row">
      <button class="primary" onclick={() => check()} disabled={!canCheck}>
        {busy ? "checking…" : "check"}
      </button>
      {#if busy}
        <button onclick={() => controller?.abort()}>stop</button>
      {/if}
      {#if !dev && !hasKey && !keyInput.trim() && !busy}
        <span class="small muted">
          no key: the caption is checked in code, and the lyric questions report unverified
        </span>
      {/if}
    </div>

    {#if errorText}
      <p class="finding error" style="margin:0; white-space:pre-wrap">{errorText}</p>
    {/if}
    {#if notice}
      <p class="finding warn" style="margin:0">{notice}</p>
    {/if}
  </section>

  {#if report}
    <section class="card">
      <div class="row">
        <h2>Report</h2>
        <span class="overall {report.overall}">overall: {report.overall}</span>
        <span class="small muted" style="margin-left:auto">
          {#if report.checked}checked {report.checked} · {/if}oracle {report.oracle.kind}{report.oracle.model
            ? `@${report.oracle.model}`
            : ""}
          {report.oracle.reachable ? "" : " · unreachable"}
        </span>
      </div>

      {#if report.oracle.degraded_reason}
        <p class="finding error" style="margin:0">{report.oracle.degraded_reason}</p>
      {/if}

      {#if report.summary}
        <p class="summary">{report.summary}</p>
      {/if}

      {#if counts}
        <div class="counts">
          <span class="count met">{counts.met}/{counts.total} met</span>
          <span class="count measure">{counts.decided_by_measurement} by measurement</span>
          <span class="count describe">{counts.decided_by_description} by description</span>
          <span class="count uncertain">{counts.uncertain} uncertain</span>
          <span class="count unverified">{counts.unverified} unverified</span>
        </div>
      {/if}

      {#if attentionRows.length}
        <div class="loud fix-block">
          <div class="row">
            <h3>TO FIX BEFORE RENDERING</h3>
            {#if onRepair && repairable.length}
              <button class="primary" onclick={autoFix} disabled={repairing || busy}>
                {repairing ? "rewriting the lyrics…" : `fix the lyrics (${repairable.length})`}
              </button>
            {/if}
          </div>
          <ul>
            {#each attentionRows as verdict (verdict.requirement_id)}
              <li>
                <div class="fix-head">
                  <strong>{verdict.text ?? verdict.requirement_id}</strong>
                  <span class="verdict {verdict.verdict}">{verdict.verdict}</span>
                  {#if verdict.severity}<span class="tag">{verdict.severity}</span>{/if}
                </div>
                <p class="fix-body">{verdict.suggestion ?? verdict.note ?? "no reason recorded"}</p>
                {#if verdict.suggestion && verdict.note}
                  <p class="small muted">{verdict.note}</p>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if unverifiedRows.length}
        <div class="loud unverified-block">
          <h3>UNVERIFIED — nothing checked these. Not passed, not failed.</h3>
          <ul>
            {#each unverifiedRows as verdict (verdict.requirement_id)}
              <li>
                <span class="mono">{verdict.requirement_id}</span>
                {#if verdict.severity}<span class="tag">{verdict.severity}</span>{/if}
                — {verdict.suggestion ?? verdict.note ?? "no reason recorded"}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      <table class="grid">
        <thead>
          <tr>
            <th>requirement</th>
            <th>verdict</th>
            <th>severity</th>
            <th>decided by</th>
            <th>what to do</th>
          </tr>
        </thead>
        <tbody>
          {#each report.verdicts as verdict (verdict.requirement_id)}
            <tr>
              <td class="mono">{verdict.requirement_id}</td>
              <td><span class="verdict {verdict.verdict}">{verdict.verdict}</span></td>
              <td>{verdict.severity ?? "—"}</td>
              <td class="mono muted">{verdict.checker}</td>
              <td class="small">
                {verdict.verdict === "met" ? "" : (verdict.suggestion ?? verdict.note ?? "")}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>

      {#if report.cross_check && report.cross_check.agrees_with_individual_verdicts === false}
        <p class="finding warn" style="margin:0">
          cross-check: {report.cross_check.note ??
            "the summary question disagrees with the individual verdicts"}
        </p>
      {/if}
    </section>
  {/if}
</div>

<style>
  .card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 12px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--radius);
  }

  h2 {
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }

  .overall {
    font-weight: 700;
  }

  .overall.compliant {
    color: var(--ok);
  }

  .overall.compliant_with_unmet_soft {
    color: var(--warn);
  }

  .overall.non_compliant {
    color: var(--bad);
  }

  .overall.unverified {
    color: var(--unknown);
  }

  .counts {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .count {
    font-size: 12px;
    padding: 2px 8px;
    border: 1px solid var(--line);
    border-radius: 999px;
  }

  .count.met {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 45%, transparent);
  }

  .count.measure {
    color: var(--ok);
  }

  .count.describe {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 45%, transparent);
  }

  /* The project's claim is that it reports what it could not check, so the two counts that
     represent un-decided work are louder than the met count rather than quieter. */
  .count.uncertain {
    color: var(--warn);
    font-weight: 700;
    border-color: var(--warn);
  }

  .count.unverified {
    color: var(--unknown);
    font-weight: 700;
    border-color: var(--unknown);
    background: color-mix(in srgb, var(--unknown) 14%, transparent);
  }

  .verdict {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .verdict.met {
    color: var(--ok);
  }

  .verdict.unmet {
    color: var(--bad);
  }

  .verdict.uncertain {
    color: var(--warn);
    padding: 0 4px;
    background: color-mix(in srgb, var(--warn) 18%, transparent);
    border-radius: 3px;
  }

  .verdict.unverified {
    color: var(--unknown);
    padding: 0 4px;
    background: color-mix(in srgb, var(--unknown) 18%, transparent);
    border-radius: 3px;
  }

  .loud {
    padding: 8px 10px;
    border: 1px solid;
    border-radius: var(--radius);
  }

  .loud h3 {
    margin: 0 0 4px;
    font-size: 12px;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .loud ul {
    margin: 0;
    padding-left: 18px;
  }

  .loud li {
    padding: 1px 0;
    font-size: 12px;
  }

  .unverified-block {
    background: color-mix(in srgb, var(--unknown) 12%, transparent);
    border-color: color-mix(in srgb, var(--unknown) 60%, var(--line));
  }

  .unverified-block h3 {
    color: var(--unknown);
  }

  .summary {
    margin: 0;
    font-size: 13px;
    line-height: 1.5;
  }

  .fix-block {
    background: color-mix(in srgb, var(--warn) 8%, transparent);
    border-color: color-mix(in srgb, var(--warn) 55%, var(--line));
  }

  .fix-block h3 {
    color: var(--warn);
  }

  .fix-block ul {
    list-style: none;
    padding-left: 0;
  }

  .fix-block li {
    padding: 6px 0;
    border-top: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
  }

  .fix-block li:first-child {
    border-top: 0;
  }

  .fix-head {
    display: flex;
    align-items: baseline;
    gap: 6px;
    flex-wrap: wrap;
  }

  .fix-body {
    margin: 2px 0 0;
    font-size: 12px;
    line-height: 1.45;
  }
</style>
