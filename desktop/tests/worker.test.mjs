// The Electron side of the Python worker: reading its event lines, and the
// lifecycle of the one long-lived process. Spawning is faked, so no Python runs.

import { Buffer } from "node:buffer";
import { EventEmitter } from "node:events";
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";

// worker.js requires python.js, which requires electron only through state.js
// (it does not), so plain CommonJS loading is enough here.
const require = createRequire(import.meta.url);
const { createWorker, lineSplitter, parseWorkerLine } = require("../main/worker.js");

// A stand-in for a spawned child process: streams, stdin writes, and exit.
function fakeChild() {
  const child = new EventEmitter();
  child.pid = 1234;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.stdin = new EventEmitter();
  child.stdin.written = [];
  child.stdin.ended = false;
  child.stdin.write = (text) => child.stdin.written.push(text);
  child.stdin.end = () => {
    child.stdin.ended = true;
  };
  child.killed = false;
  child.kill = () => {
    child.killed = true;
    child.emit("exit", null);
  };
  return child;
}

function setup() {
  const children = [];
  const events = [];
  const spawnProcess = vi.fn(() => {
    const child = fakeChild();
    children.push(child);
    return child;
  });
  const worker = createWorker({ python: "python.exe", root: "/proj", spawnProcess, send: (channel, payload) => events.push([channel, payload]) });
  return { worker, children, events, spawnProcess };
}

const sent = (child) => child.stdin.written.map((line) => JSON.parse(line));

afterEach(() => {
  vi.useRealTimers();
});

describe("parseWorkerLine", () => {
  it("reads state and error events", () => {
    expect(parseWorkerLine('{"event": "state", "state": "live"}')).toEqual({ kind: "state", state: "live" });
    expect(parseWorkerLine('{"event": "error", "message": "Model not found: x.pth"}')).toEqual({ kind: "error", message: "Model not found: x.pth" });
  });

  it("shows anything else as a log line rather than dropping it", () => {
    expect(parseWorkerLine("Traceback (most recent call last):")).toEqual({ kind: "log", line: "Traceback (most recent call last):" });
    expect(parseWorkerLine('{"event": "state", "state": "melting"}').kind).toBe("log");
    expect(parseWorkerLine('{"event": "error"}').kind).toBe("log");
    expect(parseWorkerLine("[1, 2]").kind).toBe("log");
  });
});

describe("lineSplitter", () => {
  it("joins lines split across chunks and skips blank ones", () => {
    const lines = [];
    const feed = lineSplitter((line) => lines.push(line));
    feed(Buffer.from('{"event": "sta'));
    feed(Buffer.from('te", "state": "ready"}\r\n\r\nINFO one\nINFO tw'));
    feed(Buffer.from("o\n"));
    expect(lines).toEqual(['{"event": "state", "state": "ready"}', "INFO one", "INFO two"]);
  });
});

describe("createWorker", () => {
  it("starts one process on first use and reuses it", () => {
    const { worker, children, spawnProcess } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    worker.send("start", ["--model", "a.pth"]);
    expect(spawnProcess).toHaveBeenCalledTimes(1);
    expect(spawnProcess.mock.calls[0][1]).toEqual(["-m", "inference.worker"]);
    expect(sent(children[0])).toEqual([
      { cmd: "configure", argv: ["--model", "a.pth"] },
      { cmd: "start", argv: ["--model", "a.pth"] },
    ]);
  });

  it("does not start a process just to stop it", () => {
    const { worker, spawnProcess } = setup();
    worker.stop();
    expect(spawnProcess).not.toHaveBeenCalled();
  });

  it("forwards states, errors, and stderr to the page", () => {
    const { worker, children, events } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    const child = children[0];
    child.stdout.emit("data", Buffer.from('{"event": "state", "state": "loading"}\n{"event": "error", "message": "bad"}\n'));
    child.stderr.emit("data", Buffer.from("INFO Loading RMVPE model\n"));
    expect(events).toEqual([
      ["state", "loading"],
      ["log", "bad"],
      ["log", "INFO Loading RMVPE model"],
    ]);
  });

  it("reports idle when the process dies and starts a new one on the next command", () => {
    const { worker, children, events, spawnProcess } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    children[0].emit("exit", 1);
    expect(events).toContainEqual(["state", "idle"]);
    expect(events.some(([channel, line]) => channel === "log" && /exited \(1\)/.test(line))).toBe(true);
    expect(worker.isRunning()).toBe(false);
    worker.send("configure", ["--model", "a.pth"]);
    expect(spawnProcess).toHaveBeenCalledTimes(2);
  });

  it("treats a process that never spawned as gone, so quitting does not hang", async () => {
    const { worker, children } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    children[0].pid = undefined;
    children[0].emit("error", new Error("spawn python.exe ENOENT"));
    expect(worker.isRunning()).toBe(false);
    await expect(worker.shutdown()).resolves.toBeUndefined();
  });

  it("shuts down by closing stdin, without a crash message", async () => {
    const { worker, children, events } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    const done = worker.shutdown();
    expect(children[0].stdin.ended).toBe(true);
    children[0].emit("exit", 0);
    await done;
    expect(children[0].killed).toBe(false);
    expect(events.some(([channel, line]) => channel === "log" && /exited/.test(line))).toBe(false);
  });

  it("kills a worker that does not exit after stdin closes", async () => {
    vi.useFakeTimers();
    const { worker, children } = setup();
    worker.send("configure", ["--model", "a.pth"]);
    const done = worker.shutdown();
    await vi.advanceTimersByTimeAsync(3000);
    await done;
    expect(children[0].killed).toBe(true);
  });
});
