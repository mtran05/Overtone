import type { WorkerState } from "./bridge";

// What the status lamp shows, worked out from the Python worker's state. Kept
// apart from the React session so the rules can be tested on their own.

export type Status = "Idle" | "Loading" | "Ready" | "Starting" | "Live" | "Stopped" | "Preview";

export const STATUS_LABEL: Record<Status, string> = {
  Idle: "Idle",
  Loading: "Loading voice…",
  Ready: "Ready",
  Starting: "Starting…",
  Live: "Live",
  Stopped: "Stopped",
  Preview: "Preview",
};

/** Starting and live both mean audio is, or is about to be, flowing: the button reads Stop. */
export function isRunning(state: WorkerState): boolean {
  return state === "starting" || state === "live";
}

/** True when audio stopped without the user pressing Stop, such as a device error. */
export function stoppedUnexpectedly(previous: WorkerState, next: WorkerState, stopRequested: boolean): boolean {
  return isRunning(previous) && !isRunning(next) && !stopRequested;
}

/** The lamp state. Stopped is kept until the next load or start replaces it. */
export function statusFor(state: WorkerState, stopped: boolean): Status {
  if (state === "loading") return "Loading";
  if (state === "starting") return "Starting";
  if (state === "live") return "Live";
  if (stopped) return "Stopped";
  return state === "ready" ? "Ready" : "Idle";
}
