// `npm start` skips the renderer build when renderer/dist is newer than every
// source it was built from. These tests lay out a fake desktop folder and move
// file times around to check that decision.

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createRequire } from "node:module";
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const require = createRequire(import.meta.url);
const { needsRendererBuild } = require("../ensure-electron.js");

let root;

// Write a file under the fake root and set its modification time, in seconds.
function touch(relative, seconds) {
  const file = path.join(root, relative);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, "");
  utimesSync(file, seconds, seconds);
}

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), "overtone-build-"));
  touch("renderer/src/main.tsx", 1000);
  touch("renderer/index.html", 1000);
  touch("shared/opts-spec.json", 1000);
  // Folder times move when files are added, so pin them too.
  for (const dir of ["renderer/src", "renderer", "shared"]) utimesSync(path.join(root, dir), 1000, 1000);
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("needsRendererBuild", () => {
  it("builds when there is no dist yet", () => {
    expect(needsRendererBuild(root)).toBe(true);
  });

  it("skips the build when dist is newer than every source", () => {
    touch("renderer/dist/index.html", 2000);
    expect(needsRendererBuild(root)).toBe(false);
  });

  it("rebuilds when a renderer source changed after the build", () => {
    touch("renderer/dist/index.html", 2000);
    touch("renderer/src/main.tsx", 3000);
    expect(needsRendererBuild(root)).toBe(true);
  });

  it("rebuilds when the shared option spec changed after the build", () => {
    touch("renderer/dist/index.html", 2000);
    touch("shared/opts-spec.json", 3000);
    expect(needsRendererBuild(root)).toBe(true);
  });
});
