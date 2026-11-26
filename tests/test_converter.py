"""The block, overlap, and SOLA path of RealtimeConverter, on the CPU with a fake model.

The fake model returns a constant signal, so any seam the crossfade leaves at a
block boundary shows up as a deviation from that constant.
"""

from types import SimpleNamespace

import numpy as np
import pytest


torch = pytest.importorskip("torch")

from inference.converter import RealtimeConverter  # noqa: E402


class ConstantModel:
    """Stands in for RVC: same sample rate as the stream, constant output."""

    def __init__(self, level=0.25, sample_rate=16000):
        self.level = level
        self.tgt_sr = sample_rate
        self.pth_path = "constant.pth"
        self.config = SimpleNamespace(device=torch.device("cpu"))
        self.cache_pitch = torch.zeros(1024, dtype=torch.long)
        self.cache_pitchf = torch.zeros(1024)
        self.calls = 0

    def infer(self, input_wav, block_frame_16k, skip_head, return_length, f0_method):
        self.calls += 1
        self.cache_pitch[-1] = 7
        return torch.full((return_length * (self.tgt_sr // 100),), self.level)


def make(rms_mix_rate=1.0, **model):
    rvc = ConstantModel(**model)
    converter = RealtimeConverter(rvc, "rmvpe", sample_rate=16000, block_time=0.1, crossfade_time=0.02, extra_time=0.5, rms_mix_rate=rms_mix_rate)
    return converter, rvc


def test_block_sizes_are_whole_10ms_frames():
    converter, _ = make()
    assert converter.block_frame == 1600
    assert converter.block_frame % converter.zc == 0


def test_process_block_rejects_the_wrong_length():
    converter, _ = make()
    with pytest.raises(ValueError, match="Expected 1600 samples"):
        converter.process_block(np.zeros(100, dtype=np.float32))


def test_crossfade_leaves_no_seam_between_blocks():
    converter, _ = make(level=0.25)
    out = np.concatenate([converter.process_block(np.zeros(1600, dtype=np.float32)) for _ in range(4)])
    # The very first crossfade fades in from silence; after that every block joins seamlessly.
    np.testing.assert_allclose(out[1600:], 0.25, atol=1e-5)


def test_convert_returns_the_input_length_at_the_stream_rate():
    converter, rvc = make(level=0.25)
    out = converter.convert(np.zeros(5000, dtype=np.float32), 16000)
    assert out.shape == (5000,)
    assert rvc.calls == 4  # 5000 samples pad up to four 1600-sample blocks


def test_convert_scales_down_output_that_would_clip():
    converter, _ = make(level=2.0)
    out = converter.convert(np.zeros(3200, dtype=np.float32), 16000)
    assert np.max(np.abs(out)) == pytest.approx(0.99, abs=1e-6)


def test_loudness_follows_a_silent_input_when_rms_mix_rate_is_zero():
    converter, _ = make(rms_mix_rate=0.0, level=0.25)
    out = np.concatenate([converter.process_block(np.zeros(1600, dtype=np.float32)) for _ in range(3)])
    assert np.max(np.abs(out)) < 1e-3


def test_warm_up_runs_blocks_then_leaves_no_trace():
    converter, rvc = make(level=0.25)
    converter.warm_up(blocks=2)
    assert rvc.calls == 2
    assert not converter.sola_buffer.any()
    assert not converter.input_wav.any()
    assert not rvc.cache_pitch.any()


def test_warm_up_also_readies_the_other_trackers():
    converter, rvc = make()
    converter.warm_up(blocks=2, also=("rmvpe", "fcpe"))
    assert converter.ready_methods == {"rmvpe", "fcpe", "pm"}
    assert converter.f0_method == "rmvpe"
    assert rvc.calls == 4  # rmvpe is the chosen tracker, so only fcpe adds blocks


def test_a_tracker_that_fails_to_warm_up_is_left_out():
    converter, rvc = make()

    def infer(input_wav, block_frame_16k, skip_head, return_length, f0_method):
        if f0_method == "fcpe":
            raise RuntimeError("no fcpe")
        return torch.full((return_length * 160,), 0.25)

    rvc.infer = infer
    converter.warm_up(also=("fcpe",))
    assert converter.ready_methods == {"rmvpe", "pm"}
    assert converter.f0_method == "rmvpe"
