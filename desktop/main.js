"use strict";

// Desktop window for live voice conversion.
// Locates the project and its Python, opens the window, and hands the page an
// API through preload.js. The work lives in main/.

const path = require("path");
const { app, BrowserWindow } = require("electron");
const { registerIpc } = require("./main/ipc");
const { createLocator } = require("./main/locate");
const { setWin } = require("./main/state");
const { createWorker } = require("./main/worker");

const locator = createLocator();
// Started lazily on the first configure or start, then kept for the whole session.
const worker = createWorker(locator);

// Open the UI. The page cannot use Node; it talks to this process through preload.js.
function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 680,
    backgroundColor: "#12181c",
    autoHideMenuBar: true,
    title: "Overtone",
    icon: path.join(__dirname, "logo.png"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  setWin(win);
  win.once("ready-to-show", () => win.show());
  // Layout probe for diagnosing shell geometry. Development only: the packaged
  // app does not ship debug-layout.js. See that file for usage.
  if (process.env.DEBUG_LAYOUT && !app.isPackaged) require("./debug-layout")(win);
  win.on("closed", () => setWin(null));
  if (process.env.VITE_DEV_SERVER_URL) {
    win.loadURL(process.env.VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(path.join(__dirname, "renderer", "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  registerIpc(locator, worker);
  createWindow();
});

// Give the worker a moment to close the audio devices and exit, then quit for real.
app.on("before-quit", (event) => {
  if (!worker.isRunning()) return;
  event.preventDefault();
  worker.shutdown().then(() => app.quit());
});

app.on("window-all-closed", () => app.quit());
