<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import { fixed, mmss } from "./format";
  import type { StructureTemplate, TimelinePlan } from "./types";

  let {
    plan,
    templates,
    templateId = $bindable(),
    bpm = $bindable(),
    duration = $bindable(),
  }: {
    plan: TimelinePlan | null;
    templates: StructureTemplate[];
    templateId: string;
    bpm: number;
    duration: number | null;
  } = $props();

  const totals = $derived(plan?.totals ?? null);
  const summary = $derived(
    plan && totals
      ? `${plan.template_name} · ${bpm} BPM · ${mmss(totals.total_s)}` +
          (plan.achieved_s ? ` (scaled to ${mmss(plan.achieved_s)})` : "") +
          ` · ${plan.profile_label}`
      : "…",
  );
</script>

<Collapsible title="Structure & time" {summary} storageKey="mm.panel.timeline" defaultOpen>
  {#snippet badges()}
    {#if totals}
      <span class="chip">{totals.sections} sections</span>
      <span class="chip">{totals.budget_min}–{totals.budget_max} syll</span>
    {/if}
  {/snippet}

  <div class="row">
    <label class="row small">
      template
      <select bind:value={templateId}>
        {#each templates as template (template.id)}
          <option value={template.id}>{template.name}</option>
        {/each}
      </select>
    </label>
    <label class="row small">
      tempo
      <input type="number" style="width:4.5rem" min="40" max="220" bind:value={bpm} />
      BPM
    </label>
    <label class="row small">
      target
      <input
        type="number"
        style="width:5rem"
        placeholder="natural"
        min="30"
        max="600"
        value={duration ?? ""}
        oninput={(event) => {
          const raw = event.currentTarget.value;
          duration = raw === "" ? null : Number(raw);
        }}
      />
      seconds
    </label>
  </div>

  {#if plan && totals}
    <div class="row small muted">
      <span>{totals.bars} bars</span>
      <span>· {mmss(totals.vocal_s)} sung, {mmss(totals.instrumental_s)} instrumental
        ({totals.instrumental_sections} sections)</span>
      <span>· {totals.vocal_lines} vocal lines</span>
      <span>· ceiling {totals.ceiling}</span>
    </div>

    <div class="timeline">
      {#each plan.rows as row (row.index)}
        {@const width = totals.total_s ? (row.dur_s / totals.total_s) * 100 : 0}
        <div class="tl-row">
          <span>
            {row.label}
            {#if row.instrumental}<span class="muted small">instrumental</span>{/if}
            {#if row.hook}<span class="chip">hook</span>{/if}
          </span>
          <span class="muted">{row.bars}b</span>
          <span class="muted">
            {row.instrumental ? "—" : `${row.budget_min}–${row.budget_max}`}
          </span>
          <span
            class="tl-bar"
            class:instrumental={row.instrumental}
            class:sparse={row.sparse}
            style={`width:${width}%`}
            title={`${mmss(row.start_s)} · ${fixed(row.dur_s)}s · ceiling ${row.ceiling} syllables`}
          ></span>
        </div>
      {/each}
    </div>
  {/if}
</Collapsible>
