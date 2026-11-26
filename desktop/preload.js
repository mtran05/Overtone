"use strict";

// The only API the page may call. Names match the ipc handlers in main.js.

const { contextBridge, ipcRenderer } = require("electron");

// Subscribe to one main-process event and return the function that undoes it,
// so a React effect can clean up instead of stacking a listener per mount.
function listen(channel, handler) {
  const listener = (_event, payload) => handler(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("rvc", {
  assets: () => ipcRenderer.invoke("assets"),
  browse: (kind) => ipcRenderer.invoke("browse", kind),
  devices: () => ipcRenderer.invoke("devices"),
  configure: (opts) => ipcRenderer.invoke("configure", opts),
  start: (opts) => ipcRenderer.invoke("start", opts),
  stop: () => ipcRenderer.invoke("stop"),
  setHotkeys: (binds) => ipcRenderer.invoke("hotkeys", binds),
  onLog: (callback) => listen("log", (line) => callback(line)),
  onState: (callback) => listen("state", (state) => callback(state)),
  onHotkey: (callback) => listen("hotkey", (id) => callback(id)),
});
