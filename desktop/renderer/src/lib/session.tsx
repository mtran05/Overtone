import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { bridge, type Device, type InferenceOpts, type WorkerState } from "./bridge";
import { shrinkImage } from "./images";
import { createPreset, loadActivePresetId, loadStoredPresets, saveActivePresetId, saveStoredPresets, upsertPresetOnLive, type Preset } from "./presets";
import { sanitizeOpts } from "./sanitize";
import { STATUS_LABEL, isRunning, statusFor, stoppedUnexpectedly, type Status } from "./status";
import { defaultOpts } from "./specs";
import { useDevices, type DeviceScan } from "../hooks/useDevices";
import { useLog } from "../hooks/useLog";

// Shared live-session state: what the Python worker is doing, the status lamp
// text, the tail of the process log, the form settings, the saved model
// presets, and the scanned audio device list.
//
// This lives above the router so the worker keeps reporting while the user is
// on the Presets or SFX page, and so returning to Live restores the previous
// settings and device list instead of resetting them.
//
// Every change to the options is sent to the worker (after a short pause, so a
// dragged slider is one update, not fifty). Idle, that preloads the model so Go
// live is near-instant; live, the worker applies the change in place.
export interface Session {
  /** True while starting or live: the Go live button reads Stop. */
  running: boolean;
  /** Machine-readable state, used to pick the lamp colour. */
  status: Status;
  /** What the lamp actually says. Scanning overrides the label while idle. */
  statusLabel: string;
  logLines: string[];
  opts: InferenceOpts;
  presets: Preset[];
  activePresetId: string | null;
  scan: DeviceScan;
  devices: Device[];
  pushLog: (line: string) => void;
  clearLog: () => void;
  startLive: (liveOpts: InferenceOpts) => Promise<void>;
  stopLive: () => Promise<void>;
  setOpt: <K extends keyof InferenceOpts>(key: K, value: InferenceOpts[K]) => void;
  setOpts: (next: InferenceOpts | ((o: InferenceOpts) => InferenceOpts)) => void;
  createPresetFromOpts: (sourceOpts?: InferenceOpts, overrides?: { name?: string; image?: string }) => Preset;
  updatePreset: (id: string, patch: Partial<Pick<Preset, "name" | "image" | "opts" | "lastUsedAt">>) => void;
  deletePreset: (id: string) => void;
  loadPreset: (id: string) => void;
  recordLivePreset: (liveOpts: InferenceOpts) => void;
  refreshDevices: () => Promise<void>;
}

const SessionContext = createContext<Session | null>(null);

// A shrunk 192px WebP is a few tens of kilobytes. Anything well past that is a full-size original.
const LARGE_IMAGE_CHARS = 200_000;

// How long the options must stay unchanged before they are sent to the worker.
const CONFIGURE_DELAY_MS = 250;

export function SessionProvider({ children }: { children: ReactNode }) {
  const [workerState, setWorkerState] = useState<WorkerState>("idle");
  const [stopped, setStopped] = useState(false);
  const [preview, setPreview] = useState(false);
  const running = isRunning(workerState);
  const runningRef = useRef(running);
  runningRef.current = running;
  const stopRequested = useRef(false);
  const [opts, setOptsState] = useState<InferenceOpts>(defaultOpts);
  const [presets, setPresets] = useState<Preset[]>(loadStoredPresets);
  const [activePresetId, setActivePresetId] = useState<string | null>(loadActivePresetId);
  const { lines, push: pushLog, clear: clearLog } = useLog();

  // Report a failed save once, not on every later edit, and again only after a save has worked.
  const saveFailed = useRef(false);
  useEffect(() => {
    const saved = saveStoredPresets(presets);
    if (!saved && !saveFailed.current) pushLog("Presets could not be saved: storage is full. Clear some preset images and try again.");
    saveFailed.current = !saved;
  }, [presets, pushLog]);

  // Presets saved before images were shrunk on import can hold full-size photos. Shrink those once.
  useEffect(() => {
    let cancelled = false;
    for (const preset of loadStoredPresets()) {
      if (preset.image.length <= LARGE_IMAGE_CHARS) continue;
      void shrinkImage(preset.image).then((image) => {
        if (cancelled || image === preset.image) return;
        setPresets((current) => current.map((item) => (item.id === preset.id && item.image === preset.image ? { ...item, image } : item)));
      });
    }
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    saveActivePresetId(activePresetId);
  }, [activePresetId]);

  const startLive = useCallback(
    async (liveOpts: InferenceOpts) => {
      const rvc = bridge();
      if (!rvc) return;
      stopRequested.current = false;
      setStopped(false);
      const result = await rvc.start(liveOpts);
      if (!result.ok) pushLog(result.error);
    },
    [pushLog],
  );

  const stopLive = useCallback(async () => {
    const rvc = bridge();
    if (!rvc) return;
    stopRequested.current = true;
    await rvc.stop();
  }, []);

  const setOpts = useCallback((next: InferenceOpts | ((o: InferenceOpts) => InferenceOpts)) => {
    setOptsState((o) => (typeof next === "function" ? next(o) : next));
  }, []);

  const setOpt = useCallback(<K extends keyof InferenceOpts>(key: K, value: InferenceOpts[K]) => setOptsState((o) => ({ ...o, [key]: value })), []);

  const createPresetFromOpts = useCallback(
    (sourceOpts?: InferenceOpts, overrides?: { name?: string; image?: string }) => {
      const created = createPreset(sourceOpts ?? opts, overrides);
      setPresets((current) => [created, ...current]);
      setActivePresetId(created.id);
      return created;
    },
    [opts],
  );

  const updatePreset = useCallback((id: string, patch: Partial<Pick<Preset, "name" | "image" | "opts" | "lastUsedAt">>) => {
    setPresets((current) =>
      current.map((item) => {
        if (item.id !== id) return item;
        return {
          ...item,
          ...patch,
          opts: patch.opts ? sanitizeOpts(patch.opts) : item.opts,
        };
      }),
    );
  }, []);

  const deletePreset = useCallback((id: string) => {
    setPresets((current) => current.filter((item) => item.id !== id));
    setActivePresetId((currentId) => (currentId === id ? null : currentId));
  }, []);

  const loadPreset = useCallback(
    (id: string) => {
      const found = presets.find((item) => item.id === id);
      if (!found) return;
      const cleaned = sanitizeOpts(found.opts);
      setOptsState(cleaned);
      setActivePresetId(found.id);
      setPresets((current) => current.map((item) => (item.id === id ? { ...item, lastUsedAt: Date.now() } : item)));
      pushLog(`Loaded preset: ${found.name}`);
    },
    [presets, pushLog],
  );

  const recordLivePreset = useCallback(
    (liveOpts: InferenceOpts) => {
      const next = upsertPresetOnLive(presets, activePresetId, liveOpts);
      setPresets(next.presets);
      setActivePresetId(next.activePresetId);
    },
    [presets, activePresetId],
  );

  // Device problems belong in the log as well as next to the dropdowns.
  const { scan, refresh: refreshDevices, devices } = useDevices(pushLog);

  // Subscribe once so the worker keeps reporting while another page is open.
  const lastState = useRef<WorkerState>("idle");
  useEffect(() => {
    const rvc = bridge();
    if (!rvc) {
      setPreview(true);
      return;
    }
    const unsubscribers = [
      rvc.onLog(pushLog),
      rvc.onState((next) => {
        if (stoppedUnexpectedly(lastState.current, next, stopRequested.current)) setStopped(true);
        else if (next !== "idle" && next !== "ready") setStopped(false);
        lastState.current = next;
        setWorkerState(next);
      }),
    ];
    // StrictMode mounts effects twice in development; without this every log line would arrive twice.
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
  }, [pushLog]);

  // Send settled options to the worker. Errors while idle are left for Go live
  // to report, so typing a path does not fill the log; while live they matter now.
  useEffect(() => {
    const rvc = bridge();
    if (!rvc || !opts.model) return;
    const timer = setTimeout(() => {
      void rvc.configure(sanitizeOpts(opts)).then((result) => {
        if (!result.ok && runningRef.current) pushLog(result.error);
      });
    }, CONFIGURE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [opts, pushLog]);

  const status: Status = preview ? "Preview" : statusFor(workerState, stopped);

  const value = useMemo<Session>(
    () => ({
      running,
      status,
      statusLabel: !running && scan.kind === "loading" ? "Looking for devices…" : STATUS_LABEL[status],
      logLines: lines,
      opts,
      presets,
      activePresetId,
      scan,
      devices,
      pushLog,
      clearLog,
      startLive,
      stopLive,
      setOpt,
      setOpts,
      createPresetFromOpts,
      updatePreset,
      deletePreset,
      loadPreset,
      recordLivePreset,
      refreshDevices,
    }),
    [
      running,
      status,
      lines,
      opts,
      presets,
      activePresetId,
      scan,
      devices,
      pushLog,
      clearLog,
      startLive,
      stopLive,
      setOpt,
      setOpts,
      createPresetFromOpts,
      updatePreset,
      deletePreset,
      loadPreset,
      recordLivePreset,
      refreshDevices,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside a SessionProvider");
  return session;
}
