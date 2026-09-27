<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import { fixed, mmss } from "./format";
  import type { LyricReport, TimelinePlan } from "./types";

  let {
    report,
    plan,
    caretLine,
  }: {
    report: LyricReport | null;
    plan: TimelinePlan | null;
    caretLine: number;
  } = $props();

  // The section the caret sits in is the last one that starts at or above it.
  const index = $derived.by(() => {
    if (!report) return -1;
    let found = -1;
    report.outline.forEach((entry, position) => {
      if (entry.line <= caretLine) found = position;
    });
    return found;
  });

  const measured = $derived(index >= 0 && report ? report.sections[index] : null);
  const planned = $derived(index >= 0 && plan ? plan.rows[index] : null);
  const written = $derived(
    measured ? measured.counts.reduce((total, count) => total + count, 0) : 0,
  );
  const summary = $derived(
    measured
      ? `${measured.tag} · ${written} syllables` +
        (planned && !planned.instrumental ? ` of ${planned.budget_min}–${planned.budget_max}` : "")
      : "put the caret in a section",
  );
</script>

<Collapsible title="Section" {summary} storageKey="mm.panel.inspector" defaultOpen>
  {#snippet badges()}
    {#if measured && planned && !planned.instrumental && written > planned.ceiling}
      <span class="chip warn">over the ceiling</span>
    {/if}
  {/snippet}

  {#if measured}
    <div class="small">
      <div class="row">
        <strong>{measured.tag}</strong>
        {#if planned}
          <span class="muted">
            {planned.bars} bars · {fixed(planned.dur_s)}s · {planned.lines} lines
            {#if planned.instrumental}· instrumental{/if}
          </span>
        {/if}
      </div>
      <div class="row" style="margin-top:6px">
        <span class="muted">syllables</span>
        <span class="mono">{written}</span>
        {#if planned && !planned.instrumental}
          <span class="muted">budget {planned.budget_min}–{planned.budget_max}</span>
          <span class="muted">ceiling {planned.ceiling}</span>
          <span class="muted">
            {measured.syl_per_bar === null || measured.syl_per_bar === undefined
              ? ""
              : `${fixed(measured.syl_per_bar, 2)}/s`}
          </span>
        {/if}
      </div>
      <div class="row" style="margin-top:6px">
        <span class="muted">per line</span>
        <span class="mono">{measured.counts.join(", ") || "—"}</span>
      </div>
      <div class="row" style="margin-top:6px">
        <span class="muted">phrases</span>
        <span class="mono">{measured.phrases.map((line) => line.join("/")).join("  ") || "—"}</span>
      </div>
      <div class="row" style="margin-top:6px">
        <span class="muted">rhyme</span>
        <span>{measured.scheme}</span>
        {#if measured.scheme_expected}
          <span class="muted">template asks {measured.scheme_expected}</span>
        {/if}
      </div>
      {#if planned && planned.vocals.length}
        <div class="row" style="margin-top:6px">
          <span class="muted">template asks for</span>
          <span class="mono">{planned.vocals.join(", ")}</span>
        </div>
      {/if}
      <div class="row muted" style="margin-top:6px">
        <span>{mmss(planned?.start_s ?? 0)} into the song</span>
      </div>
    </div>
  {:else}
    <p class="small muted" style="margin:0">put the caret in a section to see its numbers</p>
  {/if}
</Collapsible>
