// Typed view of the API preload.js exposes as window.rvc.
// The shape mirrors the ipcMain handlers in desktop/main.js;
// when a handler's payload changes, update InferenceOpts/Device here too.
export interface Assets {
  models: string[];
  indices: string[];
  sounds?: string[];
}

export interface Device {
  index: number;
  inputs: number;
  outputs: number;
  rate: number;
  host: string;
  name: string;
  note: string;
}

/**
 * What the Python worker is doing, as reported by inference/worker.py:
 * idle (no model loaded), loading (preparing a model), ready (loaded, not live),
 * starting (opening the stream, loading first if needed), live (audio flowing).
 */
export type WorkerState = "idle" | "loading" | "ready" | "starting" | "live";

/** Removes the listener it came from. Return it from a React effect. */
export type Unsubscribe = () => void;

export interface RvcBridge {
  assets: () => Promise<Assets>;
  browse: (kind: "model" | "index" | "audio" | "image") => Promise<string | null>;
  devices: () => Promise<{ ok: true; devices: Device[] } | { ok: false; error: string }>;
  /** Load or update the model without starting or stopping audio. */
  configure: (opts: InferenceOpts) => Promise<{ ok: true } | { ok: false; error: string }>;
  start: (opts: InferenceOpts) => Promise<{ ok: true } | { ok: false; error: string }>;
  stop: () => Promise<{ ok: true }>;
  onLog: (callback: (line: string) => void) => Unsubscribe;
  onState: (callback: (state: WorkerState) => void) => Unsubscribe;
}

export interface InferenceOpts {
  model: string;
  index: string;
  indexRate: number;
  key: number;
  formant: number;
  f0: "rmvpe" | "fcpe" | "pm";
  sampleRate: number;
  blockTime: number;
  crossfadeTime: number;
  extraTime: number;
  rmsMixRate: number;
  inputDevice: string;
  outputDevice: string;
  hostApi: string;
  inputChannels: number;
  outputChannels: number;
  latency: string;
  inputGain: number;
  outputGain: number;
  noClip: boolean;
  wasapiExclusive: boolean;
  wasapiAutoConvert: boolean;
  f0Min: number;
  f0Max: number;
  rmvpeThreshold: number;
  fcpeThreshold: number;
  indexNeighbors: number;
}

declare global {
  interface Window {
    rvc?: RvcBridge;
  }
}

// Returns the bridge when running inside Electron, undefined in a plain browser
// (the app then shows "Preview" instead of live data).
export function bridge(): RvcBridge | undefined {
  return window.rvc;
}
