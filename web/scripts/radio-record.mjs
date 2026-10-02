// Regression check: a station's catalogue comes from what is on disk.
//
// The engine is driven through Vite's SSR loader in Node — no browser — so the module's own
// discovery, startup and switching are what is under test. The renderer is stubbed so each source is
// exercised on its own: the listing route, the page's saved record, the remembered addresses, and the
// renderer's history. `--live` points the engine at the running renderer instead and asserts against
// the files that are really there.
import path from "node:path";
import { createServer } from "vite";

const WEB = path.resolve(import.meta.dirname, "..");
// With --live the engine is pointed at the running renderer instead of a stub, so the route the
// toolbox serves is what is exercised.
const LIVE = process.argv.includes("--live");
const failures = [];
function check(label, actual, expected) {
  const same = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`  ${same ? "ok  " : "FAIL"}  ${label}`);
  if (!same) {
    failures.push(label);
    console.log(`        want: ${JSON.stringify(expected)}`);
    console.log(`        got:  ${JSON.stringify(actual)}`);
  }
}

const take = (filename, subfolder) => ({ filename, subfolder, type: "output" });
// A played take whose file is still on disk, and one whose file has been deleted.
const playedBoomBap = {
  id: "saved:1",
  index: 0,
  stationId: "boom-bap-basement",
  title: "Boom Bap Basement #1",
  seed: 1,
  caption: "Boom Bap, Dusty Drums",
  theme: "a block that raised you",
  angle: "told to the person who left",
  instrumental: false,
  file: take("boom-bap-basement_00001.mp3", "radio/boom-bap-basement"),
  at: 1,
};
const deletedBoomBap = {
  ...playedBoomBap,
  id: "saved:2",
  title: "Boom Bap Basement #9",
  theme: "the winter the heat got cut off",
  file: take("boom-bap-basement_00099.mp3", "radio/boom-bap-basement"),
};

const store = new Map([
  ["mm.radio.settings", JSON.stringify({ stationId: LIVE ? "" : "boom-bap-basement" })],
  // Live starts with nothing recorded, so what it finds can only have come from the renderer.
  ["mm.radio.history", JSON.stringify(LIVE ? {} : { "boom-bap-basement": [playedBoomBap, deletedBoomBap] })],
]);
globalThis.localStorage = {
  getItem: (key) => store.get(key) ?? null,
  setItem: (key, value) => store.set(key, String(value)),
  removeItem: (key) => store.delete(key),
};
globalThis.sessionStorage = { getItem: () => null, setItem() {}, removeItem() {} };

// What is actually on disk, which only the listing route can tell the page.
const onDisk = {
  "boom-bap-basement": ["boom-bap-basement_00001.mp3", "boom-bap-basement_00002.mp3"],
  "trap-after-dark": ["trap-after-dark_00001.mp3"],
};
let listingAvailable = true;
let rendererHistory = {};
if (LIVE) {
  // The engine's dev proxy path (`/comfy-8288`) needs a server in front of it and there is none here,
  // so it is rewritten to the real address. Everything else is the live renderer.
  const real = globalThis.fetch;
  globalThis.fetch = (url, init) =>
    real(String(url).replace(/^\/comfy-8288/, "http://127.0.0.1:8288"), init);
} else {
  globalThis.fetch = async (url) => {
    const target = String(url);
    if (target.includes("mytoolbox/output_files")) {
      if (!listingAvailable) return new Response("", { status: 404 }); // no such route to ask
      const subfolder = new URL(target, "http://local").searchParams.get("subfolder") ?? "";
      const stationId = subfolder.replace(/^radio\//, "");
      const files = onDisk[stationId];
      if (!files) {
        return new Response(JSON.stringify({ error: `no such subfolder: ${subfolder}` }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({
          files: files.map((name) => ({
            name,
            subfolder,
            path: `${subfolder}/${name}`,
            type: "output",
            content_type: "audio",
            size: 1,
            mtime: 1,
          })),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    if (target.includes("history")) {
      return new Response(JSON.stringify(rendererHistory), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    // A response with no take in it: enrichment is best-effort, so discovery carries on.
    return new Response("not an mp3", { status: 200 });
  };
}

const server = await createServer({
  root: WEB,
  configFile: path.join(WEB, "vite.config.ts"),
  server: { middlewareMode: true },
  appType: "custom",
  logLevel: "silent",
});

try {
  const radio = await server.ssrLoadModule("/src/lib/radio.svelte.ts");

  if (LIVE) {
    const station =
      process.argv.find((argument) => argument.startsWith("--station="))?.split("=")[1] ??
      "boom-bap-basement";
    radio.radioState.stationId = station;
    await radio.refreshAvailable();
    const takes = radio.radioState.available;
    console.log(`\n${station}: ${takes.length} take(s), newest ${takes[takes.length - 1]?.file?.filename ?? "none"}\n`);
    check("the renderer's own listing finds the station's takes", takes.length > 0, true);
    check(
      "every take is named for the station",
      takes.every((song) => song.file?.filename.startsWith(station)),
      true,
    );
    // The listing gives addresses; the take's own graph has to be read for the caption and the words.
    // Both together are what makes a recovered song show what it actually is.
    check(
      "and every file was read for its caption",
      takes.every((song) => song.caption.length > 0),
      true,
    );
    check(
      "and some for the words it sang",
      takes.some((song) => song.lyrics.length > 0),
      true,
    );
  } else {
    console.log("\nthe listing decides what exists:\n");
    await radio.refreshAvailable();
    check("the station's files on disk are found", radio.radioState.available.length, 2);
    check(
      "a played take keeps its theme, which lives in the page's record",
      radio.radioState.available.find((song) => song.file?.filename.endsWith("_00001.mp3"))?.theme,
      "a block that raised you",
    );
    check(
      "a take the listing leaves out stays out",
      radio.radioState.available.some((song) => song.file?.filename.endsWith("_00099.mp3")),
      false,
    );

    console.log("\na station with no saved record still lists its files:\n");
    radio.radioState.stationId = "trap-after-dark";
    radio.radioState.history = [];
    rendererHistory = {};
    await radio.refreshAvailable();
    check("the files are found with an empty record", radio.radioState.available.length, 1);

    console.log("\nwith no listing route, the page uses what it remembers:\n");
    listingAvailable = false;
    radio.radioState.stationId = "boom-bap-basement";
    radio.radioState.history = [];
    await radio.refreshAvailable();
    check("the addresses it kept are still offered", radio.radioState.available.length, 2);

    console.log("\nthe record holds as the user moves between stations:\n");
    radio.radioState.history = [playedBoomBap, deletedBoomBap];
    radio.selectStation("drill-corridor");
    const stored = JSON.parse(store.get("mm.radio.history") ?? "{}");
    check("the station that was left keeps its takes", stored["boom-bap-basement"]?.length, 2);
  }
} finally {
  await server.close();
}

console.log(
  failures.length === 0
    ? LIVE
      ? "\nthe running renderer's listing is what the radio plays from"
      : "\nthe catalogue comes from the files, and holds through a reload, an empty renderer and a switch"
    : `\n${failures.length} failure(s): ${failures.join(", ")}`,
);
process.exit(failures.length === 0 ? 0 : 1);
