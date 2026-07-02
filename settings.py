"""App settings: fixed audio format + user-tunable options persisted to settings.json.

The API key is intentionally NOT stored here — it stays in .env (read via os.getenv) so
secrets never land in the settings file.
"""
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# When frozen by PyInstaller, anchor data files (.env, settings.json, transcripts/) to the
# folder containing the .exe — NOT the temp extraction dir — so they persist next to it.
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ENV_FILE = os.path.join(APP_DIR, ".env")

# Load .env from beside the app (works both in dev and when frozen).
load_dotenv(ENV_FILE)


def clean_api_key(value: str, key_env: str = "") -> str:
    """Sanitize a pasted API key. Users often paste a whole .env line
    (``GROQ_API_KEY=gsk_...``) or an auth header (``Bearer gsk_...``) into the key field;
    strip those wrappers plus surrounding quotes/whitespace so only the raw key is stored."""
    v = (value or "").strip().strip("\"'").strip()
    # Drop a leading "NAME=" prefix (the configured key_env, or any env-style NAME=).
    if key_env and v.startswith(f"{key_env}="):
        v = v[len(key_env) + 1:]
    else:
        v = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*", "", v, count=1)
    if v[:7].lower() == "bearer ":
        v = v[7:]
    return v.strip().strip("\"'").strip()


def set_env_var(key: str, value: str, path: str = ENV_FILE) -> None:
    """Create or update a single ``KEY=value`` line in the .env file next to the app,
    preserving any other lines and comments, and update the live process environment so
    the change takes effect immediately (without a restart or a second load_dotenv)."""
    value = (value or "").strip()
    lines: list = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            if stripped.split("=", 1)[0].strip() == key:
                lines[i] = f"{key}={value}"
                replaced = True
                break
    if not replaced:
        lines.append(f"{key}={value}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.environ[key] = value

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
        "key_env": "GROQ_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
        "key_env": "OPENAI_API_KEY",
    },
}

# Fields the GUI can change and we persist to disk.
PERSIST_FIELDS = (
    "provider", "model", "language", "input_device",
    "vad_aggressiveness", "silence_hangover_ms", "preroll_ms",
    "min_speech_ms", "max_utterance_s", "log_dir",
)


@dataclass
class Settings:
    # --- user-tunable (persisted) ---
    provider: str = "groq"
    model: str = ""                       # blank => provider default
    language: str = "en"
    input_device: Optional[int] = None    # None => system default
    vad_aggressiveness: int = 2           # 0 (lax) .. 3 (strict)
    silence_hangover_ms: int = 600
    preroll_ms: int = 300
    min_speech_ms: int = 250
    max_utterance_s: float = 20.0
    log_dir: str = "transcripts"

    # --- transcription robustness ---
    max_retries: int = 3
    retry_backoff_s: float = 1.0

    # --- fixed audio format (not user-tunable) ---
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 30                    # webrtcvad accepts 10/20/30 ms only

    # ---- derived ----
    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def _provider_cfg(self) -> dict:
        return PROVIDERS.get(self.provider, PROVIDERS["groq"])

    @property
    def base_url(self) -> str:
        return self._provider_cfg["base_url"]

    @property
    def resolved_model(self) -> str:
        return self.model.strip() or self._provider_cfg["model"]

    @property
    def key_env(self) -> str:
        return self._provider_cfg["key_env"]

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv(self.key_env)

    @property
    def resolved_log_dir(self) -> str:
        """Absolute output folder. Relative log_dir is anchored to the app folder so the
        save location is the same no matter what directory you launch from."""
        if os.path.isabs(self.log_dir):
            return self.log_dir
        return os.path.join(APP_DIR, self.log_dir)

    # ---- persistence ----
    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in PERSIST_FIELDS}

    def save(self, path: str = SETTINGS_FILE) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def save_api_key(self, key: str) -> None:
        """Persist the secret for the *current* provider to .env (keyed by ``key_env``)
        so it never lands in settings.json. Takes effect immediately."""
        set_env_var(self.key_env, clean_api_key(key, self.key_env))

    @classmethod
    def load(cls, path: str = SETTINGS_FILE) -> "Settings":
        s = cls()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for k in PERSIST_FIELDS:
                    if k in data:
                        setattr(s, k, data[k])
            except Exception as e:  # noqa: BLE001
                print(f"[settings] could not load {path}: {e}", flush=True)
        return s
