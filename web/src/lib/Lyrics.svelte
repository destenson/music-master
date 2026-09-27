<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import { fixed } from "./format";
  import type { LyricReport } from "./types";

  let { text = $bindable(), report }: { text: string; report: LyricReport | null } = $props();

  const findings = $derived(
    report
      ? report.errors.length + report.warnings.length + report.oracle_tasks.length
      : 0,
  );
  const summary = $derived(
    report
      ? `${report.lines} lines · ${report.sections.length} sections` +
          (report.conformance ? ` · ${report.conformance.matched.length} matched the template` : "")
      : "waiting for the text tier",
  );
</script>

<div class="stack">
  <Collapsible title="Lyric" {summary} storageKey="mm.panel.lyric" defaultOpen>
    {#snippet badges()}
      {#if report?.conformance?.missing?.length}
        <span class="chip warn">{report.conformance.missing.length} missing</span>
      {/if}
    {/snippet}
    <textarea class="lyrics" bind:value={text} spellcheck="false"></textarea>
  </Collapsible>

  {#if report}
    <Collapsible
      title="Findings"
      summary={findings === 0
        ? "nothing to report"
        : `${report.errors.length} error(s) · ${report.warnings.length} warning(s) · ${report.oracle_tasks.length} deferred`}
      storageKey="mm.panel.findings"
      defaultOpen
    >
      {#snippet badges()}
        {#if report.errors.length}<span class="chip warn">{report.errors.length} error(s)</span>{/if}
      {/snippet}

      {#if findings === 0}
        <p class="small muted" style="margin:0">nothing to report</p>
      {/if}
      {#each report.errors as error, i (i)}
        <div class="finding error">ERROR — {error}</div>
      {/each}
      {#each report.warnings as warning, i (i)}
        <div class="finding warn">warn — {warning}</div>
      {/each}
      {#each report.oracle_tasks as task, i (i)}
        <div class="finding oracle">deferred — {task}</div>
      {/each}
    </Collapsible>

    {#if report.sections.length}
      <Collapsible
        title="Per section"
        summary={`${report.sections.length} sections · syllables counted per phrase`}
        storageKey="mm.panel.sections"
      >
        <table class="grid">
          <thead>
            <tr>
              <th>section</th>
              <th>syllables / line</th>
              <th>phrases</th>
              <th>end rhyme</th>
              <th>2/s</th>
            </tr>
          </thead>
          <tbody>
            {#each report.sections as section (section.tag)}
              <tr>
                <td>{section.tag}</td>
                <td class="mono">{section.counts.join(",")}</td>
                <td class="mono">{section.phrases.map((line) => line.join("/")).join("  ")}</td>
                <td>
                  {section.scheme}
                  {#if section.scheme_expected}
                    <span class="muted small">vs {section.scheme_expected}</span>
                  {/if}
                </td>
                <td class="mono muted">
                  {section.syl_per_bar === null || section.syl_per_bar === undefined
                    ? "—"
                    : fixed(section.syl_per_bar, 2)}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </Collapsible>
    {/if}
  {/if}
</div>
