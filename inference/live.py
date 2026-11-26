"""Audio devices and the live microphone-to-speaker stream.

Both live paths use this module: `python -m inference.realtime --live` for
terminal users, and `python -m inference.worker` for the desktop app. It
imports no torch, so listing devices stays fast; sounddevice is imported only
when a device is actually touched.
"""

import json
import logging
from dataclasses import dataclass

import numpy as np


logger = logging.getLogger(__name__)


def import_sounddevice():
    """Import PortAudio. Only the live path and device listing need it, so file mode stays light."""
    import sounddevice as sd

    return sd


def host_api_name(sd, device):
    """Return the PortAudio host name for one device entry."""
    return sd.query_hostapis(device["hostapi"])["name"]


def device_matches(sd, device, kind, host_api):
    """Return whether this device can be used as an input or an output."""
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    if device[channel_key] < 1:
        return False
    if host_api and host_api.lower() not in host_api_name(sd, device).lower():
        return False
    return True


def resolve_device(spec, kind, host_api=None):
    """Return a PortAudio device index, or None to keep the system default.

    spec may be a device number from --list-devices or part of the device name.
    """
    if spec is None or spec == "":
        return None
    sd = import_sounddevice()
    devices = sd.query_devices()
    try:
        index = int(spec)
    except ValueError:
        index = None
    if index is not None:
        if index < 0 or index >= len(devices):
            raise SystemExit(f"{kind} device {index} is outside 0..{len(devices) - 1}")
        device = devices[index]
        if not device_matches(sd, device, kind, host_api):
            raise SystemExit(f"Device {index} ({device['name']}) is not a matching {kind} device")
        return index
    needle = str(spec).lower()
    matches = [
        i
        for i, device in enumerate(devices)
        if needle in device["name"].lower() and device_matches(sd, device, kind, host_api)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"No {kind} device matches {spec!r}. Run --list-devices.")
    names = ", ".join(f"{i}: {devices[i]['name']}" for i in matches)
    raise SystemExit(f"Several {kind} devices match {spec!r}: {names}")


def device_label(sd, index, kind):
    """Describe the device that will actually be opened."""
    if index is None:
        index = sd.default.device[0 if kind == "input" else 1]
    device = sd.query_devices(index)
    return f"{index}: {device['name']} ({host_api_name(sd, device)})"


def parse_latency(value):
    """Accept low, high, or a number of seconds.

    An unset latency arrives as an empty string, because that is what the
    shared option spec declares as the default. It means the same thing as
    None here: let PortAudio choose. resolve_device treats "" the same way.
    """
    if value is None or value == "":
        return None
    if value.lower() in {"low", "high"}:
        return value.lower()
    try:
        return float(value)
    except ValueError:
        raise SystemExit("--latency must be low, high, or a number of seconds")


def wasapi_settings(sd, args, input_device, output_device):
    """Build WASAPI settings only when the user asked for them."""
    if not args.wasapi_exclusive and not args.wasapi_auto_convert:
        return None

    def is_wasapi(index, kind):
        if index is None:
            index = sd.default.device[0 if kind == "input" else 1]
        return "WASAPI" in host_api_name(sd, sd.query_devices(index)).upper()

    if not (is_wasapi(input_device, "input") and is_wasapi(output_device, "output")):
        raise SystemExit("--wasapi-exclusive and --wasapi-auto-convert require WASAPI devices")
    return sd.WasapiSettings(
        exclusive=args.wasapi_exclusive,
        auto_convert=args.wasapi_auto_convert,
    )


def device_rows(sd):
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
                "host": host_api_name(sd, device),
                "name": device["name"],
                "note": ", ".join(marks),
            }
        )
    return rows


def list_devices(as_json=False):
    """Print the input and output devices PortAudio can see, as a table or JSON."""
    sd = import_sounddevice()
    rows = device_rows(sd)
    if as_json:
        print(json.dumps(rows))
        return
    print(f"{'idx':>4}  {'in':>3}  {'out':>3}  {'rate':>8}  {'host':<18}  name")
    for row in rows:
        suffix = f"  ({row['note']})" if row["note"] else ""
        print(
            f"{row['index']:4d}  {row['inputs']:3d}  {row['outputs']:3d}  {row['rate']:8.0f}  "
            f"{row['host']:<18}  {row['name']}{suffix}"
        )


@dataclass(frozen=True)
class StreamConfig:
    """Which devices to open and how. Resolved before the model loads, so a bad device fails at once."""

    input_device: object
    output_device: object
    input_channels: int
    output_channels: int
    latency: object
    extra_settings: object


def resolve_stream(args):
    """Turn the device options into a StreamConfig, or raise SystemExit with the reason."""
    sd = import_sounddevice()
    input_device = resolve_device(args.input_device, "input", args.host_api)
    output_device = resolve_device(args.output_device, "output", args.host_api)
    extra_settings = wasapi_settings(sd, args, input_device, output_device)
    input_info = sd.query_devices(input_device if input_device is not None else sd.default.device[0])
    if args.input_channels > input_info["max_input_channels"]:
        raise SystemExit(f"Input device has {input_info['max_input_channels']} channels, not {args.input_channels}")
    output_info = sd.query_devices(output_device if output_device is not None else sd.default.device[1])
    if args.output_channels > output_info["max_output_channels"]:
        raise SystemExit(f"Output device has {output_info['max_output_channels']} channels, not {args.output_channels}")
    return StreamConfig(
        input_device=input_device,
        output_device=output_device,
        input_channels=args.input_channels,
        output_channels=args.output_channels,
        latency=parse_latency(args.latency),
        extra_settings=extra_settings,
    )


class LiveStream:
    """Run one converter between a microphone and speakers.

    `levels` is anything with input_gain, output_gain, and no_clip, such as the
    parsed options. It is read on every block, so the worker can swap in new
    options while the stream runs and the next block uses them.
    """

    def __init__(self, converter, config, levels, on_error=None):
        """Remember what to open. Nothing touches the audio devices until start()."""
        self.converter = converter
        self.config = config
        self.levels = levels
        self.on_error = on_error
        self._stream = None

    def start(self):
        """Open the devices and begin converting."""
        sd = import_sounddevice()
        converter = self.converter

        def callback(indata, outdata, frames, time_info, status):
            """Convert one microphone block and copy it into the speaker buffer."""
            if status:
                logger.warning("Audio stream: %s", status)
            try:
                levels = self.levels
                mono = np.mean(indata, axis=1) if indata.ndim == 2 else indata
                mono = mono * levels.input_gain
                converted = converter.process_block(mono) * levels.output_gain
                if not levels.no_clip:
                    converted = np.clip(converted, -1.0, 1.0)
                if outdata.shape[1] == 1:
                    outdata[:, 0] = converted
                else:
                    outdata[:] = converted[:, None]
            except Exception as error:
                # An exception would otherwise end the stream with nothing but a
                # traceback. Report it, then stop cleanly.
                logger.exception("Live conversion failed")
                outdata.fill(0)
                if self.on_error is not None:
                    self.on_error(error)
                raise sd.CallbackAbort from error

        logger.info(
            "Input %s, output %s. Block size is %d samples.",
            device_label(sd, self.config.input_device, "input"),
            device_label(sd, self.config.output_device, "output"),
            converter.block_frame,
        )
        self._stream = sd.Stream(
            device=(self.config.input_device, self.config.output_device),
            samplerate=converter.sample_rate,
            blocksize=converter.block_frame,
            channels=(self.config.input_channels, self.config.output_channels),
            dtype="float32",
            latency=self.config.latency,
            extra_settings=self.config.extra_settings,
            callback=callback,
        )
        self._stream.start()

    def close(self):
        """Stop and release the devices. Safe to call twice."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()
