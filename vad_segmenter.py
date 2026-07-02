"""Turns a stream of audio frames into discrete speech utterances.

Uses webrtcvad with a ring-buffer state machine:
  - triggers on speech onset (with a short pre-roll so we don't clip the first word),
  - ends the clip on a trailing silence gap, OR force-flushes at a max length so a long
    monologue still produces timely, timestamped entries.

Timestamps mark when speech STARTED (adjusted for pre-roll), not when transcription runs.
"""
import collections
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import webrtcvad

from settings import Settings


@dataclass
class Utterance:
    pcm: bytes
    start_utc: datetime
    start_monotonic: float
    duration_s: float


class VadSegmenter(threading.Thread):
    def __init__(self, frame_queue: "queue.Queue[bytes]",
                 utt_queue: "queue.Queue[Utterance]", settings: Settings):
        super().__init__(daemon=True, name="vad")
        self._in = frame_queue
        self._out = utt_queue
        self._s = settings
        self._stop_evt = threading.Event()
        self._vad = webrtcvad.Vad(settings.vad_aggressiveness)

        self._frame_s = settings.frame_ms / 1000.0
        self._num_padding = max(1, settings.preroll_ms // settings.frame_ms)
        self._hangover_frames = max(1, settings.silence_hangover_ms // settings.frame_ms)
        self._min_frames = max(1, settings.min_speech_ms // settings.frame_ms)
        self._max_frames = max(1, int(settings.max_utterance_s * 1000 // settings.frame_ms))

    def stop(self):
        self._stop_evt.set()

    def run(self):
        s = self._s
        ring = collections.deque(maxlen=self._num_padding)
        triggered = False
        voiced = []            # frames of the current utterance
        silence_run = 0        # consecutive non-speech frames while triggered
        start_utc = None
        start_mono = None

        while not self._stop_evt.is_set():
            try:
                frame = self._in.get(timeout=0.5)
            except queue.Empty:
                continue
            if len(frame) != s.frame_bytes:
                continue  # defensive: ignore odd-sized frames

            is_speech = self._vad.is_speech(frame, s.sample_rate)

            if not triggered:
                ring.append((frame, is_speech))
                if sum(1 for _, sp in ring if sp) > 0.9 * ring.maxlen:
                    # Speech onset — start a clip, prepend the pre-roll buffer.
                    triggered = True
                    preroll = [f for f, _ in ring]
                    voiced = list(preroll)
                    silence_run = 0
                    preroll_dur = len(preroll) * self._frame_s
                    start_mono = time.monotonic() - preroll_dur
                    start_utc = datetime.now(timezone.utc) - timedelta(seconds=preroll_dur)
                    ring.clear()
            else:
                voiced.append(frame)
                silence_run = 0 if is_speech else silence_run + 1

                ended = silence_run >= self._hangover_frames
                too_long = len(voiced) >= self._max_frames

                if ended:
                    self._flush(voiced, start_utc, start_mono)
                    triggered = False
                    voiced = []
                    silence_run = 0
                    ring.clear()
                elif too_long:
                    # Still talking — flush what we have and seamlessly begin a new clip.
                    self._flush(voiced, start_utc, start_mono)
                    voiced = []
                    silence_run = 0
                    start_mono = time.monotonic()
                    start_utc = datetime.now(timezone.utc)

    def _flush(self, frames, start_utc, start_mono):
        if len(frames) < self._min_frames:
            return  # too short to be real speech
        pcm = b"".join(frames)
        duration_s = len(pcm) / 2 / self._s.sample_rate
        self._out.put(Utterance(pcm=pcm, start_utc=start_utc,
                                start_monotonic=start_mono, duration_s=duration_s))
