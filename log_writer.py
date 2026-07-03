"""Appends transcript entries as JSON lines to a single, fixed-path rolling file.

Everything is written to one file (default: transcripts/transcript.jsonl) so an external
tool can always read the same location. When that file grows past `max_bytes` it rotates.

Two rotation modes:
  * archive (prune=False): the full file is moved aside to transcript-<timestamp>.jsonl.
  * prune   (prune=True):  the last `carryover_seconds` of conversation are kept at the
                           head of a fresh file and every old transcript-* archive is
                           deleted, so exactly one small, bounded file ever exists.

Either way the active file keeps its fixed name, so the tool's read path never changes.
Flushes after every write so a tool tailing the file sees new lines immediately.
"""
import glob
import json
import os
import threading
from datetime import datetime


def _iso(dt: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and a trailing 'Z'."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _parse_iso(s: str):
    """Parse a timestamp written by _iso back to a datetime, or None if unparseable."""
    try:
        return datetime.strptime(s.rstrip("Z"), "%Y-%m-%dT%H:%M:%S.%f")
    except (ValueError, AttributeError):
        return None


class LogWriter:
    def __init__(self, log_dir: str = "transcripts",
                 filename: str = "transcript.jsonl", max_bytes: int = 1_000_000,
                 prune: bool = False, carryover_seconds: float = 60.0):
        self._dir = log_dir
        self._filename = filename
        self._max_bytes = max_bytes
        self._prune = prune
        self._carryover_s = carryover_seconds
        os.makedirs(self._dir, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = None

    @property
    def path(self) -> str:
        """The fixed path your tool should read."""
        return os.path.join(self._dir, self._filename)

    def _archive_glob(self) -> str:
        base, ext = os.path.splitext(self._filename)
        return os.path.join(self._dir, f"{base}-*{ext}")

    def _open(self):
        """Ensure the active file is open. If it already exceeds the threshold from a
        previous run, rotate it first so we start bounded."""
        if self._fh is None:
            if (self._max_bytes > 0 and os.path.exists(self.path)
                    and os.path.getsize(self.path) >= self._max_bytes):
                self._do_rotate()
            self._fh = open(self.path, "a", encoding="utf-8")
        return self._fh

    def _do_rotate(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if not os.path.exists(self.path):
            return
        if self._prune:
            self._rotate_prune()
        else:
            self._rotate_archive()

    def _rotate_archive(self):
        """Move the active file aside to transcript-<timestamp>.jsonl and start fresh."""
        base, ext = os.path.splitext(self._filename)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(self._dir, f"{base}-{stamp}{ext}")
        n = 1
        while os.path.exists(dest):   # avoid clobbering on two rotations in one second
            dest = os.path.join(self._dir, f"{base}-{stamp}-{n}{ext}")
            n += 1
        os.replace(self.path, dest)

    def _rotate_prune(self):
        """Keep only the last `carryover_seconds` of entries in a fresh file, then delete
        every old transcript-* archive. Recent context survives; nothing else is retained."""
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept = self._recent_tail(lines)

        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, self.path)   # atomic swap so a reader never sees a half-written file

        for old in glob.glob(self._archive_glob()):
            try:
                os.remove(old)
            except OSError:
                pass   # a reader may hold it open; skip and retry on the next rotation

    def _recent_tail(self, lines):
        """Return the trailing lines within carryover_seconds of the newest entry."""
        if self._carryover_s <= 0 or not lines:
            return []
        times = [self._line_time(ln) for ln in lines]
        newest = max((t for t in times if t is not None), default=None)
        if newest is None:
            return lines[-50:]   # timestamps unreadable — fall back to a small line count
        cutoff = newest.timestamp() - self._carryover_s
        return [ln for ln, t in zip(lines, times)
                if t is None or t.timestamp() >= cutoff]

    @staticmethod
    def _line_time(line: str):
        """Timestamp of a JSONL entry's 'start', or None if the line can't be parsed."""
        try:
            return _parse_iso(json.loads(line).get("start", ""))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

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
            fh = self._open()
            fh.write(line + "\n")
            fh.flush()
            # Rotate *after* writing so no entry is ever split across files.
            if self._max_bytes > 0 and fh.tell() >= self._max_bytes:
                self._do_rotate()
        return entry

    def close(self):
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
