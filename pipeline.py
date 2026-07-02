"""Owns the capture -> VAD -> transcribe -> log pipeline as a start/stoppable unit,
plus a blocking mic self-test helper. Keeps the GUI (and CLI) free of wiring details.
"""
import queue
from typing import Callable, Optional

import sounddevice as sd

from audio_capture import AudioCapture
from log_writer import LogWriter
from settings import Settings
from transcriber import Transcriber, transcribe_pcm
from vad_segmenter import VadSegmenter


class PipelineController:
    def __init__(self, settings: Settings, on_entry: Optional[Callable[[dict], None]] = None):
        self._s = settings
        self._on_entry = on_entry
        self._running = False
        self._log = None
        self._capture = None
        self._vad = None
        self._transcriber = None

    def is_running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        frame_q: "queue.Queue[bytes]" = queue.Queue()
        utt_q: "queue.Queue" = queue.Queue()

        self._log = LogWriter(self._s.resolved_log_dir)
        self._capture = AudioCapture(frame_q, self._s)
        self._vad = VadSegmenter(frame_q, utt_q, self._s)
        self._transcriber = Transcriber(utt_q, self._log, self._s, on_entry=self._on_entry)

        self._vad.start()
        self._transcriber.start()
        self._capture.start()   # start feeding frames last
        self._running = True

    def stop(self):
        if not self._running:
            return
        self._capture.stop()            # stop feeding frames first
        self._vad.stop()
        self._vad.join(timeout=2)
        self._transcriber.stop()        # let it drain the last queued utterance
        self._transcriber.join(timeout=15)
        self._log.close()
        self._running = False


def record_clip(settings: Settings, seconds: float, device: Optional[int] = None) -> bytes:
    """Blocking capture of `seconds` of raw PCM from `device` (or the configured one)."""
    dev = device if device is not None else settings.input_device
    n_frames = max(1, int(seconds * 1000 / settings.frame_ms))
    frames = []
    with sd.RawInputStream(samplerate=settings.sample_rate, blocksize=settings.frame_samples,
                           device=dev, channels=settings.channels, dtype="int16") as st:
        for _ in range(n_frames):
            data, _overflow = st.read(settings.frame_samples)
            frames.append(bytes(data))
    return b"".join(frames)


def test_mic(settings: Settings, seconds: float = 3.0, device: Optional[int] = None) -> str:
    """Record a short clip from the mic and transcribe it — proves mic + API end to end."""
    pcm = record_clip(settings, seconds, device)
    return transcribe_pcm(pcm, settings)
