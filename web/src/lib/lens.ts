/**
 * The grammar lens: what turns a plain textarea into an editor that knows the lyric grammar.
 *
 * The lyric stays a text file — everything here is a view over the same characters, so it still
 * round-trips. The rules it enforces are the ones the checker enforces, read from the same
 * `section-tags.json`, so the lens cannot invent a rule the checker does not have.
 */
import {
  autocompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete";
import { linter, type Diagnostic } from "@codemirror/lint";
import type { Extension } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import type { TagPools, TagTerm } from "./types";

// --- Slot-aware tag completion -------------------------------------------------------------

function completions(terms: TagTerm[], detail: string): Completion[] {
  return terms.map((term) => ({
    label: term.label,
    detail,
    info: term.description,
    type: "keyword",
  }));
}

const CAESURA_BREAK = /\s([/|])\s/g;

/** The label inside a bracket tag, with any ` - modifier` removed. */
function bracketLabel(text: string): string | null {
  const match = /^\s*\[([^\]]+)\]\s*$/.exec(text);
  if (!match) return null;
  return match[1].split(" - ")[0].trim();
}

/**
 * Which pool a tag position draws from.
 *
 * The one hard rule is `modifier`: the grammar allows a modifier only after a section header, so that
 * is the only place one is offered. The rest is ordering rather than a gate, because after a blank
 * line a tag can legitimately be either the transition leaving this section or the header of the
 * next one — refusing half of those would be the lens inventing a rule the checker does not have.
 */
export type Slot = "modifier" | "header" | "within" | "leaving";

export function slotFor(options: {
  /** The whole document, split into lines. */
  lines: string[];
  /** 1-based line the caret is on. */
  line: number;
  /** The tag text after `[`, up to the caret. */
  content: string;
  sectionLabels: Set<string>;
}): Slot {
  if (options.content.includes(" - ")) return "modifier";

  let foundHeader = false;
  let crossedBlank = false;
  let hasWords = false;

  // Walk back to this section's header, noting what sat in between.
  for (let n = options.line - 1; n >= 1; n -= 1) {
    const raw = options.lines[n - 1] ?? "";
    if (raw.trim() === "") {
      crossedBlank = true;
      continue;
    }
    const label = bracketLabel(raw.trim());
    if (label !== null && options.sectionLabels.has(label)) {
      foundHeader = true;
      break;
    }
    if (label === null) hasWords = true;
  }

  if (!foundHeader) return "header";
  return hasWords || crossedBlank ? "leaving" : "within";
}

export function tagCompletion(pools: TagPools) {
  const sectionLabels = new Set(pools.sections.map((section) => section.label));
  const sections = completions(pools.sections, "section");
  const modifiers = completions(pools.modifiers, "modifier");
  const performance = [
    ...completions(pools.vocal_tags, "vocal"),
    ...completions(pools.energy_tags, "energy"),
    ...completions(pools.instrumental_section_tags, "instrumental"),
  ];
  const transitions = completions(pools.transition_tags, "transition");

  const poolsFor: Record<Slot, Completion[]> = {
    modifier: modifiers,
    header: [...sections, ...performance],
    within: [...performance, ...sections],
    leaving: [...transitions, ...sections, ...performance],
  };

  return (context: CompletionContext): CompletionResult | null => {
    // Only inside an open bracket; the format is bracketed, so that is the only place a tag goes.
    const token = context.matchBefore(/\[[^\]\n]*/);
    if (!token) return null;

    const doc = context.state.doc;
    const lines: string[] = [];
    for (let n = 1; n <= doc.lines; n += 1) lines.push(doc.line(n).text);

    const content = token.text.slice(1);
    const slot = slotFor({
      lines,
      line: doc.lineAt(token.from).number,
      content,
      sectionLabels,
    });
    const modifierAt = content.indexOf(" - ");
    const from = slot === "modifier" ? token.from + 1 + modifierAt + 3 : token.from + 1;

    return { from, options: poolsFor[slot], validFor: /^[^\]\n]*$/ };
  };
}

// --- Findings, pointed at the line they are about --------------------------------------------

export interface Finding {
  line: number;
  severity: "error" | "warning";
  message: string;
}

/**
 * The checker reports most findings as `line N: ...` and the rest as prose about the whole song.
 * Only the positional ones can be underlined, and inventing a position for the others would put a
 * squiggle under an innocent line.
 */
export function parseFindings(report: { errors: string[]; warnings: string[] }): Finding[] {
  const out: Finding[] = [];
  const positional = /^line (\d+):\s*(.*)$/s;
  const pairs: [Finding["severity"], string[]][] = [
    ["error", report.errors],
    ["warning", report.warnings],
  ];
  for (const [severity, items] of pairs) {
    for (const item of items) {
      const match = positional.exec(item);
      if (match) out.push({ line: Number(match[1]), severity, message: match[2].trim() });
    }
  }
  return out;
}

export function lyricLinter(check: (text: string) => Finding[]): Extension {
  return linter(
    (view) => {
      const doc = view.state.doc;
      return check(doc.toString())
        .filter((finding) => finding.line >= 1 && finding.line <= doc.lines)
        .map((finding): Diagnostic => {
          const line = doc.line(finding.line);
          return {
            from: line.from,
            to: line.to,
            severity: finding.severity,
            message: finding.message,
          };
        });
    },
    { delay: 250 },
  );
}

// --- Caesurae and section headers, made visible ------------------------------------------------

const caesura = Decoration.mark({ class: "cm-caesura" });
const header = Decoration.mark({ class: "cm-header-tag" });

export function structureMarks(pools: TagPools): Extension {
  const sectionLabels = new Set(pools.sections.map((section) => section.label));

  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;

      constructor(view: EditorView) {
        this.decorations = this.build(view);
      }

      update(update: ViewUpdate) {
        if (update.docChanged || update.viewportChanged) this.decorations = this.build(update.view);
      }

      build(view: EditorView): DecorationSet {
        const marks: { from: number; to: number; deco: Decoration }[] = [];
        const doc = view.state.doc;

        for (let n = 1; n <= doc.lines; n += 1) {
          const line = doc.line(n);
          const label = bracketLabel(line.text);
          if (label !== null && sectionLabels.has(label)) {
            marks.push({ from: line.from, to: line.to, deco: header });
          }
          CAESURA_BREAK.lastIndex = 0;
          let match: RegExpExecArray | null;
          while ((match = CAESURA_BREAK.exec(line.text)) !== null) {
            const at = line.from + match.index + 1;
            marks.push({ from: at, to: at + 1, deco: caesura });
          }
        }

        return Decoration.set(
          marks.map((mark) => mark.deco.range(mark.from, mark.to)),
          true,
        );
      }
    },
    { decorations: (plugin) => plugin.decorations },
  );
}

// --- Assembling the lens ----------------------------------------------------------------------

export function createLens(options: {
  pools: TagPools;
  check: (text: string) => Finding[];
}): Extension[] {
  return [
    autocompletion({ override: [tagCompletion(options.pools)], activateOnTyping: true }),
    lyricLinter(options.check),
    structureMarks(options.pools),
    EditorView.lineWrapping,
  ];
}
