// Ported from the self-check block that used to live at the bottom of args.js.
// This file is ESM because Vitest is ESM; the module under test is CommonJS and
// arrives through Node's default-interop.

import { describe, expect, it } from "vitest";
import { createRequire } from "node:module";
import spec from "../shared/opts-spec.json" with { type: "json" };

// Node's own loader, not Vite's: args.js is CommonJS and require()s the spec
// itself, which the transform pipeline cannot resolve.
const require = createRequire(import.meta.url);
const { buildArgs, parseDevices, defaultOpts } = require("../args.js");
const OPTIONS = spec.options;

const errorFrom = (fn) => {
  try {
    fn();
  } catch (error) {
    return error.message;
  }
  return "";
};

describe("buildArgs", () => {
  const base = { ...defaultOpts(), model: "assets/weights/kikiV1.pth" };

  it("builds the minimum command", () => {
    const built = buildArgs(base);
    expect(built[0]).toBe("-m");
    expect(built[1]).toBe("inference.realtime");
    expect(built).toContain("--live");
    expect(built).toContain("--f0");
    expect(built[built.indexOf("--block-time") + 1]).toBe("0.25");
  });

  it("leaves optional values off the command when they are empty", () => {
    const built = buildArgs(base);
    for (const flag of ["--index", "--no-clip", "--input-device", "--output-device", "--host-api", "--latency"]) {
      expect(built).not.toContain(flag);
    }
  });

  it("adds every optional value when they are set", () => {
    const built = buildArgs({
      ...base,
      index: "voice.index",
      inputDevice: "1",
      outputDevice: "2",
      hostApi: " WASAPI ",
      latency: "low",
      noClip: true,
      wasapiExclusive: true,
      wasapiAutoConvert: true,
    });
    for (const flag of [
      "--index",
      "--input-device",
      "--output-device",
      "--host-api",
      "--latency",
      "--no-clip",
      "--wasapi-exclusive",
      "--wasapi-auto-convert",
    ]) {
      expect(built).toContain(flag);
    }
    expect(built[built.indexOf("--host-api") + 1]).toBe("WASAPI");
  });

  it("accepts a numeric latency", () => {
    const built = buildArgs({ ...base, latency: " 0.02 " });
    expect(built[built.indexOf("--latency") + 1]).toBe("0.02");
  });

  it("reports each invalid field with a readable message", () => {
    expect(errorFrom(() => buildArgs({ ...base, model: "" }))).toBe("Model is required");
    expect(errorFrom(() => buildArgs({ ...base, model: null }))).toBe("Model is required");
    expect(errorFrom(() => buildArgs({ ...base, f0: "nope" }))).toContain("Pitch method");
    expect(errorFrom(() => buildArgs({ ...base, f0Min: 80, f0Max: 40 }))).toContain("Lowest pitch");
    expect(errorFrom(() => buildArgs({ ...base, f0Min: 0 }))).toContain("Lowest pitch");
    expect(errorFrom(() => buildArgs({ ...base, latency: "fast" }))).toContain("Latency");
    expect(errorFrom(() => buildArgs({ ...base, indexNeighbors: 0 }))).toContain("neighbors");
    expect(errorFrom(() => buildArgs({ ...base, inputChannels: 0 }))).toContain("Channel counts");
    expect(errorFrom(() => buildArgs({ ...base, outputChannels: 0 }))).toContain("Channel counts");
    expect(errorFrom(() => buildArgs({ ...base, blockTime: "abc" }))).toContain("--block-time");
  });

  it("emits every numeric option the spec declares", () => {
    const built = buildArgs(base);
    for (const [key, option] of Object.entries(OPTIONS)) {
      if (option.kind !== "number") continue;
      expect(built, `missing ${option.flag}`).toContain(option.flag);
      expect(built[built.indexOf(option.flag) + 1]).toBe(String(base[key]));
    }
  });
});

describe("defaultOpts", () => {
  it("has an entry for every option in the shared spec", () => {
    expect(Object.keys(defaultOpts()).sort()).toEqual(Object.keys(OPTIONS).sort());
  });

  it("uses the spec defaults", () => {
    const opts = defaultOpts();
    for (const [key, option] of Object.entries(OPTIONS)) expect(opts[key]).toEqual(option.default);
  });

  it("feeds straight into buildArgs", () => {
    expect(() => buildArgs(defaultOpts())).toThrow("Model is required");
    expect(() => buildArgs({ ...defaultOpts(), model: "m.pth" })).not.toThrow();
  });
});

describe("parseDevices", () => {
  // Shaped exactly like `python -m inference.realtime --list-devices --json`.
  const listing = JSON.stringify([
    { index: 0, inputs: 2, outputs: 0, rate: 48000.0, host: "Windows WASAPI", name: "Microphone (Realtek)", note: "default input" },
    { index: 1, inputs: 0, outputs: 2, rate: 48000.0, host: "Windows DirectSound", name: "Speakers", note: "default output" },
  ]);

  it("reads every device and its default marks", () => {
    const devices = parseDevices(listing);
    expect(devices).toHaveLength(2);
    expect(devices[0]).toEqual({
      index: 0,
      inputs: 2,
      outputs: 0,
      rate: 48000,
      name: "Microphone (Realtek)",
      host: "Windows WASAPI",
      note: "default input",
    });
    expect(devices[1]).toMatchObject({ index: 1, inputs: 0, outputs: 2, host: "Windows DirectSound", note: "default output" });
  });

  it("keeps names that contain brackets and double spaces intact", () => {
    const [device] = parseDevices(
      JSON.stringify([{ index: 4, inputs: 1, outputs: 0, rate: 8000, host: "Windows WDM-KS", name: "Headset  (SOUNDPEATS Gamer)", note: "" }]),
    );
    expect(device.name).toBe("Headset  (SOUNDPEATS Gamer)");
  });

  it("drops entries without an index or a name", () => {
    expect(parseDevices(JSON.stringify([{ name: "no index" }, { index: 2 }, null]))).toEqual([]);
  });

  it("returns nothing for an empty list", () => {
    expect(parseDevices("[]")).toEqual([]);
  });

  it("throws on output that is not a JSON list", () => {
    expect(() => parseDevices("")).toThrow("Could not read the device list");
    expect(() => parseDevices("Traceback (most recent call last):")).toThrow("Could not read the device list");
    expect(() => parseDevices('{"index": 0}')).toThrow("Could not read the device list");
  });
});
