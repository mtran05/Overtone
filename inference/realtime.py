"""Run real-time voice conversion from a file or the microphone.

File mode writes a converted wav using the same block, overlap, and SOLA
crossfade path as live playback:

    python -m inference.realtime --model assets/weights/kikiV1.pth --index assets/indices/kikiV1.index --input voice.wav --output converted.wav

Live mode plays the microphone through the default speakers:

    python -m inference.realtime --model assets/weights/kikiV1.pth --index assets/indices/kikiV1.index --live
"""

import argparse
import json
import logging
import os
from pathlib import Path

import numpy as np

# Only light imports at module level: --list-devices must not pull in torch.
# The converter, soundfile, and sounddevice are imported where they are used.
from inference.opts import OPT_SPEC, PitchSettings


logger = logging.getLogger(__name__)


def _load_audio(path):
    """Read a file as mono float32 and return it with its sample rate."""
    import soundfile as sf

    audio, sample_rate = sf.read(path, always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    return audio, sample_rate


def _build_converter(args):
    """Build a RealtimeConverter from parsed CLI arguments."""
    # Loads torch, HuBERT, and the voice model, so it is the slow part of startup.
    from inference.converter import RealtimeConverter

    index_rate = args.index_rate if args.index else 0.0
    settings = PitchSettings(
        f0_min=args.f0_min,
        f0_max=args.f0_max,
        rmvpe_threshold=args.rmvpe_threshold,
        fcpe_threshold=args.fcpe_threshold,
        index_neighbors=args.index_neighbors,
    )
    return RealtimeConverter(
        model_path=args.model,
        index_path=args.index,
        index_rate=index_rate,
        key=args.key,
        formant=args.formant,
        f0_method=args.f0,
        sample_rate=args.sample_rate,
        block_time=args.block_time,
        crossfade_time=args.crossfade_time,
        extra_time=args.extra_time,
        rms_mix_rate=args.rms_mix_rate,
        settings=settings,
    )


def _convert_file(args):
    """Convert --input and write --output."""
    converter = _build_converter(args)
    audio, sample_rate = _load_audio(args.input)
    if args.input_gain != 1.0:
        audio = audio * args.input_gain
    converted = converter.convert(audio, sample_rate) * args.output_gain
    if not args.no_clip:
        converted = np.clip(converted, -1.0, 1.0)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf

    sf.write(output, converted, converter.sample_rate, subtype=args.subtype)
    logger.info("Wrote %s (%d samples at %d Hz)", output, len(converted), converter.sample_rate)


def _run_live(args):
    """Convert the chosen microphone and play it on the chosen speakers."""
    sd = _import_sounddevice()
    input_device = _resolve_device(args.input_device, "input", args.host_api)
    output_device = _resolve_device(args.output_device, "output", args.host_api)
    extra_settings = _wasapi_settings(sd, args, input_device, output_device)
    # Check the channel counts before loading the model, so a bad device fails
    # at once instead of after the model has loaded.
    input_device_info = sd.query_devices(
        input_device if input_device is not None else sd.default.device[0]
    )
    if args.input_channels > input_device_info["max_input_channels"]:
        raise SystemExit(
            f"Input device has {input_device_info['max_input_channels']} channels, "
            f"not {args.input_channels}"
        )
    output_device_info = sd.query_devices(
        output_device if output_device is not None else sd.default.device[1]
    )
    if args.output_channels > output_device_info["max_output_channels"]:
        raise SystemExit(
            f"Output device has {output_device_info['max_output_channels']} channels, "
            f"not {args.output_channels}"
        )

    converter = _build_converter(args)
    # Load the pitch model and record the GPU graphs now. Otherwise the first
    # live blocks do that work inside the audio callback and drop out.
    converter.warm_up()

    def callback(indata, outdata, frames, time_info, status):
        """Convert one microphone block and copy it into the speaker buffer."""
        if status:
            logger.warning("Audio stream: %s", status)
        mono = np.mean(indata, axis=1) if indata.ndim == 2 else indata
        mono = mono * args.input_gain
        converted = converter.process_block(mono) * args.output_gain
        if not args.no_clip:
            converted = np.clip(converted, -1.0, 1.0)
        if outdata.shape[1] == 1:
            outdata[:, 0] = converted
        else:
            outdata[:] = converted[:, None]

    logger.info(
        "Input %s, output %s. Press Ctrl+C to stop. Block size is %d samples.",
        _device_label(sd, input_device, "input"),
        _device_label(sd, output_device, "output"),
        converter.block_frame,
    )
    with sd.Stream(
        device=(input_device, output_device),
        samplerate=converter.sample_rate,
        blocksize=converter.block_frame,
        channels=(args.input_channels, args.output_channels),
        dtype="float32",
        latency=_parse_latency(args.latency),
        extra_settings=extra_settings,
        callback=callback,
    ):
        _announce_ready()
        try:
            while True:
                sd.sleep(1000)
        except KeyboardInterrupt:
            logger.info("Stopped")


# The desktop app sets OVERTONE_EVENTS=1 and watches stdout for this exact line,
# which means audio is flowing. desktop/main/python.js holds the same string.
READY_LINE = "@overtone ready"


def _announce_ready():
    """Tell the desktop app that the stream is open. Silent for terminal users."""
    if os.environ.get("OVERTONE_EVENTS") == "1":
        print(READY_LINE, flush=True)


ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _missing_base_models(f0_method):
    """Name the first missing base model and how to download it, or return None.

    hubert.py and rtrvc.py load from the same paths, but importing them pulls
    in torch, so the check is repeated here to fail in a second, not after
    the imports. desktop/repo.js makes the same check for the app.
    """
    hubert = ASSETS / "hubert_base"
    has_weights = any((hubert / name).is_file() for name in ("pytorch_model.bin", "model.safetensors"))
    if not (hubert / "config.json").is_file() or not has_weights:
        return (
            f"HuBERT model missing from {hubert}. Download it with: "
            'hf download lj1995/VoiceConversionWebUI --revision main --include "hubert_base/*" --local-dir assets'
        )
    rmvpe = ASSETS / "rmvpe" / "rmvpe.pt"
    if f0_method == "rmvpe" and not rmvpe.is_file():
        return (
            f"RMVPE model missing: {rmvpe}. Download it with: "
            "hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main --local-dir assets/rmvpe, "
            "or pass --f0 fcpe or --f0 pm."
        )
    return None


def _import_sounddevice():
    """Import PortAudio. The live path is the only caller, so file mode stays light."""
    import sounddevice as sd

    return sd


def _host_api_name(sd, device):
    """Return the PortAudio host name for one device entry."""
    return sd.query_hostapis(device["hostapi"])["name"]


def _device_matches(sd, index, device, kind, host_api):
    """Return whether this device can be used as an input or an output."""
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    if device[channel_key] < 1:
        return False
    if host_api and host_api.lower() not in _host_api_name(sd, device).lower():
        return False
    return True


def _resolve_device(spec, kind, host_api=None):
    """Return a PortAudio device index, or None to keep the system default.

    spec may be a device number from --list-devices or part of the device name.
    """
    if spec is None or spec == "":
        return None
    sd = _import_sounddevice()
    devices = sd.query_devices()
    try:
        index = int(spec)
    except ValueError:
        index = None
    if index is not None:
        if index < 0 or index >= len(devices):
            raise SystemExit(f"{kind} device {index} is outside 0..{len(devices) - 1}")
        device = devices[index]
        if not _device_matches(sd, index, device, kind, host_api):
            raise SystemExit(
                f"Device {index} ({device['name']}) is not a matching {kind} device"
            )
        return index
    needle = str(spec).lower()
    matches = [
        i
        for i, device in enumerate(devices)
        if needle in device["name"].lower() and _device_matches(sd, i, device, kind, host_api)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"No {kind} device matches {spec!r}. Run --list-devices.")
    names = ", ".join(f"{i}: {devices[i]['name']}" for i in matches)
    raise SystemExit(f"Several {kind} devices match {spec!r}: {names}")


def _device_label(sd, index, kind):
    """Describe the device that will actually be opened."""
    if index is None:
        index = sd.default.device[0 if kind == "input" else 1]
    device = sd.query_devices(index)
    return f"{index}: {device['name']} ({_host_api_name(sd, device)})"


def _parse_latency(value):
    """Accept low, high, or a number of seconds.

    An unset latency arrives as an empty string, because that is what the
    shared option spec declares as the default. It means the same thing as
    None here: let PortAudio choose. _resolve_device treats "" the same way.
    """
    if value is None or value == "":
        return None
    if value.lower() in {"low", "high"}:
        return value.lower()
    try:
        return float(value)
    except ValueError:
        raise SystemExit("--latency must be low, high, or a number of seconds")


def _wasapi_settings(sd, args, input_device, output_device):
    """Build WASAPI settings only when the user asked for them."""
    if not args.wasapi_exclusive and not args.wasapi_auto_convert:
        return None

    def is_wasapi(index, kind):
        if index is None:
            index = sd.default.device[0 if kind == "input" else 1]
        return "WASAPI" in _host_api_name(sd, sd.query_devices(index)).upper()

    if not (is_wasapi(input_device, "input") and is_wasapi(output_device, "output")):
        raise SystemExit("--wasapi-exclusive and --wasapi-auto-convert require WASAPI devices")
    return sd.WasapiSettings(
        exclusive=args.wasapi_exclusive,
        auto_convert=args.wasapi_auto_convert,
    )


def _device_rows(sd):
    """Return every PortAudio device as a plain dict, with its default marks."""
    default_input, default_output = sd.default.device
    rows = []
    for index, device in enumerate(sd.query_devices()):
        marks = []
        if index == default_input:
            marks.append("default input")
        if index == default_output:
            marks.append("default output")
        rows.append(
            {
                "index": index,
                "inputs": int(device["max_input_channels"]),
                "outputs": int(device["max_output_channels"]),
                "rate": float(device["default_samplerate"]),
                "host": _host_api_name(sd, device),
                "name": device["name"],
                "note": ", ".join(marks),
            }
        )
    return rows


def _list_devices(as_json=False):
    """Print the input and output devices PortAudio can see, as a table or JSON."""
    sd = _import_sounddevice()
    if as_json:
        print(json.dumps(_device_rows(sd)))
        return
    default_input, default_output = sd.default.device
    print(f"{'idx':>4}  {'in':>3}  {'out':>3}  {'rate':>8}  {'host':<18}  name")
    for index, device in enumerate(sd.query_devices()):
        marks = []
        if index == default_input:
            marks.append("default input")
        if index == default_output:
            marks.append("default output")
        suffix = f"  ({', '.join(marks)})" if marks else ""
        print(
            f"{index:4d}  {device['max_input_channels']:3d}  "
            f"{device['max_output_channels']:3d}  {device['default_samplerate']:8.0f}  "
            f"{_host_api_name(sd, device):<18}  {device['name']}{suffix}"
        )


def _add_spec_arguments(parser):
    """Add one argparse argument per option described in the shared spec."""
    for spec in OPT_SPEC.values():
        kind = spec["kind"]
        if kind == "bool":
            parser.add_argument(spec["flag"], action="store_true", default=spec["default"], help=spec["cliHelp"])
        elif kind == "enum":
            parser.add_argument(spec["flag"], choices=tuple(spec["choices"]), default=spec["default"], help=spec["cliHelp"])
        elif kind == "number":
            parser.add_argument(spec["flag"], type=int if spec.get("integer") else float, default=spec["default"], help=spec["cliHelp"])
        else:
            parser.add_argument(spec["flag"], default=spec["default"], help=spec["cliHelp"])


def main(argv=None):
    """Parse the real-time CLI and run file mode, live mode, or device listing."""
    parser = argparse.ArgumentParser(description="Real-time RVC voice conversion")
    parser.add_argument("--input", help="Input wav/flac/ogg file")
    parser.add_argument("--output", help="Output wav path for file mode")
    parser.add_argument("--live", action="store_true", help="Convert the microphone live")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--json", action="store_true", help="With --list-devices, print JSON instead of a table")
    parser.add_argument(
        "--subtype",
        default="FLOAT",
        choices=("FLOAT", "PCM_16", "PCM_24", "PCM_32"),
        help="Wav sample format for file mode",
    )
    _add_spec_arguments(parser)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.list_devices:
        _list_devices(as_json=args.json)
        return
    if not args.model:
        parser.error("--model is required")
    if not Path(args.model).is_file():
        parser.error(f"Model not found: {args.model}")
    if args.index and not Path(args.index).is_file():
        parser.error(f"Index not found: {args.index}")
    if args.f0_min <= 0 or args.f0_max <= args.f0_min:
        parser.error("--f0-min must be positive and lower than --f0-max")
    if args.input_channels < 1 or args.output_channels < 1:
        parser.error("Channel counts must be at least 1")
    if args.index_neighbors < 1:
        parser.error("--index-neighbors must be at least 1")
    missing = _missing_base_models(args.f0)
    if missing:
        parser.error(missing)
    if args.live:
        _run_live(args)
        return
    if not args.input or not args.output:
        parser.error("File mode requires --input and --output. Use --live for the microphone.")
    if not Path(args.input).is_file():
        parser.error(f"Input not found: {args.input}")
    _convert_file(args)


if __name__ == "__main__":
    main()
