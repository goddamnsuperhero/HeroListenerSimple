"""Headless CLI entry point (no GUI): mic -> VAD -> remote transcription -> log.

For the graphical control panel, run `python app.py` instead.
"""
import sys
import time

import sounddevice as sd

from pipeline import PipelineController
from settings import Settings


def _describe_device(settings: Settings) -> str:
    try:
        idx = settings.input_device
        if idx is None:
            idx = sd.default.device[0]
        return f"#{idx} {sd.query_devices(idx)['name']}"
    except Exception as e:  # noqa: BLE001
        return f"(could not query device: {e})"


def main() -> int:
    s = Settings.load()
    if not s.api_key:
        print(f"ERROR: no API key found ({s.key_env}) for provider '{s.provider}'. "
              f"Set it in .env — see README.md.", file=sys.stderr)
        return 1

    print(f"Provider : {s.provider}  ({s.base_url})")
    print(f"Model    : {s.resolved_model}")
    print(f"Mic      : {_describe_device(s)}")
    print(f"Log dir  : {s.resolved_log_dir}")
    print("Listening... (Ctrl+C to stop)\n")

    controller = PipelineController(s)
    controller.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
