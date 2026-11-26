"use strict";

// System-wide soundboard shortcuts. The page sends the binds it wants global
// (it has already filtered out plain typing keys, see renderer/src/lib/hotkeys.ts);
// this registers them with Electron and tells the page when one is pressed,
// whichever app has focus.

// Replace every registered bind with `binds` ([{ id, accelerator }]). Returns
// which accelerators registered and which failed, usually because another app
// already owns that shortcut.
function applyHotkeys(globalShortcut, binds, onPress) {
  globalShortcut.unregisterAll();
  const registered = [];
  const failed = [];
  const seen = new Set();
  for (const bind of Array.isArray(binds) ? binds : []) {
    if (!bind || typeof bind.id !== "string" || typeof bind.accelerator !== "string") continue;
    // Two pads on one key: the first one keeps it.
    if (seen.has(bind.accelerator)) continue;
    seen.add(bind.accelerator);
    let ok = false;
    try {
      ok = globalShortcut.register(bind.accelerator, () => onPress(bind.id));
    } catch {
      ok = false;
    }
    (ok ? registered : failed).push(bind.accelerator);
  }
  return { registered, failed };
}

module.exports = { applyHotkeys };
