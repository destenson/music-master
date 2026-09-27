<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    summary = "",
    storageKey,
    defaultOpen = false,
    avoid = false,
    badges,
    children,
  }: {
    title: string;
    summary?: string;
    storageKey: string;
    defaultOpen?: boolean;
    avoid?: boolean;
    badges?: Snippet;
    children: Snippet;
  } = $props();

  /**
   * Deliberately uncontrolled: Svelte never writes `open`, so the browser owns the state and a
   * reactive update cannot fight the user's click. The action only seeds the state from storage and
   * records the choice, which is what makes the layout remember what you had open between visits.
   */
  function remember(node: HTMLDetailsElement, params: { key: string; open: boolean }) {
    const stored = (() => {
      try {
        return localStorage.getItem(params.key);
      } catch {
        return null; // storage can be unavailable, and that is not worth failing a render over
      }
    })();

    node.open = stored === null ? params.open : stored === "true";

    const onToggle = () => {
      try {
        localStorage.setItem(params.key, String(node.open));
      } catch {
        /* not remembering is an acceptable outcome */
      }
    };
    node.addEventListener("toggle", onToggle);
    return { destroy: () => node.removeEventListener("toggle", onToggle) };
  }
</script>

<details
  class="section"
  class:avoid
  use:remember={{ key: storageKey, open: defaultOpen }}
>
  <!-- The summary is the one line that stands in for the contents, so it ellipsises rather than
       wrapping; the title carries the whole of it for the long groups. -->
  <summary title={summary || undefined}>
    <span class="section-title">{title}</span>
    {#if badges}{@render badges()}{/if}
    <span class="section-summary" class:empty={!summary}>{summary || "nothing selected"}</span>
  </summary>
  <div class="section-body">
    {@render children()}
  </div>
</details>
