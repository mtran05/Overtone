import { describe, expect, it } from "vitest";
import { acceleratorFromEvent, canBeGlobal, keyFromCode, normalizeKeybind } from "./hotkeys";

const press = (code: string, mods: Partial<{ ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }> = {}) => ({
  code,
  ctrlKey: false,
  altKey: false,
  shiftKey: false,
  metaKey: false,
  ...mods,
});

describe("keyFromCode", () => {
  it("names letters, digits, F-keys, and the numpad the way Electron does", () => {
    expect(keyFromCode("KeyQ")).toBe("Q");
    expect(keyFromCode("Digit7")).toBe("7");
    expect(keyFromCode("F12")).toBe("F12");
    expect(keyFromCode("Numpad3")).toBe("num3");
    expect(keyFromCode("NumpadAdd")).toBe("numadd");
    expect(keyFromCode("ArrowLeft")).toBe("Left");
    expect(keyFromCode("Space")).toBe("Space");
  });

  it("refuses keys that cannot be bound", () => {
    expect(keyFromCode("ShiftLeft")).toBeNull();
    expect(keyFromCode("ControlRight")).toBeNull();
    expect(keyFromCode("Escape")).toBeNull();
    expect(keyFromCode("F25")).toBeNull();
  });
});

describe("acceleratorFromEvent", () => {
  it("puts modifiers first, in a fixed order", () => {
    expect(acceleratorFromEvent(press("KeyA", { shiftKey: true, ctrlKey: true }))).toBe("Ctrl+Shift+A");
    expect(acceleratorFromEvent(press("Digit1", { altKey: true, metaKey: true }))).toBe("Alt+Super+1");
    expect(acceleratorFromEvent(press("F5"))).toBe("F5");
  });

  it("ignores a modifier pressed on its own, so you can hold it before the key", () => {
    expect(acceleratorFromEvent(press("ControlLeft", { ctrlKey: true }))).toBeNull();
  });

  it("uses the physical key, so Shift does not change which key it is", () => {
    expect(acceleratorFromEvent(press("Digit1", { shiftKey: true }))).toBe("Shift+1");
  });
});

describe("normalizeKeybind", () => {
  it("upgrades single-key binds saved by older versions", () => {
    expect(normalizeKeybind("a")).toBe("A");
    expect(normalizeKeybind("A")).toBe("A");
    expect(normalizeKeybind("5")).toBe("5");
    expect(normalizeKeybind(" ")).toBe("Space");
    expect(normalizeKeybind("Numpad1")).toBe("num1");
    expect(normalizeKeybind("ArrowUp")).toBe("Up");
    expect(normalizeKeybind("F5")).toBe("F5");
    expect(normalizeKeybind("-")).toBe("-");
  });

  it("leaves current binds and empty values alone", () => {
    expect(normalizeKeybind("Ctrl+Shift+A")).toBe("Ctrl+Shift+A");
    expect(normalizeKeybind(undefined)).toBeUndefined();
    expect(normalizeKeybind("")).toBeUndefined();
  });
});

describe("canBeGlobal", () => {
  it("allows combinations with Ctrl, Alt, or the Windows key", () => {
    expect(canBeGlobal("Ctrl+1")).toBe(true);
    expect(canBeGlobal("Alt+Shift+Q")).toBe(true);
    expect(canBeGlobal("Super+F")).toBe(true);
  });

  it("allows keys nobody types with", () => {
    expect(canBeGlobal("F9")).toBe(true);
    expect(canBeGlobal("num4")).toBe(true);
    expect(canBeGlobal("Shift+F2")).toBe(true);
  });

  it("keeps typing keys in-window, so they still work in other apps", () => {
    expect(canBeGlobal("A")).toBe(false);
    expect(canBeGlobal("Shift+A")).toBe(false);
    expect(canBeGlobal("Space")).toBe(false);
    expect(canBeGlobal("1")).toBe(false);
    expect(canBeGlobal(undefined)).toBe(false);
  });
});
