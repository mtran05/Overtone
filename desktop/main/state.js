"use strict";

// The desktop window, kept in one module so the IPC handlers and the event
// sender in python.js cannot each end up holding a different copy. The Python
// worker is owned by main.js and handed to the IPC handlers.

const state = {
  win: null,
};

module.exports = {
  getWin: () => state.win,
  setWin: (win) => {
    state.win = win;
  },
};
