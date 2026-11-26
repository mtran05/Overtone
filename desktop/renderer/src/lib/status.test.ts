import { describe, expect, it } from "vitest";
import { STATUS_LABEL, isRunning, statusFor, stoppedUnexpectedly } from "./status";

describe("statusFor", () => {
  it("follows the worker through a normal session", () => {
    expect(statusFor("idle", false)).toBe("Idle");
    expect(statusFor("loading", false)).toBe("Loading");
    expect(statusFor("ready", false)).toBe("Ready");
    expect(statusFor("starting", false)).toBe("Starting");
    expect(statusFor("live", false)).toBe("Live");
  });

  it("shows Stopped only while nothing newer is happening", () => {
    expect(statusFor("ready", true)).toBe("Stopped");
    expect(statusFor("idle", true)).toBe("Stopped");
    expect(statusFor("loading", true)).toBe("Loading");
    expect(statusFor("live", true)).toBe("Live");
  });

  it("has a label for every status", () => {
    for (const label of Object.values(STATUS_LABEL)) expect(label.length).toBeGreaterThan(0);
    expect(STATUS_LABEL.Loading).toBe("Loading voice…");
  });
});

describe("isRunning", () => {
  it("counts starting and live, so Stop can cancel a start", () => {
    expect(["idle", "loading", "ready", "starting", "live"].filter((state) => isRunning(state as never))).toEqual(["starting", "live"]);
  });
});

describe("stoppedUnexpectedly", () => {
  it("flags audio that stopped on its own", () => {
    expect(stoppedUnexpectedly("live", "ready", false)).toBe(true);
    expect(stoppedUnexpectedly("starting", "ready", false)).toBe(true);
    expect(stoppedUnexpectedly("live", "idle", false)).toBe(true);
  });

  it("ignores a stop the user asked for", () => {
    expect(stoppedUnexpectedly("live", "ready", true)).toBe(false);
  });

  it("ignores a brief restart while live, such as a model switch", () => {
    expect(stoppedUnexpectedly("live", "starting", false)).toBe(false);
    expect(stoppedUnexpectedly("starting", "live", false)).toBe(false);
  });

  it("ignores changes that never involved audio", () => {
    expect(stoppedUnexpectedly("loading", "ready", false)).toBe(false);
  });
});
