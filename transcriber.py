"""Transcribes utterances remotely and writes them to the log, in order.

A single FIFO worker thread keeps log entries chronological and avoids hammering the
API with parallel calls. Each utterance is encoded to an in-memory WAV and sent to an
OpenAI-compatible transcription endpoint (Groq by default).
"""
import io
import queue
import threading
import time
import wave
from datetime import timedelta
from typing import Callable, Optional

from openai import OpenAI

from log_writer import LogWriter
from settings import Settings
from vad_segmenter import Utterance


def pcm_to_wav(pcm: bytes, settings: Settings) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(settings.channels)
        w.setsampwidth(2)   # int16
        w.setframerate(settings.sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_pcm(pcm: bytes, settings: Settings) -> str:
    """One-shot transcription of a raw PCM clip. Used by the mic self-test."""
    client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)
    resp = client.audio.transcriptions.create(
        model=settings.resolved_model,
        file=("clip.wav", pcm_to_wav(pcm, settings), "audio/wav"),
        language=settings.language,
        response_format="json",
    )
    return resp.text.strip()


class Transcriber(threading.Thread):
    def __init__(self, utt_queue: "queue.Queue[Utterance]", log_writer: LogWriter,
                 settings: Settings, on_entry: Optional[Callable[[dict], None]] = None):
        super().__init__(daemon=True, name="transcriber")
        self._q = utt_queue
        self._log = log_writer
        self._s = settings
        self._on_entry = on_entry
        self._stop_evt = threading.Event()
        self._client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.is_set():
            try:
                utt = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._process(utt)

    def _process(self, utt: Utterance):
        text, error = self._transcribe(pcm_to_wav(utt.pcm, self._s))
        if not text and not error:
            return  # non-speech that Whisper returned empty for — skip
        entry = self._log.write(
            start=utt.start_utc,
            end=utt.start_utc + timedelta(seconds=utt.duration_s),
            monotonic=utt.start_monotonic,
            duration_s=utt.duration_s,
            text=text,
            model=self._s.resolved_model,
            error=error,
        )
        if self._on_entry is not None:
            try:
                self._on_entry(entry)
            except Exception as e:  # noqa: BLE001 — UI callback must never kill the worker
                print(f"[transcriber] on_entry callback failed: {e}", flush=True)
        tag = "ERR" if error else "ok "
        print(f"[{tag}] ({utt.duration_s:.1f}s) {text!r}", flush=True)

    def _transcribe(self, wav: bytes):
        delay = self._s.retry_backoff_s
        for attempt in range(1, self._s.max_retries + 1):
            try:
                resp = self._client.audio.transcriptions.create(
                    model=self._s.resolved_model,
                    file=("utterance.wav", wav, "audio/wav"),
                    language=self._s.language,
                    response_format="json",
                )
                return (resp.text.strip(), False)
            except Exception as e:  # noqa: BLE001 — keep the pipeline alive on any failure
                print(f"[transcriber] attempt {attempt}/{self._s.max_retries} failed: {e}",
                      flush=True)
                if attempt < self._s.max_retries:
                    time.sleep(delay)
                    delay *= 2
        # Persist an empty, error-flagged entry so the timeline slot isn't silently lost.
        return ("", True)
