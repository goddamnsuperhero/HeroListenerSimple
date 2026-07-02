"""Reference consumer: how a chatbot would read recent utterances and their age.

Run:  python tools/tail_log.py [path-to-jsonl]
Prints each new line as it appears, with 'age' = seconds since the speech started.
"""
import json
import os
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from settings import Settings  # noqa: E402

LOG_DIR = Settings.load().resolved_log_dir


def today_log() -> str:
    return os.path.join(LOG_DIR, f"transcript-{date.today().isoformat()}.jsonl")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else today_log()
    print(f"Tailing {path}  (Ctrl+C to stop)\n")
    pos = 0
    while True:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                f.seek(pos)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    e = json.loads(line)
                    age = (datetime.now(timezone.utc) - parse_iso(e["start"])).total_seconds()
                    flag = " [ERROR]" if e.get("error") else ""
                    print(f"[{age:6.1f}s ago]{flag} {e['text']}")
                pos = f.tell()
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
