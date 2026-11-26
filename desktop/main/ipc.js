"use strict";

// The IPC handlers the page can call. Their names and payloads are the
// contract described by RvcBridge in renderer/src/lib/bridge.ts; changing one
// side without the other will fail the preload shape test in desktop/tests.

const fs = require("fs");
const path = require("path");
const { dialog, globalShortcut, ipcMain } = require("electron");
const { buildArgs, parseDevices } = require("../args");
const { missingBaseModels } = require("../repo");
const { applyHotkeys } = require("./hotkeys");
const { emit, filesIn, runPython } = require("./python");
const { getWin } = require("./state");

const AUDIO_EXTS = [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"];
const IMAGE_MIME = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
};

function registerIpc(locator, worker) {
  const { root, python, missing } = locator;

  // Check the page's options and turn them into worker flags, or say what is wrong.
  function prepare(opts) {
    const problem = missing();
    if (problem) return { error: problem };
    let argv;
    try {
      argv = buildArgs(opts);
    } catch (error) {
      return { error: error.message };
    }
    const noBaseModels = missingBaseModels(root, opts.f0);
    if (noBaseModels) return { error: noBaseModels };
    if (!fs.existsSync(opts.model)) return { error: `Model not found: ${opts.model}` };
    if (opts.index && !fs.existsSync(opts.index)) return { error: `Index not found: ${opts.index}` };
    return { argv };
  }

  // Models live in assets/weights, index files in assets/indices, sounds in assets/sounds.
  ipcMain.handle("assets", () => {
    if (!root) return { models: [], indices: [], sounds: [] };
    return {
      models: filesIn(path.join(root, "assets", "weights"), ".pth"),
      indices: filesIn(path.join(root, "assets", "indices"), ".index"),
      sounds: filesIn(path.join(root, "assets", "sounds"), AUDIO_EXTS),
    };
  });

  // kind is "model", "index", "audio", or "image". Returns the chosen path (or data URL for image), or null if cancelled.
  ipcMain.handle("browse", async (_event, kind) => {
    const picker =
      kind === "model"
        ? {
            title: "Voice model",
            defaultPath: root ? path.join(root, "assets", "weights") : undefined,
            filters: [{ name: "Voice model", extensions: ["pth"] }],
          }
        : kind === "index"
          ? {
              title: "Index",
              defaultPath: root ? path.join(root, "assets", "indices") : undefined,
              filters: [{ name: "Index", extensions: ["index"] }],
            }
          : kind === "audio"
            ? {
                title: "Audio clip",
                defaultPath: root ? path.join(root, "assets", "sounds") : undefined,
                filters: [{ name: "Audio", extensions: ["mp3", "wav", "ogg", "flac", "m4a", "aac"] }],
              }
            : {
                title: "Profile image",
                filters: [{ name: "Image", extensions: ["png", "jpg", "jpeg", "webp", "gif", "svg"] }],
              };

    const result = await dialog.showOpenDialog(getWin(), {
      ...picker,
      properties: ["openFile"],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    const chosen = result.filePaths[0];
    if (kind === "image") {
      try {
        const ext = path.extname(chosen).toLowerCase();
        const mime = IMAGE_MIME[ext] || "image/png";
        const data = fs.readFileSync(chosen);
        return `data:${mime};base64,${data.toString("base64")}`;
      } catch {
        return null;
      }
    }
    return chosen;
  });

  // Ask Python for the PortAudio device list as JSON for the two dropdowns.
  ipcMain.handle("devices", async () => {
    try {
      const text = await runPython(python, root, ["-m", "inference.realtime", "--list-devices", "--json"], missing);
      return { ok: true, devices: parseDevices(text) };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  });

  // Load or update the model without starting audio. The page calls this
  // whenever the options change: idle, it preloads so Go live is instant;
  // live, the worker applies the change with the least work it can.
  ipcMain.handle("configure", (_event, opts) => {
    if (!opts || !opts.model) return { ok: true };
    const prepared = prepare(opts);
    if (prepared.error) return { ok: false, error: prepared.error };
    worker.send("configure", prepared.argv);
    return { ok: true };
  });

  // Go live. Progress arrives as "state" events, not as this reply.
  ipcMain.handle("start", (_event, opts) => {
    const prepared = prepare(opts || {});
    if (prepared.error) return { ok: false, error: prepared.error };
    worker.send("start", prepared.argv);
    return { ok: true };
  });

  // System-wide soundboard keys. Each call replaces the whole set; [] clears it.
  ipcMain.handle("hotkeys", (_event, binds) => applyHotkeys(globalShortcut, binds, (id) => emit("hotkey", id)));

  // Close the stream. The model stays loaded for the next start.
  ipcMain.handle("stop", () => {
    worker.stop();
    return { ok: true };
  });
}

module.exports = { registerIpc };
