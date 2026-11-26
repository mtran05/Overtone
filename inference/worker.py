"""The long-running inference process behind the desktop app.

Electron starts `python -m inference.worker` once and keeps it. Loading torch,
HuBERT, and a voice model takes tens of seconds, so doing it once, ahead of
time, is what makes "Go live" near-instant and lets settings change while live.

Protocol, one JSON object per line:

  stdin   {"cmd": "configure", "argv": [...]}   load or update, stay as live/idle as now
          {"cmd": "start", "argv": [...]}       configure, then open the audio stream
          {"cmd": "stop"}                       close the stream, keep the model loaded
          {"cmd": "shutdown"}                   exit (closing stdin does the same)

  stdout  {"event": "state", "state": "idle" | "loading" | "ready" | "starting" | "live"}
          {"event": "error", "message": "..."}

argv holds the same option flags as `inference.realtime` and is parsed and
checked by the same code. Logs go to stderr; stdout carries only events.

What a change costs comes from each option's "apply" field in
desktop/shared/opts-spec.json: "live" options reach the next block,
"stream" reopens the devices, "converter" rebuilds the block buffers, and
"model" reloads the voice while keeping HuBERT and the pitch models.
"""

import argparse
import json
import logging
import os
import queue
import sys
import threading

from inference.live import LiveStream, resolve_stream
from inference.opts import OPT_SPEC
from inference.realtime import (
    build_converter,
    build_parser,
    build_rvc,
    check_args,
    pitch_settings,
    setup_logging,
    switchable_trackers,
)


logger = logging.getLogger(__name__)

# argparse attribute name -> what changing it costs.
APPLY = {spec["flag"].lstrip("-").replace("-", "_"): spec["apply"] for spec in OPT_SPEC.values()}


class _RaisingParser(argparse.ArgumentParser):
    """Report a bad option as an error event instead of exiting the process."""

    def error(self, message):
        raise ValueError(message)


def changed_costs(old, new):
    """The set of apply costs touched by going from old to new options."""
    if old is None:
        return {"model"}
    return {cost for attr, cost in APPLY.items() if getattr(old, attr) != getattr(new, attr)}


class Worker:
    """Owns the loaded model, its converter, and the open stream, if any."""

    def __init__(self, emit, commands):
        """emit sends one event to Electron; commands is the queue read by run()."""
        self.emit = emit
        self.commands = commands
        self.parser = build_parser(_RaisingParser)
        self.state = "idle"
        self.args = None
        self.rvc = None
        self.converter = None
        self.stream = None

    def set_state(self, state):
        """Report a state change. Repeats are not sent."""
        if state != self.state:
            self.state = state
            self.emit({"event": "state", "state": state})

    def _parse(self, argv):
        """Parse and check argv exactly as the CLI would, raising ValueError on a problem."""
        args = self.parser.parse_args(argv)
        problem = check_args(args)
        if problem:
            raise ValueError(problem)
        return args

    def configure(self, argv):
        """Bring the loaded model in line with argv without starting or stopping audio."""
        self._apply(self._parse(argv))

    def start(self, argv):
        """Configure, then open the stream unless it is already open."""
        args = self._parse(argv)
        if self.stream is None:
            self.set_state("starting")
        self._apply(args)
        if self.stream is None:
            if self._stop_pending():
                # The user pressed Stop while the model was loading.
                self.set_state("ready")
                return
            self._open_stream()

    def stop(self):
        """Close the stream. The model stays loaded so the next start is instant."""
        self._close_stream()
        self.set_state("ready" if self.converter is not None else "idle")

    def shutdown(self):
        """Release the audio devices before the process exits."""
        self._close_stream()

    def fail(self, message):
        """Report a failed command and settle into whatever state is now true."""
        self.emit({"event": "error", "message": message})
        if self.stream is None:
            self.set_state("ready" if self.converter is not None else "idle")

    def stream_failed(self):
        """The audio callback hit an error and stopped. Release the devices."""
        self._close_stream()
        self.set_state("ready" if self.converter is not None else "idle")

    def _apply(self, args):
        """Do the least work that makes the loaded state match args."""
        costs = changed_costs(self.args, args)
        live = self.stream is not None
        need_model = self.rvc is None or "model" in costs
        # A pitch tracker that was not warmed up would load inside the audio
        # path, so switching to one needs the converter rebuilt and warmed.
        cold_tracker = self.converter is not None and args.f0 not in self.converter.ready_methods
        need_converter = need_model or self.converter is None or "converter" in costs or cold_tracker
        reopen = live and (need_converter or "stream" in costs)

        if reopen:
            self._close_stream()
            self.set_state("starting")
        elif need_converter and self.state != "starting":
            self.set_state("loading")

        if need_model:
            rvc = build_rvc(args, last_rvc=self.rvc)
        else:
            rvc = self.rvc
            rvc.change_key(args.key)
            rvc.change_formant(args.formant)
            rvc.update_settings(pitch_settings(args))
            rvc.change_index(args.index, args.index_rate)

        if need_converter:
            converter = build_converter(args, rvc)
            # GPU work here is safe only because no stream is running: recording a
            # CUDA graph fails if another thread uses the GPU at the same moment.
            # The other trackers are warmed too, so a later switch is seamless.
            converter.warm_up(also=switchable_trackers())
        else:
            converter = self.converter
            converter.rms_mix_rate = args.rms_mix_rate
            converter.f0_method = args.f0

        self.rvc, self.converter, self.args = rvc, converter, args
        if reopen:
            self._open_stream()
        elif live:
            # Gains and clipping are read from here on every block.
            self.stream.levels = args
        elif self.state == "loading":
            self.set_state("ready")

    def _open_stream(self):
        """Open the devices for the current converter and report live."""
        stream = LiveStream(
            self.converter,
            resolve_stream(self.args),
            self.args,
            on_error=self._on_stream_error,
            safety_blocks=self.args.safety_blocks,
        )
        stream.start()
        self.stream = stream
        self.set_state("live")

    def _close_stream(self):
        """Close the stream if one is open."""
        stream, self.stream = self.stream, None
        if stream is not None:
            stream.close()

    def _on_stream_error(self, error):
        """Called on the audio thread. Report now; let the main thread clean up."""
        self.emit({"event": "error", "message": f"Live conversion stopped: {error}"})
        self.commands.put({"cmd": "_stream_failed"})

    def _stop_pending(self):
        """Whether a stop command is already waiting in the queue."""
        with self.commands.mutex:
            return any(command.get("cmd") == "stop" for command in self.commands.queue)


def _superseded(batch, position):
    """A configure is pointless when a later configure or start in the same batch replaces it."""
    return any(command.get("cmd") in ("configure", "start") for command in batch[position + 1 :])


def run(worker, commands):
    """Process commands until shutdown, skipping configures that a later one replaces."""
    while True:
        batch = [commands.get()]
        while True:
            try:
                batch.append(commands.get_nowait())
            except queue.Empty:
                break
        for position, command in enumerate(batch):
            name = command.get("cmd")
            if name == "configure" and _superseded(batch, position):
                continue
            if name == "shutdown":
                worker.shutdown()
                return
            try:
                if name == "configure":
                    worker.configure(command.get("argv", []))
                elif name == "start":
                    worker.start(command.get("argv", []))
                elif name == "stop":
                    worker.stop()
                elif name == "_stream_failed":
                    worker.stream_failed()
                else:
                    raise ValueError(f"Unknown command: {name!r}")
            except (ValueError, SystemExit) as error:
                # Bad options or devices: the message is the whole story.
                worker.fail(str(error))
            except Exception as error:
                logger.exception("%s failed", name)
                worker.fail(f"{name} failed: {error}")


def _read_commands(stream, commands):
    """Feed stdin lines into the queue. End of input means Electron is gone, so shut down."""
    for line in stream:
        line = line.strip()
        if not line:
            continue
        try:
            commands.put(json.loads(line))
        except ValueError:
            logger.warning("Ignoring a line that is not JSON: %s", line[:80])
    commands.put({"cmd": "shutdown"})


def _take_command_pipe():
    """Return a private reader for the command pipe and point fd 0 at NUL.

    On Windows, while one thread blocks reading a pipe, other calls that query
    that same handle wait for the read to finish. Imports in torch's stack check
    stdin, so the model load stalled until Electron happened to send another
    line. Reading from a duplicate and leaving fd 0 on NUL keeps those checks
    away from the pipe. dup2 onto fd 0 also updates the process's standard
    input handle, which is what those checks look at.
    """
    if os.name != "nt":
        return sys.stdin
    pipe = os.dup(0)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    sys.stdin = open(os.devnull, encoding="utf-8")
    return open(pipe, encoding="utf-8")


def main():
    """Wire stdin, stdout, and the queue together and run until shutdown."""
    command_pipe = _take_command_pipe()
    events = sys.stdout
    # Libraries sometimes print. Send that to stderr so stdout stays pure events.
    sys.stdout = sys.stderr
    setup_logging()
    lock = threading.Lock()

    def emit(event):
        with lock:
            events.write(json.dumps(event) + "\n")
            events.flush()

    commands = queue.Queue()
    threading.Thread(target=_read_commands, args=(command_pipe, commands), daemon=True).start()
    run(Worker(emit, commands), commands)


if __name__ == "__main__":
    main()
