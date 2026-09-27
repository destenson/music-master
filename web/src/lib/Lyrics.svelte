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
  // Only the positional ones get a squiggle, because underlining an innocent line is worse than
  // no underline — but a finding that names a section can still jump to that section's header.
  const positional = $derived(report ? parseFindings(report) : []);
  const elsewhere = $derived(
    report
      ? [...report.errors, ...report.warnings].filter((message) => !/^line \d+:/.test(message))
      : [],
  );
  const deferred = $derived(report?.oracle_tasks ?? []);
  const notes = $derived(report?.notes ?? []);
  const total = $derived(positional.length + elsewhere.length + notes.length + deferred.length);

  // A finding without a line number often still names a section — "[Chorus]: 4 lines" or
  // "position 3 of [Verse]". Resolving that to the first header of that section is what lets the
  // row jump; a lyric can repeat a section, and the first is the honest answer to an ambiguous tag.
  const sectionLines = $derived.by(() => {
    const map = new Map<string, number>();
    (report?.sections ?? []).forEach((section, index) => {
      const line = report?.outline?.[index]?.line;
      if (line) map.set(labelKey(section.tag), line);
    });
    return map;
  });

  /** Where a finding's own text points, when it points anywhere. */
  function anchorFor(message: string): number | null {
    const numbered = /\bline (\d+)\b/.exec(message);
    if (numbered) return Number(numbered[1]);
    for (const match of message.matchAll(/\[([^\]]+)\]/g)) {
      const line = sectionLines.get(labelKey(match[1]));
      if (line) return line;
    }
    return null;
  }

  /** "[Verse 2]" and "[Verse]" are the same section; a jump wants the header either names. */
  function labelKey(tag: string): string {
    return tag.split(" - ")[0].replace(/\s+\d+$/, "").trim().toLowerCase();
  }

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
  <!-- One row per finding. When the finding points at a line, the whole row is the jump target:
       the line number is the label, not a separate button, so the click area matches what reads
       as clickable. -->
  {#snippet findingRow(message: string, cls: string, line: number | null, showLine = false)}
    {#if line}
      <button
        class="finding jumpable {cls}"
        title="show line {line}"
        onclick={() => editor?.revealLine(line)}
      >
        {#if showLine}<span class="jump">line {line}</span>{/if}
        {message}
      </button>
    {:else}
      <div class="finding {cls}">{message}</div>
    {/if}
  {/snippet}

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
      {@render findingRow(
        finding.message,
        finding.severity === "error" ? "error" : "warn",
        finding.line,
        true,
      )}
    {/each}

    {#each elsewhere as message, i (i)}
      {@render findingRow(
        message,
        message.startsWith("ERROR") ? "error" : "warn",
        anchorFor(message),
      )}
    {/each}

    {#each notes as message, i (i)}
      {@render findingRow(message, "note", anchorFor(message))}
    {/each}

    {#each deferred as task, i (i)}
      {@render findingRow(`deferred — ${task}`, "oracle", anchorFor(task))}
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
