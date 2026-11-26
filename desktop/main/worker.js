"use strict";

// The one long-lived Python process, `python -m inference.worker`. It is
// started on the first configure or start and kept, so the model stays loaded
// between sessions. See inference/worker.py for the protocol.
//
// Closing its stdin is how it is told to exit, so if this process dies the
// worker notices end-of-input and exits too instead of holding the mic and GPU.

const { spawn } = require("child_process");
const { emit, pythonEnv } = require("./python");

const STATES = new Set(["idle", "loading", "ready", "starting", "live"]);
const SHUTDOWN_GRACE_MS = 3000;

// One stdout line from the worker, sorted into a state change, an error, or a
// plain log line. Anything that is not a known event is shown as a log line.
function parseWorkerLine(line) {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return { kind: "log", line };
  }
  if (message && message.event === "state" && STATES.has(message.state)) return { kind: "state", state: message.state };
  if (message && message.event === "error" && typeof message.message === "string") return { kind: "error", message: message.message };
  return { kind: "log", line };
}

// Turn chunks into whole lines. Python may split a line across chunks.
function lineSplitter(onLine) {
  let buffer = "";
  return (chunk) => {
    buffer += chunk.toString("utf8");
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop();
    for (const line of lines) if (line.trim()) onLine(line);
  };
}

function createWorker({ python, root, spawnProcess = spawn, send: sendEvent = emit }) {
  let proc = null;
  let quitting = false;
  let exited = null;

  function ensure() {
    if (proc) return proc;
    const child = spawnProcess(python, ["-m", "inference.worker"], { cwd: root, windowsHide: true, env: pythonEnv() });
    proc = child;
    let settle;
    exited = new Promise((resolve) => (settle = resolve));
    // A spawn that never started (no pid) may report "error" without ever
    // reporting "exit". Treat it as gone, or quitting would wait forever.
    const gone = () => {
      if (proc === child) proc = null;
      settle();
    };
    child.stdout.on(
      "data",
      lineSplitter((line) => {
        const parsed = parseWorkerLine(line);
        if (parsed.kind === "state") sendEvent("state", parsed.state);
        else if (parsed.kind === "error") sendEvent("log", parsed.message);
        else sendEvent("log", parsed.line);
      }),
    );
    child.stderr.on(
      "data",
      lineSplitter((line) => sendEvent("log", line)),
    );
    // A write after the worker died must not crash the main process.
    child.stdin.on("error", () => {});
    child.on("error", (error) => {
      sendEvent("log", `Python worker: ${error.message}`);
      if (child.pid === undefined) {
        gone();
        sendEvent("state", "idle");
      }
    });
    child.on("exit", (code) => {
      gone();
      sendEvent("state", "idle");
      if (!quitting) sendEvent("log", `Python worker exited (${code}). It starts again on the next change.`);
    });
    return child;
  }

  function send(cmd, argv) {
    const child = ensure();
    child.stdin.write(`${JSON.stringify(argv ? { cmd, argv } : { cmd })}\n`);
  }

  // Stopping never starts a worker just to tell it to stop.
  function stop() {
    if (proc) send("stop");
  }

  // Ask the worker to exit and wait for it, killing it if it does not exit in time.
  function shutdown() {
    quitting = true;
    const child = proc;
    if (!child) return Promise.resolve();
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), SHUTDOWN_GRACE_MS);
    return exited.then(() => clearTimeout(timer));
  }

  return { send, stop, shutdown, isRunning: () => proc !== null };
}

module.exports = { createWorker, parseWorkerLine, lineSplitter };
