// Registering system-wide soundboard keys, against a fake globalShortcut.

import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { applyHotkeys } = require("../main/hotkeys.js");

function fakeShortcuts(taken = []) {
  const handlers = new Map();
  return {
    handlers,
    cleared: 0,
    unregisterAll() {
      this.cleared += 1;
      handlers.clear();
    },
    register(accelerator, handler) {
      if (taken.includes(accelerator)) return false;
      if (accelerator === "Bogus+Key") throw new Error("Invalid accelerator");
      handlers.set(accelerator, handler);
      return true;
    },
  };
}

describe("applyHotkeys", () => {
  it("registers each bind and reports the pad id when pressed", () => {
    const shortcuts = fakeShortcuts();
    const pressed = [];
    const result = applyHotkeys(
      shortcuts,
      [
        { id: "airhorn", accelerator: "Ctrl+1" },
        { id: "drum", accelerator: "F9" },
      ],
      (id) => pressed.push(id),
    );
    expect(result).toEqual({ registered: ["Ctrl+1", "F9"], failed: [] });
    shortcuts.handlers.get("F9")();
    expect(pressed).toEqual(["drum"]);
  });

  it("replaces the previous set, and an empty list clears it", () => {
    const shortcuts = fakeShortcuts();
    applyHotkeys(shortcuts, [{ id: "a", accelerator: "Ctrl+1" }], () => {});
    applyHotkeys(shortcuts, [], () => {});
    expect(shortcuts.cleared).toBe(2);
    expect(shortcuts.handlers.size).toBe(0);
  });

  it("reports shortcuts another app owns, and invalid ones, as failed", () => {
    const shortcuts = fakeShortcuts(["Ctrl+2"]);
    const result = applyHotkeys(
      shortcuts,
      [
        { id: "a", accelerator: "Ctrl+2" },
        { id: "b", accelerator: "Bogus+Key" },
        { id: "c", accelerator: "num1" },
      ],
      () => {},
    );
    expect(result).toEqual({ registered: ["num1"], failed: ["Ctrl+2", "Bogus+Key"] });
  });

  it("gives a key bound to two pads to the first one, and skips malformed entries", () => {
    const shortcuts = fakeShortcuts();
    const pressed = [];
    applyHotkeys(shortcuts, [{ id: "first", accelerator: "F1" }, { id: "second", accelerator: "F1" }, null, { id: 3 }], (id) => pressed.push(id));
    shortcuts.handlers.get("F1")();
    expect(pressed).toEqual(["first"]);
  });
});
