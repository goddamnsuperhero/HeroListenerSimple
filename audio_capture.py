"""Microphone capture: pushes fixed-size int16 frames into a queue.

Runs on PortAudio's own callback thread, so it never blocks on transcription.
"""
import queue

import sounddevice as sd

from settings import Settings


class AudioCapture:
    def __init__(self, frame_queue: "queue.Queue[bytes]", settings: Settings):
        self._q = frame_queue
        self._s = settings
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        if status:
            # Buffer overflow/underflow etc. — non-fatal; just surface it.
            print(f"[audio] {status}", flush=True)
        # indata is a raw CFFI buffer (RawInputStream); copy it out as bytes.
        self._q.put(bytes(indata))

    def start(self):
        s = self._s
        self._stream = sd.RawInputStream(
            samplerate=s.sample_rate,
            blocksize=s.frame_samples,   # one VAD frame per callback
            device=s.input_device,
            channels=s.channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
