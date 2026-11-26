"use strict";

// Running Python for one-shot commands (device listing), and sending events to
// the page. The long-lived live converter is in worker.js.

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { getWin } = require("./state");

// Force UTF-8 and unbuffered logs so lines reach the window as they are printed.
function pythonEnv() {
  return { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUNBUFFERED: "1" };
}

// Sorted full paths of files in dir that end with ext (string or string[]). Empty when the folder is missing.
function filesIn(dir, ext) {
  if (!fs.existsSync(dir)) return [];
  const exts = Array.isArray(ext) ? ext : [ext];
  return fs
    .readdirSync(dir)
    .filter((name) => exts.some((suffix) => name.toLowerCase().endsWith(suffix)))
    .map((name) => path.join(dir, name))
    .sort();
}

// Run Python to completion and return stdout. Used for --list-devices, not the live stream.
function runPython(python, root, args, missing) {
  return new Promise((resolve, reject) => {
    const problem = missing();
    if (problem) {
      reject(new Error(problem));
      return;
    }
    const proc = spawn(python, args, { cwd: root, windowsHide: true, env: pythonEnv() });
    let out = "";
    let err = "";
    proc.stdout.on("data", (chunk) => {
      out += chunk;
    });
    proc.stderr.on("data", (chunk) => {
      err += chunk;
    });
    proc.on("error", reject);
    proc.on("close", (code) => {
      if (code === 0) resolve(out);
      else reject(new Error((err || out).trim() || `Python exited ${code}`));
    });
  });
}

// Send one event to the page. Ignored if the window is already gone.
function emit(channel, payload) {
  const win = getWin();
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

module.exports = { filesIn, pythonEnv, runPython, emit };
