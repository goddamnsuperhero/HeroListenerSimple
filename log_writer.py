"""Appends transcript entries as JSON lines, one file per calendar day.

Flushes after every write so a chatbot tailing the file sees new lines immediately.
"""
import json
import os
import threading
from datetime import date, datetime


def _iso(dt: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and a trailing 'Z'."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogWriter:
    def __init__(self, log_dir: str = "transcripts"):
        self._dir = log_dir
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = None
        self._date = None

    def _file_for_today(self):
        today = date.today()
        if self._date != today or self._fh is None:
            if self._fh is not None:
                self._fh.close()
            path = os.path.join(self._dir, f"transcript-{today.isoformat()}.jsonl")
            self._fh = open(path, "a", encoding="utf-8")
            self._date = today
        return self._fh

    def write(self, start, end, monotonic, duration_s, text, model, error=False) -> dict:
        entry = {
            "start": _iso(start),
            "end": _iso(end),
            "monotonic": round(monotonic, 3),
            "duration_s": round(duration_s, 3),
            "text": text,
            "model": model,
            "error": error,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            fh = self._file_for_today()
            fh.write(line + "\n")
            fh.flush()
        return entry

    def close(self):
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
