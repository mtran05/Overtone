# Command line

The CLI entry point is `inference.realtime`. Run it from the repository root, with the virtual environment from the [quick start](../README.md#quick-start) active. `python -m inference.realtime --help` prints every option.

- [Live microphone conversion](#live-microphone-conversion)
- [File conversion](#file-conversion)
- [Choosing audio devices](#choosing-audio-devices)
- [All options](#all-options)
- [Environment variables](#environment-variables)

## Live microphone conversion

```powershell
python -m inference.realtime --model assets/weights/myvoice.pth --index assets/indices/myvoice.index --live
```

This plays your converted voice through the default speakers. Press `Ctrl+C` to stop.

Before the audio opens, the converter runs two silent warm-up blocks. That loads the pitch model and records the GPU work, so the first real blocks don't drop out. See [Architecture](architecture.md#warm-up) for details.

## File conversion

Leave out `--live` and pass `--input` and `--output` instead:

```powershell
python -m inference.realtime --model assets/weights/myvoice.pth --index assets/indices/myvoice.index --input voice.wav --output converted.wav
```

- **Input:** `.wav`, `.flac` or `.ogg`. Stereo is mixed to mono, and any sample rate is resampled.
- **Output:** a `.wav` at the model's sample rate, or at `--sample-rate` if set. Choose the format with `--subtype`: `FLOAT` (default), `PCM_16`, `PCM_24` or `PCM_32`.
- **Same path as live:** the file goes through the same blocks and crossfade as live audio, so what you hear live is what you get on disk.

## Choosing audio devices

List every input and output device PortAudio can see:

```powershell
python -m inference.realtime --list-devices
```

Add `--json` for machine-readable output. This is what the desktop app uses.

Then select devices by index or by part of their name:

```powershell
python -m inference.realtime --model assets/weights/myvoice.pth --live --input-device "Microphone" --output-device "CABLE Input" --host-api WASAPI
```

The same device often appears once per host API (MME, DirectSound, WASAPI). If a name matches more than one, add `--host-api` or pass the numeric index.

## All options

Every option is defined once in [`desktop/shared/opts-spec.json`](../desktop/shared/opts-spec.json), which also feeds the desktop app's controls, so this list and the app always agree.

### Voice

| Flag           | Default | Description                                                    |
| -------------- | ------- | -------------------------------------------------------------- |
| `--model`      | —       | Path to a trained `.pth` voice model (required)                |
| `--index`      | —       | Optional `.index` retrieval file                               |
| `--index-rate` | `0.75`  | How strongly to blend toward the index, from 0 to 1            |
| `--index-neighbors` | `8` | How many index vectors to blend for each frame                |

### Pitch

| Flag                | Default | Description                                                      |
| ------------------- | ------- | ---------------------------------------------------------------- |
| `--key`             | `0`     | Pitch shift in semitones, from −24 to 24                         |
| `--formant`         | `0`     | Formant shift in semitones: brighter or darker without moving the note as much |
| `--f0`              | `rmvpe` | Pitch tracker: `rmvpe` (most accurate), `fcpe` (lighter) or `pm` (classic, CPU) |
| `--f0-min`          | `50`    | Lowest pitch treated as voiced, in Hz                            |
| `--f0-max`          | `1100`  | Highest pitch, in Hz                                             |
| `--rmvpe-threshold` | `0.03`  | How sure RMVPE must be before it counts a note. Higher ignores more noise. |
| `--fcpe-threshold`  | `0.006` | The same, for FCPE                                               |

### Gain

| Flag             | Default | Description                                                         |
| ---------------- | ------- | ------------------------------------------------------------------- |
| `--rms-mix-rate` | `0`     | `0` follows your loudness, `1` keeps the model's loudness           |
| `--input-gain`   | `1`     | Multiply the microphone or file before conversion                   |
| `--output-gain`  | `1`     | Multiply the converted audio                                        |
| `--no-clip`      | off     | Leave samples outside −1..1 instead of clipping them                |

### Timing

| Flag               | Default | Description                                                                 |
| ------------------ | ------- | --------------------------------------------------------------------------- |
| `--block-time`     | `0.25`  | Block length in seconds. Lower means less delay but more GPU load.          |
| `--crossfade-time` | `0.05`  | Crossfade between blocks, in seconds                                        |
| `--extra-time`     | `2.5`   | Seconds of earlier audio fed to the model ahead of each block               |
| `--safety-blocks`  | `0`     | Blocks of extra delay that absorb an occasional slow block. See [Troubleshooting](troubleshooting.md#live-audio-crackles-or-drops-out). |

### Device

| Flag                    | Default | Description                                                    |
| ----------------------- | ------- | -------------------------------------------------------------- |
| `--input-device`        | system  | Microphone number from `--list-devices`, or part of its name   |
| `--output-device`       | system  | Speaker number or part of its name                             |
| `--host-api`            | any     | Only match devices on this host API, such as `WASAPI`          |
| `--input-channels`      | `1`     | Microphone channels to open, then mix to mono                  |
| `--output-channels`     | `2`     | Speaker channels. The mono output is copied to each.           |
| `--sample-rate`         | model   | Stream sample rate. `0` uses the model's rate.                 |
| `--latency`             | auto    | `low`, `high`, or a number of seconds                          |
| `--wasapi-exclusive`    | off     | Open WASAPI devices in exclusive mode, for the lowest latency  |
| `--wasapi-auto-convert` | off     | Let WASAPI resample if the device rate differs                 |

### CLI only

| Flag             | Description                                               |
| ---------------- | --------------------------------------------------------- |
| `--live`         | Convert the microphone live instead of a file             |
| `--input`        | Input audio file for file mode                            |
| `--output`       | Output `.wav` path for file mode                          |
| `--subtype`      | Output sample format: `FLOAT`, `PCM_16`, `PCM_24`, `PCM_32` |
| `--list-devices` | Print the audio devices and exit                          |
| `--json`         | With `--list-devices`, print JSON instead of a table      |

## Environment variables

| Variable                   | Purpose                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| `RVC_CUDA_GRAPH`           | Set to `0` to turn off CUDA graph replay. It's on by default where it works. |
| `RVC_CUDA_GRAPH_MAX_CACHE` | How many recorded graph shapes to keep per model (default `8`)           |

The desktop app has a few of its own; see [Desktop app](desktop.md#environment-variables).
