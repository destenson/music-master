/**
 * Handing an artifact to the user.
 *
 * A static page cannot write to the song directory, so the loop out is a download and a commit —
 * which is also why everything the page produces is serialised by the same function the hashes go
 * through: what you download is exactly what was hashed.
 */
export function downloadText(filename: string, text: string, type = "application/json"): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
