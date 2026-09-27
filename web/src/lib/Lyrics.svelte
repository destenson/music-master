<script lang="ts">
  import Collapsible from "./Collapsible.svelte";
  import Generate from "./Generate.svelte";
  import LyricsEditor from "./LyricsEditor.svelte";
  import { fixed } from "./format";
  import { parseFindings, type Finding } from "./lens";
  import type { LyricReport, TagPools } from "./types";

  let {
    text = $bindable(),
    report,
    pools,
    check,
    buildPrompt,
    onDraft,
    onScaffold,
    onCaret,
  }: {
    text: string;
    report: LyricReport | null;
    pools: TagPools;
    check: (text: string) => Finding[];
    buildPrompt: (theme: string) => string;
    onDraft: (text: string) => void;
    onScaffold: () => void;
    onCaret: (line: number) => void;
  } = $props();

  let editor = $state<LyricsEditor | null>(null);

  // The checker states most findings as `line N: …` and the rest as prose about the whole song.
  // Only the positional ones get a jump, because a squiggle under an innocent line is worse than
  // no squiggle.
  const positional = $derived(report ? parseFindings(report) : []);
  const elsewhere = $derived(
    report
      ? [...report.errors, ...report.warnings].filter((message) => !/^line \d+:/.test(message))
      : [],
  );
  const deferred = $derived(report?.oracle_tasks ?? []);
  const total = $derived(positional.length + elsewhere.length + deferred.length);

  const summary = $derived(
    report
      ? total === 0
        ? `${report.lines} lines · nothing to report`
        : `${report.lines} lines · ${total} finding(s)`
      : "waiting for the text tier",
  );

  // The caption can change while the text does not, and the consistency findings depend on it.
  $effect(() => {
    void report;
    editor?.recheck();
  });
</script>

<div class="stack">
  <Collapsible title="Lyric" {summary} storageKey="mm.panel.lyric" defaultOpen>
    {#snippet badges()}
      {#if report?.conformance?.missing?.length}
        <span class="chip warn">{report.conformance.missing.length} missing</span>
      {/if}
      {#if report && report.errors.length}
        <span class="chip warn">{report.errors.length} error(s)</span>
      {/if}
    {/snippet}

    <div class="row">
      <button onclick={onScaffold}>Scaffold from template</button>
      <span class="muted small">
        builds the sections, the performance tags and the transitions; no words
      </span>
    </div>

    <Generate {buildPrompt} {onDraft} />

    <LyricsEditor
      bind:this={editor}
      bind:text
      {pools}
      {check}
      oncaret={(line) => onCaret(line)}
    />
  </Collapsible>

  <Collapsible title="Findings" {summary} storageKey="mm.panel.findings" defaultOpen>
    {#if total === 0}
      <p class="small muted" style="margin:0">nothing to report</p>
    {/if}

    {#each positional as finding, i (i)}
      <div class="finding {finding.severity === 'error' ? 'error' : 'warn'}">
        <button class="jump" onclick={() => editor?.revealLine(finding.line)}>
          line {finding.line}
        </button>
        {finding.message}
      </div>
    {/each}

    {#each elsewhere as message, i (i)}
      <div class="finding {message.startsWith('ERROR') ? 'error' : 'warn'}">{message}</div>
    {/each}

    {#each deferred as task, i (i)}
      <div class="finding oracle">deferred — {task}</div>
    {/each}
  </Collapsible>

  {#if report?.sections?.length}
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
          {#each report.sections as section, i (i)}
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
</div>
