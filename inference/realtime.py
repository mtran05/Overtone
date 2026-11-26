"""Run real-time voice conversion from a file or the microphone.

File mode writes a converted wav using the same block, overlap, and SOLA
crossfade path as live playback:

    python -m inference.realtime --model assets/weights/kikiV1.pth --index assets/indices/kikiV1.index --input voice.wav --output converted.wav

Live mode plays the microphone through the default speakers:

    python -m inference.realtime --model assets/weights/kikiV1.pth --index assets/indices/kikiV1.index --live

The desktop app does not run this module for live audio. It keeps one
`python -m inference.worker` process alive instead, which shares the parser,
the checks, and the model-building helpers defined here.
"""

import argparse
import logging
import sys
import time
import warnings
from pathlib import Path

import numpy as np

# Only light imports at module level: --list-devices must not pull in torch.
# The converter and soundfile are imported where they are used.
from inference.live import LiveStream, list_devices, resolve_stream
from inference.opts import OPT_SPEC, PitchSettings


logger = logging.getLogger(__name__)

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def setup_logging():
    """Log to stderr, without the harmless start-up noise that reads like a crash.

    faiss tries each CPU-specific build in turn and logs every miss as a
    ModuleNotFoundError at INFO level, and torch warns that the weight_norm
    used by the upstream synthesizer in module/ is deprecated. Neither is a
    problem, and in the desktop app's log both look like errors.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("faiss.loader").setLevel(logging.WARNING)
    warnings.filterwarnings("ignore", message="`torch.nn.utils.weight_norm` is deprecated", category=FutureWarning)


def pitch_settings(args):
    """The pitch bounds, thresholds, and index neighbour count from parsed options."""
    return PitchSettings(
        f0_min=args.f0_min,
        f0_max=args.f0_max,
        rmvpe_threshold=args.rmvpe_threshold,
        fcpe_threshold=args.fcpe_threshold,
        index_neighbors=args.index_neighbors,
    )


def build_rvc(args, last_rvc=None):
    """Load the voice model named in args, reusing HuBERT and pitch models from last_rvc."""
    # Loads torch, HuBERT, and the voice model, so it is the slow part of startup.
    from inference.converter import load_rvc

    return load_rvc(
        args.model,
        args.index,
        args.index_rate,
        args.key,
        args.formant,
        pitch_settings(args),
        last_rvc=last_rvc,
    )


def build_converter(args, rvc):
    """Wrap a loaded model in the block buffers that args describe."""
    from inference.converter import RealtimeConverter

    return RealtimeConverter(
        rvc,
        f0_method=args.f0,
        sample_rate=args.sample_rate,
        block_time=args.block_time,
        crossfade_time=args.crossfade_time,
        extra_time=args.extra_time,
        rms_mix_rate=args.rms_mix_rate,
    )


def _load_audio(path):
    """Read a file as mono float32 and return it with its sample rate."""
    import soundfile as sf

    audio, sample_rate = sf.read(path, always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    return audio, sample_rate


def _convert_file(args):
    """Convert --input and write --output."""
    import soundfile as sf

    converter = build_converter(args, build_rvc(args))
    audio, sample_rate = _load_audio(args.input)
    if args.input_gain != 1.0:
        audio = audio * args.input_gain
    converted = converter.convert(audio, sample_rate) * args.output_gain
    if not args.no_clip:
        converted = np.clip(converted, -1.0, 1.0)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, converted, converter.sample_rate, subtype=args.subtype)
    logger.info("Wrote %s (%d samples at %d Hz)", output, len(converted), converter.sample_rate)


def _run_live(args):
    """Convert the chosen microphone and play it on the chosen speakers until Ctrl+C."""
    # Resolve the devices before loading the model, so a bad device fails at once.
    config = resolve_stream(args)
    converter = build_converter(args, build_rvc(args))
    # Load the pitch model and record the GPU graphs now. Otherwise the first
    # live blocks do that work inside the audio callback and drop out.
    converter.warm_up()
    stream = LiveStream(converter, config, args, safety_blocks=args.safety_blocks)
    stream.start()
    logger.info("Live. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopped")
    finally:
        stream.close()


def missing_base_models(f0_method):
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


def switchable_trackers():
    """The GPU pitch trackers the desktop worker warms up ahead of time.

    Warming them all during the background preload lets the app switch tracker
    while live without a gap. RMVPE needs its downloaded weights; FCPE ships
    inside torchfcpe. Parselmouth (pm) needs no warm-up.
    """
    trackers = ["fcpe"]
    if (ASSETS / "rmvpe" / "rmvpe.pt").is_file():
        trackers.insert(0, "rmvpe")
    return tuple(trackers)


def check_args(args):
    """Return why these options cannot be used for a conversion, or None when they can."""
    if not args.model:
        return "--model is required"
    if not Path(args.model).is_file():
        return f"Model not found: {args.model}"
    if args.index and not Path(args.index).is_file():
        return f"Index not found: {args.index}"
    if args.f0_min <= 0 or args.f0_max <= args.f0_min:
        return "--f0-min must be positive and lower than --f0-max"
    if args.input_channels < 1 or args.output_channels < 1:
        return "Channel counts must be at least 1"
    if args.index_neighbors < 1:
        return "--index-neighbors must be at least 1"
    return missing_base_models(args.f0)


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


def build_parser(parser_class=argparse.ArgumentParser):
    """The full CLI parser. The worker passes a class whose error() raises instead of exiting."""
    parser = parser_class(description="Real-time RVC voice conversion")
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
    return parser


def main(argv=None):
    """Parse the real-time CLI and run file mode, live mode, or device listing."""
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging()
    if args.list_devices:
        list_devices(as_json=args.json)
        return
    problem = check_args(args)
    if problem:
        parser.error(problem)
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
