# Troubleshooting

- [The desktop app says it could not find the project](#the-desktop-app-says-it-could-not-find-the-project)
- [The lamp never gets past Loading voice…](#the-lamp-never-gets-past-loading-voice)
- [Live audio crackles or drops out](#live-audio-crackles-or-drops-out)
- [Several devices match, or none does](#several-devices-match-or-none-does)
- [The converted voice sounds robotic or off-pitch](#the-converted-voice-sounds-robotic-or-off-pitch)
- [A soundboard key doesn't work in other apps](#a-soundboard-key-doesnt-work-in-other-apps)

## The desktop app says it could not find the project

`Overtone.exe` must sit somewhere inside the project folder, no more than eight levels deep, and the project must contain `.venv\Scripts\python.exe`. Alternatively, set `RVC_PYTHON` to your interpreter's path.

## The lamp never gets past Loading voice…

Read the log at the bottom of the window. Usual causes:

- **A base model is missing.** The log names the file and gives the exact `hf download` command. See [step 3 of the quick start](../README.md#3-download-the-base-models). RMVPE is only needed when it's the chosen pitch tracker.
- **PyTorch can't see your GPU.** On the CPU, loading and warming up take much longer. Check that the CUDA build of PyTorch is installed, as in [step 2 of the quick start](../README.md#2-install-dependencies).

## Live audio crackles or drops out

Check the log to confirm inference is running on your GPU and not the CPU. Then try, in order:

- **A safety buffer:** set **Safety buffer (blocks)** in More settings, or `--safety-blocks 1` or `2`. Conversion moves to its own thread, and the output runs that many blocks behind, so a slow moment, such as a game busy on the GPU, doesn't cut the voice out. The cost is that much extra delay.
- **A larger block:** raise `--block-time` (for example to `0.35`).
- **The lighter tracker:** switch to `fcpe`.
- **More output buffering:** try `--latency high`.

## Several devices match, or none does

Run `--list-devices` and pass the device's numeric index, or add `--host-api` to narrow the search. The same device often appears once per host API.

## The converted voice sounds robotic or off-pitch

- **Pitch:** adjust `--key` so it suits the target voice, for example +12 for a male-to-female conversion.
- **Background noise:** raise `--rmvpe-threshold`, or `--fcpe-threshold` for FCPE.
- **Index:** tune `--index-rate`.

## A soundboard key doesn't work in other apps

- **The key isn't eligible.** Only combinations with Ctrl, Alt or the Windows key, F-keys and numpad keys can work outside Overtone, so normal typing is never taken. Pads that work everywhere show a small lit dot.
- **Another app owns it.** If another app already registered the same shortcut, the log says so and the pad works only while Overtone has focus. Pick another combination.

See [Soundboard keys](desktop.md#soundboard-keys).
