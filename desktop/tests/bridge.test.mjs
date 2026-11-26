// The page and the main process only agree on the names in preload.js. Nothing
// at build time checks that renderer/src/lib/bridge.ts still matches it, so this
// test reads both files and compares them directly.

import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const desktop = path.resolve(here, "..");

const preload = readFileSync(path.join(desktop, "preload.js"), "utf8");
const bridge = readFileSync(path.join(desktop, "renderer", "src", "lib", "bridge.ts"), "utf8");

// `name: (...) => ...` inside the object exposed to the page.
const exposedNames = () => [...preload.matchAll(/^[ \t]+(\w+):/gm)].map((match) => match[1]);

// Lines of the RvcBridge interface body.
const interfaceBody = () => bridge.slice(bridge.indexOf("export interface RvcBridge"), bridge.indexOf("export interface InferenceOpts"));

const declaredSignatures = () => [...interfaceBody().matchAll(/^[ \t]+(\w+):/gm)].map((match) => match[1]);

describe("the preload bridge", () => {
  it("exposes exactly the methods RvcBridge declares", () => {
    // Guards against the patterns matching nothing, which would make this pass vacuously.
    expect(exposedNames().length).toBeGreaterThan(0);
    expect(exposedNames().sort()).toEqual(declaredSignatures().sort());
  });

  it("exposes nothing extra, which would widen the sandbox for no reason", () => {
    const extra = exposedNames().filter((name) => !declaredSignatures().includes(name));
    expect(extra).toEqual([]);
  });

  it("keeps the ipc channel names used by preload.js in sync with main/ipc.js", () => {
    const ipc = readFileSync(path.join(desktop, "main", "ipc.js"), "utf8");
    const handled = [...ipc.matchAll(/ipcMain\.handle\("(\w+)"/g)].map((match) => match[1]).sort();
    const invoked = [...preload.matchAll(/ipcRenderer\.invoke\("(\w+)"/g)].map((match) => match[1]).sort();
    expect(handled).toEqual(invoked);
  });

  it("listens only on channels the main process actually emits", () => {
    // emit() in python.js, and sendEvent() in worker.js, which defaults to it.
    const mainDir = path.join(desktop, "main");
    const source = readdirSync(mainDir)
      .filter((name) => name.endsWith(".js"))
      .map((name) => readFileSync(path.join(mainDir, name), "utf8"))
      .join("\n");
    const emitted = new Set([...source.matchAll(/(?:emit|sendEvent)\("(\w+)"/g)].map((match) => match[1]));
    const listened = [...preload.matchAll(/listen\("(\w+)"/g)].map((match) => match[1]);
    expect(listened.sort()).toEqual(["log", "state"]);
    for (const channel of listened) expect(emitted.has(channel), channel).toBe(true);
  });

  it("returns an unsubscribe function from every listener", () => {
    expect(preload).toContain("return () => ipcRenderer.removeListener(channel, listener);");
    for (const name of ["onLog", "onState"]) expect(interfaceBody()).toMatch(new RegExp(`${name}: \\(callback: [^\\n]*\\) => Unsubscribe;`));
  });
});
