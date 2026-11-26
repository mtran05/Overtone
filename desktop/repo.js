"use strict";

// Find the RVC project folder from the desktop app, a portable exe, or a parent directory.
// A hit is a folder that contains both .venv\Scripts\python.exe and inference\realtime.py.

const fs = require("fs");
const path = require("path");

// ponytail: walks 8 parents from the exe. Move the project higher if a deeper nest stops the search.
function findRepo(starts, exists = fs.existsSync) {
  const seen = new Set();
  for (const start of starts) {
    if (!start) continue;
    let dir = path.resolve(start);
    for (let i = 0; i < 8; i++) {
      if (seen.has(dir)) break;
      seen.add(dir);
      const python = path.join(dir, ".venv", "Scripts", "python.exe");
      const entry = path.join(dir, "inference", "realtime.py");
      if (exists(python) && exists(entry)) return { root: dir, python };
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return null;
}

// The downloaded base models every live session needs. RMVPE is only needed
// when it is the chosen pitch tracker; FCPE ships its weights inside torchfcpe.
// Returns a message naming what is missing and how to get it, or null.
function missingBaseModels(root, f0, exists = fs.existsSync) {
  const hubert = path.join(root, "assets", "hubert_base");
  const hubertWeights = ["pytorch_model.bin", "model.safetensors"].some((name) => exists(path.join(hubert, name)));
  if (!exists(path.join(hubert, "config.json")) || !hubertWeights) {
    return `HuBERT model missing from ${hubert}. Download it with: hf download lj1995/VoiceConversionWebUI --revision main --include "hubert_base/*" --local-dir assets`;
  }
  const rmvpe = path.join(root, "assets", "rmvpe", "rmvpe.pt");
  if (f0 === "rmvpe" && !exists(rmvpe)) {
    return `RMVPE model missing: ${rmvpe}. Download it with: hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main --local-dir assets/rmvpe, or choose the FCPE or PM pitch tracker.`;
  }
  return null;
}

module.exports = { findRepo, missingBaseModels };
