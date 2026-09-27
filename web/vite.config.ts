import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig, type Plugin } from "vite";

const WEB = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(WEB, "..");

/**
 * What the page may read straight out of the repository.
 *
 * The point is that the UI and the CLI cannot disagree about what the vocabulary is: the form is
 * generated from the same `tag-bins.json` the renderer reads, and the checks run the same Python.
 * Listing the trees rather than the files means adding a vocabulary file needs no change here.
 */
const REPO_SOURCES = [
  { dir: "musicmaster", exts: [".py"] },
  { dir: "vocabulary", exts: [".json", ".py", ".md"] },
  { dir: "schemas", exts: [".json"] },
  ...fs
    .readdirSync(path.join(REPO, "songs"), { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => ({ dir: `songs/${entry.name}`, exts: [".json", ".md"] })),
];

/**
 * The Pyodide runtime is self-hosted rather than pulled from a CDN, so the page works offline and
 * cannot drift from the version in package.json.
 */
const PYODIDE_FILES = [
  "pyodide.mjs",
  "pyodide.asm.mjs",
  "pyodide.asm.wasm",
  "python_stdlib.zip",
  "pyodide-lock.json",
];

const MIME: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".py": "text/x-python; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".wasm": "application/wasm",
  ".zip": "application/zip",
};

function collectRepoFiles(): string[] {
  const out: string[] = [];
  for (const { dir, exts } of REPO_SOURCES) {
    const abs = path.join(REPO, dir);
    if (!fs.existsSync(abs)) continue;
    for (const rel of fs.readdirSync(abs, { recursive: true })) {
      const name = String(rel);
      if (name.split(path.sep).includes("__pycache__")) continue;
      if (!exts.includes(path.extname(name))) continue;
      if (!fs.statSync(path.join(abs, name)).isFile()) continue;
      out.push(path.posix.join(dir, name.split(path.sep).join("/")));
    }
  }
  return out.sort();
}

function sendFile(res: import("node:http").ServerResponse, abs: string, rel: string): void {
  res.setHeader("Content-Type", MIME[path.extname(rel)] ?? "application/octet-stream");
  fs.createReadStream(abs).pipe(res);
}

/**
 * Serves the repository and the Pyodide runtime in dev, and copies both into the bundle for a
 * static build. The same list drives both, so what you develop against is what gets deployed.
 */
function sharedAssets(): Plugin {
  const repoFiles = collectRepoFiles();
  let outDir = path.join(WEB, "dist");

  return {
    name: "music-master:shared-assets",

    configResolved(config) {
      outDir = path.resolve(config.root, config.build.outDir);
    },

    configureServer(server) {
      // Installed before Vite's own middlewares, so the SPA fallback never swallows these.
      server.middlewares.use((req, res, next) => {
        const url = (req.url ?? "").split("?")[0];

        if (url === "/repo/manifest.json") {
          res.setHeader("Content-Type", MIME[".json"]);
          res.end(JSON.stringify(repoFiles));
          return;
        }
        if (url.startsWith("/repo/")) {
          const rel = decodeURIComponent(url.slice("/repo/".length));
          if (!repoFiles.includes(rel)) return next();
          sendFile(res, path.join(REPO, rel), rel);
          return;
        }
        if (url.startsWith("/pyodide/")) {
          const rel = decodeURIComponent(url.slice("/pyodide/".length));
          if (!PYODIDE_FILES.includes(rel)) return next();
          sendFile(res, path.join(WEB, "node_modules/pyodide", rel), rel);
          return;
        }
        next();
      });
    },

    closeBundle() {
      for (const rel of repoFiles) {
        const dest = path.join(outDir, "repo", rel);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(path.join(REPO, rel), dest);
      }
      const manifest = path.join(outDir, "repo", "manifest.json");
      fs.mkdirSync(path.dirname(manifest), { recursive: true });
      fs.writeFileSync(manifest, JSON.stringify(repoFiles));

      for (const rel of PYODIDE_FILES) {
        const dest = path.join(outDir, "pyodide", rel);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.copyFileSync(path.join(WEB, "node_modules/pyodide", rel), dest);
      }

      this.info(
        `copied ${repoFiles.length} repository file(s) and ${PYODIDE_FILES.length} runtime file(s)`,
      );
    },
  };
}

export default defineConfig({
  plugins: [svelte(), sharedAssets()],
  // Relative base so the build works from a subpath as well as a domain root.
  base: "./",
  build: {
    target: "es2022",
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});
