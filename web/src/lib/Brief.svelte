<script lang="ts">
  import Collapsible from "./Collapsible.svelte";

  let { text }: { text: string } = $props();

  let copied = $state(false);

  async function copy(event: MouseEvent) {
    // The button sits in the summary, so the click must not also fold the section closed.
    event.preventDefault();
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      /* clipboard access can be refused; the text is on screen and selectable */
    }
  }
</script>

<Collapsible
  title="Writing brief"
  summary="the contract this song is written to — paste it into any model"
  storageKey="mm.panel.brief"
>
  {#snippet badges()}
    <button onclick={copy}>{copied ? "copied" : "copy"}</button>
  {/snippet}
  <pre class="brief">{text}</pre>
</Collapsible>
