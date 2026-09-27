<script lang="ts">
  import { onMount } from "svelte";
  import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
  import { bracketMatching, indentOnInput } from "@codemirror/language";
  import { EditorState, StateEffect, StateField } from "@codemirror/state";
  import {
    Decoration,
    EditorView,
    drawSelection,
    keymap,
    type DecorationSet,
  } from "@codemirror/view";
  import { forceLinting } from "@codemirror/lint";
  import { createLens, editorTheme, type Finding } from "./lens";
  import type { TagPools } from "./types";

  // A one-line highlight, raised by a finding's jump and lowered again once the eye has landed.
  // A decoration rather than a selection: selecting the line would fight the caret the jump sets,
  // and would leave the lyric looking edited when nothing changed.
  const flashLine = StateEffect.define<number | null>();
  const flashMark = Decoration.line({ class: "cm-flash" });
  const flashField = StateField.define<DecorationSet>({
    create: () => Decoration.none,
    update(decorations, transaction) {
      decorations = decorations.map(transaction.changes);
      for (const effect of transaction.effects) {
        if (!effect.is(flashLine)) continue;
        if (effect.value === null) return Decoration.none;
        const line = transaction.state.doc.line(
          Math.min(Math.max(1, effect.value), transaction.state.doc.lines),
        );
        return Decoration.set([flashMark.range(line.from)]);
      }
      return decorations;
    },
    provide: (field) => EditorView.decorations.from(field),
  });

  let {
    text = $bindable(),
    pools,
    check,
    oncaret,
  }: {
    text: string;
    pools: TagPools;
    check: (text: string) => Finding[];
    oncaret?: (line: number) => void;
  } = $props();

  let host: HTMLDivElement;
  let view: EditorView | null = null;
  let flashTimer: ReturnType<typeof setTimeout> | undefined;

  onMount(() => {
    view = new EditorView({
      parent: host,
      state: EditorState.create({
        doc: text,
        extensions: [
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          // Draws the cursor and selection rather than leaving them to the browser, so both follow
          // the theme below instead of the platform's own colours.
          drawSelection(),
          editorTheme(),
          flashField,
          bracketMatching(),
          indentOnInput(),
          // Reads the prop at call time rather than capturing it: the parent's caption and template
          // change underneath a view that was built once.
          ...createLens({ pools, check: (current) => check(current) }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) text = update.state.doc.toString();
            if (update.selectionSet || update.docChanged) {
              oncaret?.(update.state.doc.lineAt(update.state.selection.main.head).number);
            }
          }),
        ],
      }),
    });
    return () => {
      clearTimeout(flashTimer);
      view?.destroy();
      view = null;
    };
  });

  // Writes in changes that came from outside — a scaffold, or a generated draft — without echoing
  // the editor's own edits back into it. Comparing the documents is the whole guard.
  $effect(() => {
    const next = text;
    if (!view) return;
    if (view.state.doc.toString() === next) return;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: next } });
  });

  /** Put the caret on a line, scroll to it, and flash it, for a finding that points at one. */
  export function revealLine(line: number): void {
    if (!view) return;
    const target = Math.min(Math.max(1, line), view.state.doc.lines);
    view.dispatch({
      selection: { anchor: view.state.doc.line(target).from },
      effects: flashLine.of(target),
      scrollIntoView: true,
    });
    view.focus();
    // The highlight is a pointer, not a state: clear it once it has been read.
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      view?.dispatch({ effects: flashLine.of(null) });
    }, 1600);
  }

  /** Re-run the findings when something other than the text changed, such as the caption. */
  export function recheck(): void {
    if (view) forceLinting(view);
  }
</script>

<div class="editor" bind:this={host}></div>
