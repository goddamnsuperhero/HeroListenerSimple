"""List available microphone input devices and their indices.

Run:  python tools/list_devices.py
Then set INPUT_DEVICE=<index> in your .env if the default isn't the mic you want.
"""
import sounddevice as sd

default_in = sd.default.device[0]
print("Available input devices:\n")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        marker = "  (default)" if i == default_in else ""
        print(f"  #{i}: {d['name']}  [{d['max_input_channels']} ch]{marker}")
print("\nSet INPUT_DEVICE=<index> in your .env to pick one (blank = system default).")
