# HeroListenerSimple — realtime mic → transcript log

A featherweight app that listens to your microphone, transcribes speech in near-realtime
using a **remote** API (so your GPU/CPU stay free for gaming + streaming), and appends
timestamped entries to a JSONL log that a chatbot can read.

## How it works

```
mic ─▶ audio_capture ─▶ vad_segmenter ─▶ transcriber ─▶ log_writer ─▶ transcripts/*.jsonl
       (PortAudio)       (webrtcvad,       (Groq/OpenAI    (JSONL, one
                          speech only)      Whisper API)    line per utterance)
```

Only *speech* is uploaded (voice-activity detection gates out silence), so it stays cheap
and current. Each entry is timestamped at the moment speech **started**, so a bot can
compute how old a message is regardless of network latency.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # then edit .env and add your API key
```

Get a Groq key at https://console.groq.com/keys (default provider — ~$0.04 per hour of
speech). To use OpenAI instead, set `PROVIDER=openai` and `OPENAI_API_KEY` in `.env`.

## Run

**GUI (recommended):**

```bash
python app.py
```

A small control panel: pick + **Test** your mic, edit settings (saved to `settings.json`
and remembered next launch), hit **Start**, and watch the transcript update live.

**Headless CLI** (no window; uses the same `settings.json` / `.env`):

```bash
python main.py                 # start listening; speak; Ctrl+C to stop
python tools/tail_log.py       # (another terminal) see how a bot reads the log
python tools/list_devices.py   # list mic indices
```

## Log format

`transcripts/transcript-YYYY-MM-DD.jsonl`, one JSON object per line:

```json
{"start":"2026-07-02T19:04:12.481Z","end":"2026-07-02T19:04:15.902Z","monotonic":51234.87,"duration_s":3.42,"text":"hey can you check the score","model":"whisper-large-v3-turbo","error":false}
```

A consumer computes `age_seconds = now_utc - start`; `end` marks recency of the latest line.

## Tuning

Edit settings in the GUI (they persist to `settings.json`): input device, provider, model,
language, VAD aggressiveness, silence gap, max utterance length, min speech length.
Defaults and fixed audio format live in `settings.py`. The API key stays in `.env` (never
written to `settings.json`).