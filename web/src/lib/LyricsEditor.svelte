<script lang="ts">
  import { onMount } from "svelte";
  import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
  import { bracketMatching, indentOnInput } from "@codemirror/language";
  import { EditorState } from "@codemirror/state";
  import { EditorView, drawSelection, keymap } from "@codemirror/view";
  import { forceLinting } from "@codemirror/lint";
  import { createLens, editorTheme, type Finding } from "./lens";
  import type { TagPools } from "./types";

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

  /** Put the caret on a line and scroll to it, for a finding that names one. */
  export function revealLine(line: number): void {
    if (!view) return;
    const target = Math.min(Math.max(1, line), view.state.doc.lines);
    view.dispatch({
      selection: { anchor: view.state.doc.line(target).from },
      scrollIntoView: true,
    });
    view.focus();
  }

  /** Re-run the findings when something other than the text changed, such as the caption. */
  export function recheck(): void {
    if (view) forceLinting(view);
  }
</script>

<div class="editor" bind:this={host}></div>
