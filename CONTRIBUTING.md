# Contributing

Thanks for helping. This guide covers setting up, testing, and the conventions the code follows. For how the pieces fit together, read [Architecture](docs/architecture.md) first.

- [Setup](#setup)
- [Python](#python)
- [Desktop](#desktop)
- [Adding an inference option](#adding-an-inference-option)
- [Styling conventions](#styling-conventions)
- [Environment variables](#environment-variables)
- [Continuous integration](#continuous-integration)

## Setup

Follow the [quick start](README.md#quick-start) to create `.venv`, install PyTorch and the requirements, and download the base models. Then install the development tools:

```powershell
python -m pip install -r requirements-dev.txt
```

For the desktop app you also need Node.js 22.12 or newer.

## Python

Run these from the repository root:

```powershell
python -m pytest
```

```powershell
python -m ruff check inference tests
```

The tests need no GPU and no audio device:

- the worker's decisions, the device handling and the live callback run against fakes;
- the converter's block and crossfade path runs on the CPU with a stand-in model.

Keep it that way, so the tests also run in CI. The synthesizer in `inference/module/` is ported from upstream RVC and left as it is, so it stays easy to re-sync. ruff skips it.

## Desktop

All desktop scripts run from the `desktop` folder.

| Script                            | What it does                                                                      |
| --------------------------------- | --------------------------------------------------------------------------------- |
| `npm run verify`                  | Runs `format:check`, `lint`, `typecheck` and `test`. Run this before committing.  |
| `npm test`                        | Vitest across the Electron main process, the shared option spec and the renderer. |
| `npm run lint`                    | ESLint with zero warnings allowed.                                                |
| `npm run format` / `format:check` | Prettier.                                                                         |
| `npm run typecheck`               | `tsc --noEmit` over the renderer.                                                 |
| `npm run dev`                     | Vite dev server for the renderer, with hot reload.                                |
| `npm start`                       | Launches Electron.                                                                |
| `npm run pack`                    | `verify`, then the renderer build, then `electron-builder` into `desktop\dist`.   |

### Front-end development with live reload

Run the Vite dev server and point Electron at it, each in its own terminal:

```powershell
cd desktop
npm run dev
```

```powershell
cd desktop
$env:VITE_DEV_SERVER_URL="http://localhost:5173"; npm start
```

## Adding an inference option

Every option is described once in [`desktop/shared/opts-spec.json`](desktop/shared/opts-spec.json). That file feeds `inference/realtime.py`'s argument parser, the flags `desktop/args.js` sends to the worker, and the renderer's form controls.

1. **Add the option to `opts-spec.json`.** It appears in `python -m inference.realtime --help` and in the app's **More settings** sheet.
2. **Give it an `apply` value** saying what changing it costs while live (see [What a change costs](docs/architecture.md#what-a-change-costs)). If it can change while live, make the worker apply it in `Worker._apply` in [`inference/worker.py`](inference/worker.py).
3. **Add its type** to `InferenceOpts` in [`desktop/renderer/src/lib/bridge.ts`](desktop/renderer/src/lib/bridge.ts).
4. **Read it in the Python code** where it's needed.
5. **List it** in the options tables in [docs/cli.md](docs/cli.md#all-options).

## Styling conventions

- [`renderer/src/styles/global.css`](desktop/renderer/src/styles/global.css) holds only what has no owning component: the reset, the design tokens in `:root` and element defaults.
- [`renderer/src/styles/controls.module.css`](desktop/renderer/src/styles/controls.module.css) holds the shared look of plain inputs and selects.
- Everything else lives in the CSS module next to its component.

## Environment variables

These help when working on the app:

| Variable              | Purpose                                                                                        |
| --------------------- | ---------------------------------------------------------------------------------------------- |
| `VITE_DEV_SERVER_URL` | Makes Electron load the renderer from the Vite dev server, for hot reload                      |
| `DEBUG_LAYOUT`        | Development only: writes the window's layout geometry to `%TEMP%\layout-report.txt` and exits  |

The variables that change how Overtone runs are in [docs/cli.md](docs/cli.md#environment-variables) and [docs/desktop.md](docs/desktop.md#environment-variables).

## Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to `main` or `beta` and on every pull request:

- **Python tests and lint**, on Ubuntu with the CPU build of PyTorch: `ruff check` and `pytest`.
- **Desktop verify**, on Windows: `npm ci` and `npm run verify`.

Both should pass before a pull request is merged.
