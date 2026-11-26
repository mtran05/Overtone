// Soundboard keybinds, written the way Electron's globalShortcut expects them
// ("Ctrl+Shift+A", "F5", "num1"), so the same string works for the in-window
// key handler and for system-wide shortcuts.
//
// Keys are read from KeyboardEvent.code (the physical key), not .key, so a
// bind means the same key whatever the keyboard layout or Shift state.

const MODIFIERS = ["Ctrl", "Alt", "Shift", "Super"] as const;

// KeyboardEvent.code values that are not a letter, digit, F-key, or numpad digit.
const NAMED_KEYS: Record<string, string> = {
  Space: "Space",
  Enter: "Enter",
  Tab: "Tab",
  ArrowUp: "Up",
  ArrowDown: "Down",
  ArrowLeft: "Left",
  ArrowRight: "Right",
  Home: "Home",
  End: "End",
  PageUp: "PageUp",
  PageDown: "PageDown",
  Insert: "Insert",
  NumpadAdd: "numadd",
  NumpadSubtract: "numsub",
  NumpadMultiply: "nummult",
  NumpadDivide: "numdiv",
  NumpadDecimal: "numdec",
  Minus: "-",
  Equal: "=",
  BracketLeft: "[",
  BracketRight: "]",
  Backslash: "\\",
  Semicolon: ";",
  Quote: "'",
  Comma: ",",
  Period: ".",
  Slash: "/",
  Backquote: "`",
};

/** The key part of a bind for one KeyboardEvent.code, or null when it cannot be bound. */
export function keyFromCode(code: string): string | null {
  const letter = /^Key([A-Z])$/.exec(code);
  if (letter) return letter[1];
  const digit = /^Digit([0-9])$/.exec(code);
  if (digit) return digit[1];
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  const numpad = /^Numpad([0-9])$/.exec(code);
  if (numpad) return `num${numpad[1]}`;
  return NAMED_KEYS[code] ?? null;
}

export interface KeyLike {
  code: string;
  ctrlKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  metaKey: boolean;
}

/** The bind for a key press, such as "Ctrl+Shift+A", or null for a lone modifier or an unbindable key. */
export function acceleratorFromEvent(event: KeyLike): string | null {
  const key = keyFromCode(event.code);
  if (!key) return null;
  const held = [event.ctrlKey && "Ctrl", event.altKey && "Alt", event.shiftKey && "Shift", event.metaKey && "Super"].filter(Boolean);
  return [...held, key].join("+");
}

/**
 * Bring a saved bind up to date. Older versions stored a single key: an upper-case
 * character ("A", "1", " ") or a KeyboardEvent.code ("F5", "Numpad1", "ArrowUp").
 */
export function normalizeKeybind(saved: string | undefined): string | undefined {
  if (!saved) return undefined;
  if (saved === " ") return "Space";
  const parts = saved.split("+");
  if (parts.length > 1 && parts.slice(0, -1).every((part) => (MODIFIERS as readonly string[]).includes(part))) return saved;
  if (/^[A-Za-z]$/.test(saved)) return saved.toUpperCase();
  if (/^[0-9]$/.test(saved)) return saved;
  const fromCode = keyFromCode(saved);
  if (fromCode) return fromCode;
  // A punctuation character saved from KeyboardEvent.key.
  const punctuation = Object.values(NAMED_KEYS).find((key) => key === saved);
  return punctuation ?? saved;
}

/**
 * Whether a bind is safe to register system-wide. A global shortcut takes the key
 * from every other app, so a plain letter would stop you typing it anywhere. Only
 * combinations with Ctrl, Alt, or the Windows key, and keys nobody types with
 * (F-keys and the numpad), go global; the rest work while Overtone has focus.
 */
export function canBeGlobal(keybind: string | undefined): boolean {
  if (!keybind) return false;
  const parts = keybind.split("+");
  const key = parts[parts.length - 1];
  const modifiers = parts.slice(0, -1);
  if (modifiers.some((part) => part === "Ctrl" || part === "Alt" || part === "Super")) return true;
  return /^F([1-9]|1[0-9]|2[0-4])$/.test(key) || /^num/.test(key);
}
