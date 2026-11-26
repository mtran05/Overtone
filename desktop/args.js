"use strict";

// Build the argument list for `python -m inference.realtime --live`.
// parseDevices reads the JSON printed by --list-devices --json.
// Every flag, default, and choice comes from shared/opts-spec.json, which is
// also read by the renderer and by inference/realtime.py.

const { options: SPEC } = require("./shared/opts-spec.json");

const isNumber = (spec) => spec.kind === "number";

// Numeric options, in spec order, paired with their CLI flag.
const NUMBERS = Object.entries(SPEC)
  .filter(([, spec]) => isNumber(spec))
  .map(([key, spec]) => [key, spec.flag]);

// Options passed as a bare flag when true and omitted when false.
const FLAGS = Object.entries(SPEC)
  .filter(([, spec]) => spec.kind === "bool")
  .map(([key, spec]) => [key, spec.flag]);

// opts uses the page's field names. Empty optional strings are left off the command.
function buildArgs(opts) {
  if (!opts || !opts.model) throw new Error("Model is required");
  const f0Spec = SPEC.f0;
  if (!f0Spec.choices.includes(opts.f0)) {
    throw new Error(`Pitch method must be ${f0Spec.choices.join(", ")}`);
  }
  const latency = opts.latency == null ? "" : String(opts.latency).trim();
  if (latency && latency !== "low" && latency !== "high" && !Number.isFinite(Number(latency))) {
    throw new Error("Latency must be low, high, or seconds");
  }
  const numbers = {};
  for (const [key] of NUMBERS) {
    const value = Number(opts[key]);
    if (!Number.isFinite(value)) throw new Error(`${SPEC[key].flag} must be a number`);
    numbers[key] = value;
  }
  if (numbers.f0Min <= 0 || numbers.f0Max <= numbers.f0Min) {
    throw new Error("Lowest pitch must be above 0 and below the highest pitch");
  }
  if (numbers.inputChannels < 1 || numbers.outputChannels < 1) {
    throw new Error("Channel counts must be at least 1");
  }
  if (numbers.indexNeighbors < 1) throw new Error("Index neighbors must be at least 1");

  const args = ["-m", "inference.realtime", "--live", "--model", String(opts.model), "--f0", opts.f0];
  if (opts.index) args.push(SPEC.index.flag, String(opts.index));
  if (opts.inputDevice) args.push(SPEC.inputDevice.flag, String(opts.inputDevice));
  if (opts.outputDevice) args.push(SPEC.outputDevice.flag, String(opts.outputDevice));
  if (opts.hostApi) args.push(SPEC.hostApi.flag, String(opts.hostApi).trim());
  if (latency) args.push(SPEC.latency.flag, latency);
  for (const [key, flag] of NUMBERS) args.push(flag, String(numbers[key]));
  for (const [key, flag] of FLAGS) if (opts[key]) args.push(flag);
  return args;
}

// Read the JSON printed by `--list-devices --json`. Entries without a numeric
// index or a name are dropped, so a stray Python warning cannot fill a dropdown.
function parseDevices(text) {
  let rows;
  try {
    rows = JSON.parse(String(text).trim());
  } catch {
    throw new Error("Could not read the device list from Python");
  }
  if (!Array.isArray(rows)) throw new Error("Could not read the device list from Python");
  return rows
    .filter((row) => row && Number.isInteger(row.index) && typeof row.name === "string")
    .map((row) => ({
      index: row.index,
      inputs: Number(row.inputs) || 0,
      outputs: Number(row.outputs) || 0,
      rate: Number(row.rate) || 0,
      host: String(row.host ?? ""),
      name: row.name.trim(),
      note: String(row.note ?? ""),
    }));
}

// The starting opts: exactly what shared/opts-spec.json declares, so a new
// option needs no change here.
function defaultOpts() {
  const opts = {};
  for (const [key, spec] of Object.entries(SPEC)) opts[key] = spec.default;
  return opts;
}

module.exports = { buildArgs, parseDevices, defaultOpts };
