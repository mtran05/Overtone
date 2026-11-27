# Desktop app

The desktop app runs the same converter as [`inference.realtime --live`](cli.md) and exposes every option through a graphical interface. It drives the Python environment you set up in the [quick start](../README.md#quick-start); it does not install Python or download models for you.

- [Run from source](#run-from-source)
- [Build a portable executable](#build-a-portable-executable)
- [The Live page](#the-live-page)
- [Presets](#presets)
- [Soundboard](#soundboard)
- [Environment variables](#environment-variables)

## Run from source

```powershell
cd desktop
npm install
npm start
```

`desktop` is an npm workspace, so one `npm install` installs both the Electron shell and the React renderer. `npm start` rebuilds the renderer only when its sources have changed since the last build. Delete `renderer\dist` to force a rebuild.

## Build a portable executable

```powershell
cd desktop
npm install
npm run pack
```

This runs the full verification suite, builds the renderer and produces `desktop\dist\Overtone.exe`.

> [!IMPORTANT]
> Keep `Overtone.exe` inside the project folder, for example in `desktop\dist`. On launch it searches upward, at most eight folders, for the folder that contains both `.venv\Scripts\python.exe` and `inference\realtime.py`.

Models in `assets\weights` and indexes in `assets\indices` appear in the app automatically, and you can browse to files stored anywhere else.

## The Live page

Pick a voice model and the app starts loading it in the background right away, so **Go live** is near-instant when you press it. Every control stays available while you're live: pitch, formant, pitch tracker, index, gains, devices, even the model.

The status lamp in the top-right corner shows what's happening:

| Lamp               | Meaning                                                              |
| ------------------ | -------------------------------------------------------------------- |
| **Loading voice…** | A model was picked; it's loading and warming up in the background    |
| **Ready**          | Loaded and warm; **Go live** opens the audio in under a second       |
| **Starting…**      | Opening the audio, or briefly restarting it after a change           |
| **Live**           | Audio is flowing                                                     |
| **Stopped**        | Audio stopped without you pressing Stop, for example a device error  |

Most changes apply from the next block with no gap. Changing devices, the block size or the model restarts the audio briefly, for about a second at most. [Architecture](architecture.md#what-a-change-costs) lists which option does what.

**Stop** closes the audio but keeps the voice loaded, so going live again is instant. **More settings** opens every other option, including the **Safety buffer**, which helps if the voice cuts out (see [Troubleshooting](troubleshooting.md#live-audio-crackles-or-drops-out)).

## Presets

Each preset is a saved voice profile: a model and all its settings, with an optional picture. Going live saves the current settings into the active preset, or creates one for a new model. **Load preset** restores a profile and starts preloading its model.

Pictures are shrunk to a small thumbnail when you choose them, because presets are kept in the app's local storage, which only holds a few megabytes.

## Soundboard

The **SFX** page holds sound pads. Each pad has its own volume and keybind, and a master volume scales them all. Drop clips into `assets\sounds` or use **Add sound**. **Secondary output** plays each sound into a second device too, such as a virtual cable into voice chat, while you hear it on your own speakers.

### Soundboard keys

Click **Bind** on a pad, then press a key or combination. Esc cancels, and Backspace clears the bind. Pad keys work on every page while Overtone has focus.

Turn on **Work in other apps** to make them fire while a game or voice chat has focus too. A system-wide shortcut takes its key away from every other app, so only these binds go global:

- combinations with Ctrl, Alt or the Windows key, such as `Ctrl+1` or `Alt+Shift+Q`;
- F-keys and numpad keys.

Plain keys like `A` keep working inside Overtone only. Pads that work everywhere show a small lit dot. If another app already owns a shortcut, the log says so and that pad stays in-window.

## Environment variables

| Variable     | Purpose                                                                      |
| ------------ | ---------------------------------------------------------------------------- |
| `RVC_PYTHON` | Path to the Python interpreter to use instead of the project's `.venv`       |

The [command-line variables](cli.md#environment-variables) apply to the app too. Variables for working on the app itself are in [CONTRIBUTING.md](../CONTRIBUTING.md#environment-variables).
