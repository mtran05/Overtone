"""The block-by-block converter behind live playback and file conversion.

RealtimeConverter owns the overlap buffers and the SOLA crossfade. It feeds
each block to the streaming model in rtrvc.py. realtime.py imports this module
only when it is about to convert, so listing devices never loads torch.
"""

import logging
import time

import numpy as np
import torch
import torch.nn.functional as F
from torchaudio.transforms import Resample

from inference.device import detect_device
from inference.rtrvc import RVC


logger = logging.getLogger(__name__)


class RealtimeConverter:
    """Stream fixed-size blocks through the real-time RVC model."""

    def __init__(
        self,
        model_path,
        index_path,
        index_rate,
        key,
        formant,
        f0_method,
        sample_rate,
        block_time=0.25,
        crossfade_time=0.05,
        extra_time=2.5,
        rms_mix_rate=0.0,
        settings=None,
    ):
        """Load the voice model and size the overlap buffers from the block settings."""
        self.f0_method = f0_method
        self.rms_mix_rate = rms_mix_rate
        # Detection is expensive and runs once, where the device is first needed,
        # rather than at import time.
        self.config = detect_device()
        self.device = self.config.device
        self.rvc = RVC(
            key,
            formant,
            str(model_path),
            str(index_path) if index_path else "",
            index_rate,
            self.config,
            settings=settings,
        )
        self.sample_rate = int(sample_rate or self.rvc.tgt_sr)
        # zc is 10 ms. Every block length is a multiple of that so pitch frames line up.
        self.zc = self.sample_rate // 100
        self.block_frame = int(np.round(block_time * self.sample_rate / self.zc)) * self.zc
        self.block_frame_16k = 160 * self.block_frame // self.zc
        crossfade_frame = int(np.round(crossfade_time * self.sample_rate / self.zc)) * self.zc
        self.sola_buffer_frame = min(crossfade_frame, 4 * self.zc)
        self.sola_search_frame = self.zc
        self.extra_frame = int(np.round(extra_time * self.sample_rate / self.zc)) * self.zc
        self.skip_head = self.extra_frame // self.zc
        self.return_length = (
            self.block_frame + self.sola_buffer_frame + self.sola_search_frame
        ) // self.zc

        buffer_frames = (
            self.extra_frame
            + self.sola_buffer_frame
            + self.sola_search_frame
            + self.block_frame
        )
        self.input_wav = torch.zeros(buffer_frames, device=self.device, dtype=torch.float32)
        self.input_wav_res = torch.zeros(
            160 * buffer_frames // self.zc, device=self.device, dtype=torch.float32
        )
        self.sola_buffer = torch.zeros(
            self.sola_buffer_frame, device=self.device, dtype=torch.float32
        )
        self.fade_in_window = (
            torch.sin(
                0.5
                * np.pi
                * torch.linspace(
                    0.0,
                    1.0,
                    steps=self.sola_buffer_frame,
                    device=self.device,
                    dtype=torch.float32,
                )
            )
            ** 2
        )
        self.fade_out_window = 1 - self.fade_in_window
        self.resampler = Resample(
            orig_freq=self.sample_rate, new_freq=16000, dtype=torch.float32
        ).to(self.device)
        if self.rvc.tgt_sr != self.sample_rate:
            self.output_resampler = Resample(
                orig_freq=self.rvc.tgt_sr, new_freq=self.sample_rate, dtype=torch.float32
            ).to(self.device)
        else:
            self.output_resampler = None
        logger.info(
            "Real-time converter ready: model=%s, %d Hz, block=%d samples, device=%s",
            model_path,
            self.sample_rate,
            self.block_frame,
            self.device,
        )

    def process_block(self, block):
        """Convert one block and crossfade it onto the previous block."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if block.shape[0] != self.block_frame:
            raise ValueError(
                f"Expected {self.block_frame} samples, received {block.shape[0]}"
            )
        # Keep extra context in front of the new block, then resample that tail to 16 kHz.
        self.input_wav[: -self.block_frame] = self.input_wav[self.block_frame :].clone()
        self.input_wav[-self.block_frame :] = torch.from_numpy(block).to(self.device)
        self.input_wav_res[: -self.block_frame_16k] = self.input_wav_res[
            self.block_frame_16k :
        ].clone()
        resampled = self.resampler(self.input_wav[-self.block_frame - 2 * self.zc :])
        self.input_wav_res[-self.block_frame_16k - 160 :] = resampled[160:]

        inferred = self.rvc.infer(
            self.input_wav_res,
            self.block_frame_16k,
            self.skip_head,
            self.return_length,
            self.f0_method,
        )
        if self.output_resampler is not None:
            inferred = self.output_resampler(inferred)
        if self.rms_mix_rate < 1:
            inferred = self._mix_volume_envelope(inferred)

        # SOLA slides the new audio until it best matches the previous tail, then crossfades.
        window = self.sola_buffer_frame + self.sola_search_frame
        conv_input = inferred[None, None, :window]
        correlation = F.conv1d(conv_input, self.sola_buffer[None, None, :])
        energy = torch.sqrt(
            F.conv1d(
                conv_input**2,
                torch.ones(1, 1, self.sola_buffer_frame, device=self.device),
            )
            + 1e-8
        )
        sola_offset = int(torch.argmax(correlation[0, 0] / energy[0, 0]).item())
        inferred = inferred[sola_offset:]
        inferred[: self.sola_buffer_frame] *= self.fade_in_window
        inferred[: self.sola_buffer_frame] += self.sola_buffer * self.fade_out_window
        self.sola_buffer[:] = inferred[
            self.block_frame : self.block_frame + self.sola_buffer_frame
        ]
        return inferred[: self.block_frame].detach().cpu().numpy()

    def warm_up(self, blocks=2):
        """Run silent blocks so the first real block does no one-time work.

        The first block loads the pitch model and records the CUDA graphs for
        this block size. Live, that happens inside the audio callback and drops
        audio, so it is done here, before the stream opens. The buffers are
        cleared afterwards so the silence leaves no trace in the output.
        """
        started = time.perf_counter()
        silence = np.zeros(self.block_frame, dtype=np.float32)
        for _ in range(blocks):
            self.process_block(silence)
        self.input_wav.zero_()
        self.input_wav_res.zero_()
        self.sola_buffer.zero_()
        self.rvc.cache_pitch.zero_()
        self.rvc.cache_pitchf.zero_()
        logger.info("Warmed up in %.2fs", time.perf_counter() - started)

    def _mix_volume_envelope(self, inferred):
        """Pull the converted loudness toward the input block's envelope."""
        source = self.input_wav[self.extra_frame :]
        source = source[: inferred.shape[0]].detach().cpu().numpy()
        frame_length = 4 * self.zc
        rms_source = _rms_envelope(source, frame_length, self.zc, inferred.shape[0])
        rms_output = _rms_envelope(
            inferred.detach().cpu().numpy(), frame_length, self.zc, inferred.shape[0]
        )
        rms_source = torch.from_numpy(rms_source).to(self.device)
        rms_output = torch.from_numpy(rms_output).to(self.device)
        rms_output = torch.clamp(rms_output, min=1e-3)
        return inferred * torch.pow(rms_source / rms_output, 1 - self.rms_mix_rate)

    def convert(self, audio, sample_rate):
        """Convert a whole array by the same block path used for live audio."""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if sample_rate != self.sample_rate:
            audio = (
                Resample(orig_freq=sample_rate, new_freq=self.sample_rate)(
                    torch.from_numpy(audio)
                )
                .numpy()
            )
        original_length = len(audio)
        padding = (-original_length) % self.block_frame
        if padding:
            audio = np.pad(audio, (0, padding))
        blocks = []
        for start in range(0, len(audio), self.block_frame):
            blocks.append(self.process_block(audio[start : start + self.block_frame]))
        converted = np.concatenate(blocks)[:original_length]
        peak = np.max(np.abs(converted))
        if peak > 0.99:
            converted = converted / peak * 0.99
        return converted


def _rms_envelope(audio, frame_length, hop_length, size):
    """Return a per-sample RMS envelope aligned to audio."""
    import librosa

    rms = librosa.feature.rms(y=audio, frame_length=frame_length, hop_length=hop_length)
    envelope = torch.from_numpy(rms)
    envelope = F.interpolate(
        envelope.unsqueeze(0), size=size + 1, mode="linear", align_corners=True
    )[0, 0, :-1]
    return envelope.numpy()
