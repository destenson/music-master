<script lang="ts">
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

  const canCheck = $derived(!!core && !busy && (dev || hasKey || keyInput.trim() !== ""));

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
  const uncertainRows = $derived(
    (report?.verdicts ?? []).filter((verdict) => verdict.verdict === "uncertain"),
  );

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
  async function check(): Promise<void> {
    if (!core || busy) return;
    const typed = keyInput.trim();
    if (!dev) persistKey();
    // Persist an edited endpoint or model, but only when it differs from what is stored: writing
    // the development default to storage would follow the browser into a static build.
    if (endpoint !== jevEndpoint()) setJevEndpoint(endpoint);
    if (modelValue !== jevModel()) setJevModel(modelValue);
    const key = typed || jevKey();
    if (!dev && !key) return;

    busy = true;
    errorText = null;
    report = null;
    controller = new AbortController();

    let spec: unknown = null;
    let state: unknown = null;
    let answerModel = modelValue;
    let response: unknown = null;
    let failure: string | null = null;

    try {
      const prepared = core.jevRequest({
        selections,
        bpm,
        duration_s: duration,
        template_id: templateId || null,
        lyrics,
        caption,
        theme,
        artist_references: artistReferences,
        model: modelValue,
      });
      spec = prepared.spec;
      state = prepared.request.state;
      answerModel = prepared.request.model || modelValue;

      try {
        response = await callJev(prepared.request, { key, endpoint, signal: controller.signal });
      } catch (cause) {
        if (isAbort(cause)) return;
        failure = cause instanceof Error ? cause.message : String(cause);
        errorText = failure;
      }

      try {
        report = core.complianceReport({
          spec,
          state,
          model: answerModel,
          response,
          error: failure,
          song_id: songId,
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
      <h2>Jev compliance</h2>
      <span class="chip" class:meta={!hasKey}>{keyState}</span>
    </div>

    {#if dev}
      <p class="small" style="margin:0">
        In development the request goes through this page's own dev server at <code>/jev</code>,
        which adds <code>TYPESAFE_API_KEY</code> from its environment — the key never enters this
        browser, and the call is same-origin so CORS does not apply. The song's caption, chords and
        lyrics still leave this machine for <code>api.typesafe.ai</code>.
      </p>
    {:else}
      <p class="small" style="margin:0">
        Pressing <strong>check compliance</strong> sends this song's caption, chords and lyrics to
        <code>{endpoint}</code> for a Jev judgement. Nothing else leaves this machine: the key, the
        selections and the draft stay in this browser.
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
      <button class="primary" onclick={check} disabled={!canCheck}>
        {busy ? "checking…" : "check compliance"}
      </button>
      {#if busy}
        <button onclick={() => controller?.abort()}>stop</button>
      {/if}
      {#if !dev && !canCheck && !busy}
        <span class="small muted">
          {hasKey || keyInput.trim()
            ? ""
            : "enter a key above to run the check — it is sent only to the endpoint and stays here"}
        </span>
      {/if}
    </div>

    {#if errorText}
      <p class="finding error" style="margin:0; white-space:pre-wrap">{errorText}</p>
    {/if}
  </section>

  {#if report}
    <section class="card">
      <div class="row">
        <h2>Report</h2>
        <span class="overall {report.overall}">overall: {report.overall}</span>
        <span class="small muted" style="margin-left:auto">
          oracle {report.oracle.kind}{report.oracle.model ? `@${report.oracle.model}` : ""}
          {report.oracle.reachable ? "" : " · unreachable"}
        </span>
      </div>

      {#if report.oracle.degraded_reason}
        <p class="finding error" style="margin:0">{report.oracle.degraded_reason}</p>
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

      {#if unverifiedRows.length}
        <div class="loud unverified-block">
          <h3>UNVERIFIED — nothing checked these. Not passed, not failed.</h3>
          <ul>
            {#each unverifiedRows as verdict (verdict.requirement_id)}
              <li>
                <span class="mono">{verdict.requirement_id}</span>
                {#if verdict.severity}<span class="tag">{verdict.severity}</span>{/if}
                — {verdict.note ?? "no reason recorded"}
              </li>
            {/each}
          </ul>
        </div>
      {/if}

      {#if uncertainRows.length}
        <div class="loud uncertain-block">
          <h3>UNCERTAIN — checked, but inside the uncertainty band. Neither a pass nor a fail.</h3>
          <ul>
            {#each uncertainRows as verdict (verdict.requirement_id)}
              <li>
                <span class="mono">{verdict.requirement_id}</span>
                {#if verdict.severity}<span class="tag">{verdict.severity}</span>{/if}
                — {verdict.note ?? "no reason recorded"}
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
            <th>checker</th>
            <th>note</th>
          </tr>
        </thead>
        <tbody>
          {#each report.verdicts as verdict (verdict.requirement_id)}
            <tr>
              <td class="mono">{verdict.requirement_id}</td>
              <td><span class="verdict {verdict.verdict}">{verdict.verdict}</span></td>
              <td>{verdict.severity ?? "—"}</td>
              <td class="mono muted">{verdict.checker}</td>
              <td>{verdict.note ?? ""}</td>
            </tr>
          {/each}
        </tbody>
      </table>

      {#if report.unmet?.length}
        <div class="loud unmet-block">
          <h3>UNMET — what this song does not satisfy</h3>
          <ul>
            {#each report.unmet as item, index (index)}
              <li>{item}</li>
            {/each}
          </ul>
        </div>
      {/if}

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

  .uncertain-block {
    background: color-mix(in srgb, var(--warn) 10%, transparent);
    border-color: color-mix(in srgb, var(--warn) 60%, var(--line));
  }

  .uncertain-block h3 {
    color: var(--warn);
  }

  .unmet-block {
    border-color: color-mix(in srgb, var(--bad) 45%, var(--line));
  }

  .unmet-block h3 {
    color: var(--bad);
  }
</style>
