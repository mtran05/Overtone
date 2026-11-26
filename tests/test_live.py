"""Device matching, stream setup, and the live callback, against a fake sounddevice."""

import json

import numpy as np
import pytest

import inference.live as live


class CallbackAbort(Exception):
    pass


class FakeSD:
    """Just enough of sounddevice: a device table, host APIs, defaults, and Stream."""

    CallbackAbort = CallbackAbort

    def __init__(self):
        self.devices = [
            {"name": "Microphone (Realtek)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 48000},
            {"name": "Speakers (Realtek)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
            {"name": "Microphone (Realtek)", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 44100},
            {"name": "CABLE Input", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 8, "default_samplerate": 44100},
        ]
        self.hostapis = [{"name": "MME"}, {"name": "Windows WASAPI"}]
        self.default = type("Default", (), {"device": [0, 1]})()
        self.refreshes = 0
        self.streams = []

    def query_devices(self, index=None):
        return self.devices if index is None else self.devices[index]

    def query_hostapis(self, index):
        return self.hostapis[index]

    def _terminate(self):
        self.refreshes += 1

    def _initialize(self):
        pass

    def WasapiSettings(self, exclusive, auto_convert):
        return ("wasapi", exclusive, auto_convert)

    def Stream(self, **kwargs):
        stream = FakeStream(kwargs)
        self.streams.append(stream)
        return stream


class FakeStream:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = self.aborted = self.closed = False

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSD()
    monkeypatch.setattr(live, "import_sounddevice", lambda: fake)
    return fake


class Args:
    """Parsed options with the device defaults from the spec."""

    def __init__(self, **overrides):
        self.input_device = ""
        self.output_device = ""
        self.host_api = ""
        self.input_channels = 1
        self.output_channels = 2
        self.latency = ""
        self.wasapi_exclusive = False
        self.wasapi_auto_convert = False
        self.input_gain = 1.0
        self.output_gain = 1.0
        self.no_clip = False
        self.__dict__.update(overrides)


def test_parse_latency():
    assert live.parse_latency("") is None
    assert live.parse_latency(None) is None
    assert live.parse_latency("LOW") == "low"
    assert live.parse_latency("0.02") == 0.02
    with pytest.raises(SystemExit, match="--latency"):
        live.parse_latency("fast")


def test_resolve_device_by_index_and_by_unique_name(sd):
    assert live.resolve_device("", "input") is None
    assert live.resolve_device("1", "output") == 1
    assert live.resolve_device("cable", "output") == 3


def test_resolve_device_rejects_wrong_direction_and_out_of_range(sd):
    with pytest.raises(SystemExit, match="not a matching input"):
        live.resolve_device("1", "input")
    with pytest.raises(SystemExit, match="outside 0..3"):
        live.resolve_device("9", "input")
    with pytest.raises(SystemExit, match="No output device"):
        live.resolve_device("headphones", "output")


def test_a_name_on_two_host_apis_needs_the_host_api_filter(sd):
    with pytest.raises(SystemExit, match="Several input devices"):
        live.resolve_device("microphone", "input")
    assert live.resolve_device("microphone", "input", host_api="wasapi") == 2


def test_device_rows_marks_the_defaults(sd):
    rows = live.device_rows(sd)
    assert rows[0]["note"] == "default input"
    assert rows[1]["note"] == "default output"
    assert rows[2] == {"index": 2, "inputs": 1, "outputs": 0, "rate": 44100.0, "host": "Windows WASAPI", "name": "Microphone (Realtek)", "note": ""}


def test_list_devices_prints_json_for_the_app(sd, capsys):
    live.list_devices(as_json=True)
    assert [row["name"] for row in json.loads(capsys.readouterr().out)][3] == "CABLE Input"


def test_resolve_stream_refreshes_the_device_list_first(sd):
    config = live.resolve_stream(Args(output_device="cable"))
    assert sd.refreshes == 1
    assert config.output_device == 3 and config.input_device is None


def test_resolve_stream_checks_channel_counts_before_any_model_loads(sd):
    with pytest.raises(SystemExit, match="Input device has 1 channels, not 2"):
        live.resolve_stream(Args(input_device="2", host_api="wasapi", input_channels=2))


def test_wasapi_settings_need_wasapi_devices(sd):
    with pytest.raises(SystemExit, match="require WASAPI"):
        live.resolve_stream(Args(wasapi_exclusive=True))
    config = live.resolve_stream(Args(input_device="2", output_device="3", wasapi_exclusive=True))
    assert config.extra_settings == ("wasapi", True, False)


class HalfConverter:
    """Returns a constant 0.5 block, or raises when told to."""

    block_frame = 4
    sample_rate = 16000

    def __init__(self):
        self.fail = False
        self.seen = []

    def process_block(self, block):
        if self.fail:
            raise RuntimeError("CUDA error")
        self.seen.append(np.array(block))
        return np.full(self.block_frame, 0.5, dtype=np.float32)


def open_stream(sd, levels, on_error=None):
    converter = HalfConverter()
    stream = live.LiveStream(converter, live.resolve_stream(Args()), levels, on_error=on_error)
    stream.start()
    return stream, converter, sd.streams[-1]


def test_the_callback_mixes_to_mono_applies_gains_and_fills_every_channel(sd):
    stream, converter, fake = open_stream(sd, Args(input_gain=2.0, output_gain=3.0))
    outdata = np.zeros((4, 2), dtype=np.float32)
    fake.callback(np.array([[0.1, 0.3]] * 4, dtype=np.float32), outdata, 4, None, None)
    np.testing.assert_allclose(converter.seen[0], [0.4] * 4, rtol=1e-6)
    # 0.5 * 3.0 = 1.5 is clipped to 1.0 on both channels.
    np.testing.assert_allclose(outdata, np.ones((4, 2)))


def test_new_levels_apply_to_the_next_block(sd):
    stream, _, fake = open_stream(sd, Args())
    stream.levels = Args(output_gain=4.0, no_clip=True)
    outdata = np.zeros((4, 1), dtype=np.float32)
    fake.callback(np.zeros((4, 1), dtype=np.float32), outdata, 4, None, None)
    np.testing.assert_allclose(outdata[:, 0], [2.0] * 4)


def test_a_callback_error_is_reported_silenced_and_stops_the_stream(sd):
    errors = []
    stream, converter, fake = open_stream(sd, Args(), on_error=errors.append)
    converter.fail = True
    outdata = np.ones((4, 2), dtype=np.float32)
    with pytest.raises(CallbackAbort):
        fake.callback(np.zeros((4, 1), dtype=np.float32), outdata, 4, None, None)
    assert str(errors[0]) == "CUDA error"
    assert not outdata.any()


def test_close_releases_the_device_once(sd):
    stream, _, fake = open_stream(sd, Args())
    stream.close()
    stream.close()
    assert fake.aborted and fake.closed


def run_blocks(fake, n, channels=2):
    """Call the audio callback n times; return what each call wrote."""
    written = []
    for _ in range(n):
        outdata = np.full((4, channels), -1.0, dtype=np.float32)
        fake.callback(np.zeros((4, 1), dtype=np.float32), outdata, 4, None, None)
        written.append(outdata.copy())
    return written


def wait_for(predicate, timeout=2.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_the_open_flag_is_set_only_while_a_stream_is_open(sd):
    assert not live.STREAM_OPEN.is_set()
    stream, _, _ = open_stream(sd, Args())
    assert live.STREAM_OPEN.is_set()
    stream.close()
    assert not live.STREAM_OPEN.is_set()


def test_the_safety_buffer_delays_output_by_that_many_blocks(sd):
    converter = HalfConverter()
    stream = live.LiveStream(converter, live.resolve_stream(Args()), Args(), safety_blocks=2)
    stream.start()
    fake = sd.streams[-1]
    try:
        first = run_blocks(fake, 2)
        # Two blocks of head start play as silence while the thread converts.
        assert all(not block.any() for block in first)
        assert wait_for(lambda: len(converter.seen) == 2)
        np.testing.assert_allclose(run_blocks(fake, 1)[0], 0.5)
    finally:
        stream.close()
    assert not live.STREAM_OPEN.is_set()


def test_a_late_block_plays_silence_instead_of_stopping_the_stream(sd):
    converter = HalfConverter()
    stream = live.LiveStream(converter, live.resolve_stream(Args()), Args(), safety_blocks=1)
    stream.start()
    fake = sd.streams[-1]
    try:
        stream._outputs.get_nowait()  # use up the head start
        assert not run_blocks(fake, 1)[0].any()
        assert stream._behind == 1
    finally:
        stream.close()


def test_a_conversion_error_on_the_buffer_thread_is_reported(sd):
    errors = []
    converter = HalfConverter()
    converter.fail = True
    stream = live.LiveStream(converter, live.resolve_stream(Args()), Args(), on_error=errors.append, safety_blocks=1)
    stream.start()
    try:
        run_blocks(sd.streams[-1], 1)
        assert wait_for(lambda: errors)
        assert str(errors[0]) == "CUDA error"
    finally:
        stream.close()
