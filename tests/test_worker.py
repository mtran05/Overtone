"""The desktop worker's decisions, with the model, converter, and stream faked.

Nothing here touches a GPU or an audio device: build_rvc, build_converter,
resolve_stream, and LiveStream are replaced, so the tests check only what the
worker decides to do for each command and which states it reports.
"""

import io
import queue

import pytest

import inference.worker as worker_module
from inference.worker import Worker, _read_commands, _superseded, changed_costs, run


class FakeRVC:
    def __init__(self, args, last_rvc):
        self.model = args.model
        self.last_rvc = last_rvc
        self.calls = []

    def change_key(self, key):
        self.calls.append(("key", key))

    def change_formant(self, formant):
        self.calls.append(("formant", formant))

    def update_settings(self, settings):
        self.calls.append(("settings", settings))

    def change_index(self, path, rate):
        self.calls.append(("index", path, rate))


class FakeConverter:
    def __init__(self, args, rvc):
        self.rvc = rvc
        self.block_time = args.block_time
        self.f0_method = args.f0
        self.rms_mix_rate = args.rms_mix_rate
        self.warmed = 0
        self.warmed_also = ()
        self.ready_methods = set()
        self.cold = set()

    def warm_up(self, also=()):
        self.warmed += 1
        self.warmed_also = also
        self.ready_methods = {self.f0_method, "pm", *(m for m in also if m not in self.cold)}


class FakeStream:
    opened = []

    def __init__(self, converter, config, levels, on_error=None, safety_blocks=0):
        self.converter = converter
        self.levels = levels
        self.on_error = on_error
        self.safety_blocks = safety_blocks
        self.closed = False
        FakeStream.opened.append(self)

    def start(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def setup(monkeypatch):
    FakeStream.opened = []
    built = {"rvc": [], "converter": []}

    def build_rvc(args, last_rvc=None):
        rvc = FakeRVC(args, last_rvc)
        built["rvc"].append(rvc)
        return rvc

    def build_converter(args, rvc):
        converter = FakeConverter(args, rvc)
        built["converter"].append(converter)
        return converter

    monkeypatch.setattr(worker_module, "build_rvc", build_rvc)
    monkeypatch.setattr(worker_module, "build_converter", build_converter)
    monkeypatch.setattr(worker_module, "resolve_stream", lambda args: "stream-config")
    monkeypatch.setattr(worker_module, "LiveStream", FakeStream)
    monkeypatch.setattr(worker_module, "check_args", lambda args: None)
    monkeypatch.setattr(worker_module, "switchable_trackers", lambda: ("rmvpe", "fcpe"))

    events = []
    commands = queue.Queue()
    worker = Worker(events.append, commands)
    return worker, events, built, commands


def states(events):
    return [event["state"] for event in events if event["event"] == "state"]


BASE = ["--model", "voice.pth", "--f0", "rmvpe"]


def test_configure_while_idle_preloads_and_reports_ready(setup):
    worker, events, built, _ = setup
    worker.configure(BASE)
    assert states(events) == ["loading", "ready"]
    assert len(built["rvc"]) == 1
    assert built["converter"][0].warmed == 1
    assert FakeStream.opened == []


def test_start_on_a_warm_model_only_opens_the_stream(setup):
    worker, events, built, _ = setup
    worker.configure(BASE)
    events.clear()
    worker.start(BASE)
    assert states(events) == ["starting", "live"]
    assert len(built["rvc"]) == 1 and len(built["converter"]) == 1
    assert len(FakeStream.opened) == 1


def test_start_from_cold_loads_then_goes_live_without_a_ready_in_between(setup):
    worker, events, _, _ = setup
    worker.start(BASE)
    assert states(events) == ["starting", "live"]


def test_a_live_option_changes_in_place(setup):
    worker, events, built, _ = setup
    worker.start(BASE)
    events.clear()
    worker.configure(BASE + ["--key", "7", "--formant", "1.5"])
    assert events == []
    rvc = built["rvc"][0]
    assert ("key", 7) in rvc.calls and ("formant", 1.5) in rvc.calls
    assert len(FakeStream.opened) == 1 and not FakeStream.opened[0].closed


def test_gains_reach_the_running_stream(setup):
    worker, _, _, _ = setup
    worker.start(BASE)
    worker.configure(BASE + ["--output-gain", "0.5"])
    assert FakeStream.opened[0].levels.output_gain == 0.5


def test_a_converter_option_rebuilds_the_converter_but_keeps_the_model(setup):
    worker, events, built, _ = setup
    worker.start(BASE)
    events.clear()
    worker.configure(BASE + ["--block-time", "0.3"])
    assert states(events) == ["starting", "live"]
    assert len(built["rvc"]) == 1
    assert len(built["converter"]) == 2 and built["converter"][1].warmed == 1
    assert FakeStream.opened[0].closed and not FakeStream.opened[1].closed


def test_a_device_option_reopens_only_the_stream(setup):
    worker, events, built, _ = setup
    worker.start(BASE)
    events.clear()
    worker.configure(BASE + ["--latency", "low"])
    assert states(events) == ["starting", "live"]
    assert len(built["converter"]) == 1
    assert len(FakeStream.opened) == 2


def test_a_new_model_reuses_the_previous_one(setup):
    worker, _, built, _ = setup
    worker.start(BASE)
    worker.configure(["--model", "other.pth", "--f0", "rmvpe"])
    assert len(built["rvc"]) == 2
    assert built["rvc"][1].last_rvc is built["rvc"][0]


def test_an_unchanged_configure_does_nothing(setup):
    worker, events, built, _ = setup
    worker.configure(BASE)
    events.clear()
    worker.configure(BASE)
    assert events == []
    assert len(built["converter"]) == 1


def test_bad_options_raise_before_anything_changes(setup):
    worker, _, built, _ = setup
    with pytest.raises(ValueError):
        worker.configure(["--model", "voice.pth", "--f0", "nope"])
    assert built["rvc"] == []


def test_stop_keeps_the_model_and_reports_ready_once(setup):
    worker, events, built, _ = setup
    worker.start(BASE)
    events.clear()
    worker.stop()
    worker.stop()
    assert states(events) == ["ready"]
    assert FakeStream.opened[0].closed
    worker.start(BASE)
    assert len(built["rvc"]) == 1


def test_stop_pressed_during_loading_cancels_the_stream(setup):
    worker, events, _, commands = setup
    commands.put({"cmd": "stop"})
    worker.start(BASE)
    assert FakeStream.opened == []
    assert states(events) == ["starting", "ready"]


def test_a_failed_command_reports_the_error_and_settles(setup):
    worker, events, _, _ = setup
    worker.configure(BASE)
    events.clear()
    worker.fail("Model not found: x.pth")
    assert events == [{"event": "error", "message": "Model not found: x.pth"}]


def test_a_stream_error_is_reported_then_cleaned_up_on_the_main_thread(setup):
    worker, events, _, commands = setup
    worker.start(BASE)
    events.clear()
    FakeStream.opened[0].on_error(RuntimeError("device unplugged"))
    assert events[0] == {"event": "error", "message": "Live conversion stopped: device unplugged"}
    assert commands.get_nowait() == {"cmd": "_stream_failed"}
    worker.stream_failed()
    assert states(events) == ["ready"]
    assert FakeStream.opened[0].closed


def test_changed_costs_maps_options_to_their_apply_field(setup):
    worker, _, _, _ = setup
    old = worker.parser.parse_args(BASE)
    assert changed_costs(None, old) == {"model"}
    assert changed_costs(old, worker.parser.parse_args(BASE + ["--key", "3"])) == {"live"}
    assert changed_costs(old, worker.parser.parse_args(BASE + ["--input-device", "2"])) == {"stream"}
    assert changed_costs(old, worker.parser.parse_args(BASE + ["--extra-time", "1"])) == {"converter"}
    assert changed_costs(old, old) == set()


def test_superseded_skips_a_configure_that_a_later_one_replaces():
    batch = [{"cmd": "configure"}, {"cmd": "stop"}, {"cmd": "configure"}, {"cmd": "start"}]
    assert _superseded(batch, 0)
    assert _superseded(batch, 2)
    assert not _superseded([{"cmd": "configure"}, {"cmd": "stop"}], 0)


def test_run_applies_only_the_newest_queued_configure(setup):
    worker, _, built, commands = setup
    for key in ("1", "2", "3"):
        commands.put({"cmd": "configure", "argv": BASE + ["--key", key]})
    commands.put({"cmd": "shutdown"})
    run(worker, commands)
    assert len(built["rvc"]) == 1
    assert worker.args.key == 3


def test_run_turns_exceptions_into_error_events(setup):
    worker, events, _, commands = setup
    commands.put({"cmd": "configure", "argv": ["--f0", "nope"]})
    commands.put({"cmd": "dance"})
    commands.put({"cmd": "shutdown"})
    run(worker, commands)
    errors = [event["message"] for event in events if event["event"] == "error"]
    assert len(errors) == 2
    assert "invalid choice" in errors[0]
    assert "Unknown command" in errors[1]


def test_read_commands_skips_bad_lines_and_shuts_down_at_end_of_input():
    commands = queue.Queue()
    _read_commands(io.StringIO('{"cmd": "stop"}\n\nnot json\n{"cmd": "start", "argv": []}\n'), commands)
    assert [commands.get_nowait() for _ in range(3)] == [{"cmd": "stop"}, {"cmd": "start", "argv": []}, {"cmd": "shutdown"}]


def test_preloading_warms_every_tracker_so_a_live_switch_is_seamless(setup):
    worker, events, built, _ = setup
    worker.start(BASE)
    assert built["converter"][0].warmed_also == ("rmvpe", "fcpe")
    events.clear()
    worker.configure(["--model", "voice.pth", "--f0", "fcpe"])
    assert events == []
    assert built["converter"][0].f0_method == "fcpe"
    assert len(built["converter"]) == 1 and len(FakeStream.opened) == 1


def test_a_tracker_that_failed_to_warm_up_falls_back_to_a_restart(setup, monkeypatch):
    worker, events, built, _ = setup
    original = FakeConverter.__init__

    def cold_fcpe(self, args, rvc):
        original(self, args, rvc)
        self.cold = {"fcpe"}

    monkeypatch.setattr(FakeConverter, "__init__", cold_fcpe)
    worker.start(BASE)
    events.clear()
    worker.configure(["--model", "voice.pth", "--f0", "fcpe"])
    assert states(events) == ["starting", "live"]
    assert len(built["converter"]) == 2


def test_pm_never_needs_a_restart(setup):
    worker, events, _, _ = setup
    worker.start(BASE)
    events.clear()
    worker.configure(["--model", "voice.pth", "--f0", "pm"])
    assert events == []


def test_the_safety_buffer_reaches_the_stream_and_reopens_it(setup):
    worker, events, _, _ = setup
    worker.start(BASE)
    events.clear()
    worker.configure(BASE + ["--safety-blocks", "2"])
    assert states(events) == ["starting", "live"]
    assert FakeStream.opened[-1].safety_blocks == 2
