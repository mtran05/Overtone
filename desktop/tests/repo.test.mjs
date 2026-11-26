// Ported from the self-check block that used to live at the bottom of repo.js.
// This file is ESM because Vitest is ESM; the module under test is CommonJS and
// arrives through Node's default-interop.

import { describe, expect, it } from "vitest";
import path from "node:path";
import { createRequire } from "node:module";

// Node's own loader, not Vite's: repo.js is CommonJS.
const require = createRequire(import.meta.url);
const { findRepo, missingBaseModels } = require("../repo.js");

const ROOT = path.resolve("/proj");
const PYTHON = path.join(ROOT, ".venv", "Scripts", "python.exe");
const ENTRY = path.join(ROOT, "inference", "realtime.py");
const EXE_DIR = path.join(ROOT, "desktop", "dist");

// A predicate that says "only these two paths exist".
const onlyProject = (file) => file === PYTHON || file === ENTRY;

describe("findRepo", () => {
  it("finds the project from a nested folder", () => {
    expect(findRepo([EXE_DIR], onlyProject)).toEqual({ root: ROOT, python: PYTHON });
  });

  it("returns null when neither marker exists", () => {
    expect(findRepo([EXE_DIR], () => false)).toBeNull();
  });

  it("ignores empty and missing start paths", () => {
    expect(findRepo([], onlyProject)).toBeNull();
    expect(findRepo([null, undefined, ""], onlyProject)).toBeNull();
  });

  it("needs both markers, not just one", () => {
    const pythonOnly = (file) => file === PYTHON;
    expect(findRepo([EXE_DIR], pythonOnly)).toBeNull();
  });

  it("gives up rather than looping forever at the drive root", () => {
    expect(findRepo(["Z:\\not-a-real-root"], onlyProject)).toBeNull();
  });

  it("still finds the project when two start paths overlap", () => {
    expect(findRepo([EXE_DIR, path.join(ROOT, "desktop")], onlyProject)).toEqual({ root: ROOT, python: PYTHON });
  });
});

describe("missingBaseModels", () => {
  const HUBERT = path.join(ROOT, "assets", "hubert_base");
  const RMVPE = path.join(ROOT, "assets", "rmvpe", "rmvpe.pt");
  const present =
    (...files) =>
    (file) =>
      files.includes(file);
  const hubertFiles = [path.join(HUBERT, "config.json"), path.join(HUBERT, "pytorch_model.bin")];

  it("passes when HuBERT and RMVPE are both downloaded", () => {
    expect(missingBaseModels(ROOT, "rmvpe", present(...hubertFiles, RMVPE))).toBeNull();
  });

  it("accepts safetensors HuBERT weights", () => {
    expect(missingBaseModels(ROOT, "fcpe", present(path.join(HUBERT, "config.json"), path.join(HUBERT, "model.safetensors")))).toBeNull();
  });

  it("names HuBERT and the download command when it is missing", () => {
    const message = missingBaseModels(ROOT, "rmvpe", present(RMVPE));
    expect(message).toContain("HuBERT model missing");
    expect(message).toContain('--include "hubert_base/*"');
  });

  it("treats a HuBERT folder without weights as missing", () => {
    expect(missingBaseModels(ROOT, "pm", present(path.join(HUBERT, "config.json")))).toContain("HuBERT model missing");
  });

  it("asks for RMVPE only when it is the chosen pitch tracker", () => {
    expect(missingBaseModels(ROOT, "rmvpe", present(...hubertFiles))).toContain("RMVPE model missing");
    expect(missingBaseModels(ROOT, "fcpe", present(...hubertFiles))).toBeNull();
    expect(missingBaseModels(ROOT, "pm", present(...hubertFiles))).toBeNull();
  });
});
