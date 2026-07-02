"""BlackcatStreamBot control panel.

A small tkinter GUI to: start/stop transcription, edit settings (persisted to
settings.json), select + test the microphone, and watch the transcript update live.
Run:  python app.py
"""
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import sounddevice as sd

from pipeline import PipelineController, test_mic
from settings import PROVIDERS, Settings

INFO = "ⓘ"   # circled 'i' glyph used as the tooltip icon


class Tooltip:
    """Lightweight hover tooltip for any widget."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, wraplength=300, padx=6, pady=4).pack()

    def _hide(self, _event):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def list_input_devices():
    """Return [(index_or_None, label)] for the device dropdown, default first."""
    items = [(None, "System default")]
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "  (default)" if i == default_in else ""
            items.append((i, f"{i}: {d['name']}{mark}"))
    return items


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = Settings.load()
        self._entry_q: "queue.Queue[dict]" = queue.Queue()
        self.controller = PipelineController(self.settings,
                                             on_entry=lambda e: self._entry_q.put(e))
        self._toggle_widgets = []

        root.title("BlackcatStreamBot")
        root.geometry("660x680")
        root.minsize(560, 560)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)   # transcript row grows

        self._build_mic_row()
        self._build_settings()
        self._build_output()
        self._build_controls()
        self._build_transcript()
        self._build_statusbar()

        self._load_into_widgets()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._poll_entries)

    # ---------------- UI construction ----------------
    def _build_mic_row(self):
        f = ttk.LabelFrame(self.root, text="Microphone", padding=8)
        f.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        f.columnconfigure(0, weight=1)

        self._devices = list_input_devices()
        self.mic_var = tk.StringVar()
        self.mic_combo = ttk.Combobox(f, textvariable=self.mic_var, state="readonly",
                                      values=[label for _, label in self._devices])
        self.mic_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        Tooltip(self.mic_combo, "The microphone to listen to. A device may appear several "
                "times (different Windows audio subsystems: MME/DirectSound/WASAPI) — any "
                "works; WASAPI entries have the lowest latency.")

        self.refresh_btn = ttk.Button(f, text="Refresh", width=9, command=self._refresh_devices)
        self.refresh_btn.grid(row=0, column=1, padx=2)
        Tooltip(self.refresh_btn, "Re-scan for input devices (e.g. after plugging in a mic).")

        self.test_btn = ttk.Button(f, text="Test", width=9, command=self._on_test)
        self.test_btn.grid(row=0, column=2, padx=2)
        Tooltip(self.test_btn, "Records 3 seconds and shows what the transcriber heard — a "
                "quick end-to-end check of mic + API before you Start.")
        self._toggle_widgets += [self.mic_combo, self.refresh_btn, self.test_btn]

    def _build_settings(self):
        f = ttk.LabelFrame(self.root, text="Settings", padding=8)
        f.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        for c in (1, 3):
            f.columnconfigure(c, weight=1)

        self.provider_var = tk.StringVar()
        self.language_var = tk.StringVar()
        self.vad_var = tk.StringVar()
        self.silence_var = tk.StringVar()
        self.maxutt_var = tk.StringVar()
        self.minspeech_var = tk.StringVar()

        def row(r, c, label, widget, tip):
            lbl = ttk.Label(f, text=f"{label}  {INFO}")
            lbl.grid(row=r, column=c, sticky="w", padx=(2, 6), pady=3)
            widget.grid(row=r, column=c + 1, sticky="ew", padx=(0, 10), pady=3)
            Tooltip(lbl, tip)
            Tooltip(widget, tip)

        prov = ttk.Combobox(f, textvariable=self.provider_var, state="readonly",
                            values=list(PROVIDERS.keys()), width=12)
        row(0, 0, "Provider", prov,
            "Cloud service that transcribes your audio. 'groq' is cheapest & fastest; "
            "'openai' uses your OpenAI key. The matching key must be in .env.")
        row(0, 2, "Language", ttk.Entry(f, textvariable=self.language_var, width=10),
            "Spoken language as a 2-letter code (e.g. 'en'). Fixing it is faster and more "
            "accurate than auto-detect.")
        row(1, 0, "VAD strictness (0-3)", ttk.Spinbox(f, from_=0, to=3, textvariable=self.vad_var, width=8),
            "How aggressively silence/noise is filtered out. 0 = lax (captures more, may "
            "include background noise), 3 = strict (only clear speech). 2 is a good default.")
        row(1, 2, "Silence gap (ms)", ttk.Entry(f, textvariable=self.silence_var, width=10),
            "How long you pause before the current phrase is finalized and sent. Lower = "
            "snappier, but may cut you off mid-thought. Default 600.")
        row(2, 0, "Max utterance (s)", ttk.Entry(f, textvariable=self.maxutt_var, width=10),
            "Force-send a phrase after this many seconds of non-stop talking, so the bot "
            "never waits too long during a monologue. Default 20.")
        row(2, 2, "Min speech (ms)", ttk.Entry(f, textvariable=self.minspeech_var, width=10),
            "Ignore blips shorter than this (coughs, clicks, keyboard). Default 250.")

        self._toggle_widgets += [prov] + [w for w in f.winfo_children()
                                          if isinstance(w, (ttk.Entry, ttk.Spinbox))]

    def _build_output(self):
        f = ttk.LabelFrame(self.root, text="Output", padding=8)
        f.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        f.columnconfigure(1, weight=1)

        lbl = ttk.Label(f, text=f"Saving to  {INFO}")
        lbl.grid(row=0, column=0, sticky="w", padx=(2, 6))
        self.path_var = tk.StringVar(value=self.settings.resolved_log_dir)
        ent = ttk.Entry(f, textvariable=self.path_var, state="readonly")
        ent.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        open_btn = ttk.Button(f, text="Open folder", command=self._open_log_dir)
        open_btn.grid(row=0, column=2)

        tip = ("Transcripts are written here as transcript-YYYY-MM-DD.jsonl — one JSON "
               "line per phrase, timestamped in UTC. Change the folder via 'log_dir' in "
               "settings.json.")
        Tooltip(lbl, tip)
        Tooltip(ent, tip)
        Tooltip(open_btn, "Open the transcript folder in Explorer.")

    def _build_controls(self):
        f = ttk.Frame(self.root, padding=(8, 2))
        f.grid(row=3, column=0, sticky="ew", padx=8)
        f.columnconfigure(1, weight=1)
        self.toggle_btn = ttk.Button(f, text="Start", width=14, command=self._on_toggle)
        self.toggle_btn.grid(row=0, column=0, sticky="w")
        Tooltip(self.toggle_btn, "Start or stop listening. Settings lock while listening.")
        self.run_lbl = ttk.Label(f, text="● stopped", foreground="#a00")
        self.run_lbl.grid(row=0, column=1, sticky="w", padx=10)

    def _build_transcript(self):
        f = ttk.LabelFrame(self.root, text="Live transcript", padding=6)
        f.grid(row=4, column=0, sticky="nsew", padx=8, pady=4)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        self.text = ScrolledText(f, wrap="word", state="disabled", height=12,
                                 font=("Consolas", 10))
        self.text.grid(row=0, column=0, sticky="nsew")
        self.text.tag_config("time", foreground="#0a7")
        self.text.tag_config("err", foreground="#a00")

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Ready.")
        bar = ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                        anchor="w", padding=(6, 2))
        bar.grid(row=5, column=0, sticky="ew", padx=8, pady=(0, 8))

    # ---------------- settings <-> widgets ----------------
    def _load_into_widgets(self):
        s = self.settings
        idx = next((i for i, (dev, _) in enumerate(self._devices) if dev == s.input_device), 0)
        self.mic_combo.current(idx)
        self.provider_var.set(s.provider)
        self.language_var.set(s.language)
        self.vad_var.set(str(s.vad_aggressiveness))
        self.silence_var.set(str(s.silence_hangover_ms))
        self.maxutt_var.set(str(s.max_utterance_s))
        self.minspeech_var.set(str(s.min_speech_ms))

    def _selected_device(self):
        i = self.mic_combo.current()
        return self._devices[i][0] if 0 <= i < len(self._devices) else None

    def _apply_widgets_to_settings(self) -> bool:
        s = self.settings
        try:
            s.input_device = self._selected_device()
            s.provider = self.provider_var.get().strip() or "groq"
            s.language = self.language_var.get().strip() or "en"
            s.vad_aggressiveness = max(0, min(3, int(self.vad_var.get())))
            s.silence_hangover_ms = int(self.silence_var.get())
            s.max_utterance_s = float(self.maxutt_var.get())
            s.min_speech_ms = int(self.minspeech_var.get())
        except ValueError:
            messagebox.showerror("Invalid setting",
                                 "VAD/silence/utterance/speech fields must be numbers.")
            return False
        s.save()
        self.path_var.set(s.resolved_log_dir)
        return True

    # ---------------- actions ----------------
    def _refresh_devices(self):
        self._devices = list_input_devices()
        self.mic_combo["values"] = [label for _, label in self._devices]
        self._load_into_widgets()
        self.status_var.set("Device list refreshed.")

    def _open_log_dir(self):
        d = self.settings.resolved_log_dir
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)   # Windows
        except Exception as e:  # noqa: BLE001
            self.status_var.set(f"Could not open folder: {e}")

    def _on_test(self):
        if not self._apply_widgets_to_settings():
            return
        if not self.settings.api_key:
            messagebox.showwarning("No API key",
                                   f"No {self.settings.key_env} set in .env for provider "
                                   f"'{self.settings.provider}'.")
            return
        self._set_enabled(False)
        self.toggle_btn.config(state="disabled")
        self.status_var.set("Recording 3s… speak now.")
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self):
        try:
            text = test_mic(self.settings, seconds=3.0)
            msg = f"Heard: {text!r}" if text else "Heard nothing (silence?)."
        except Exception as e:  # noqa: BLE001
            msg = f"Test failed: {e}"
        self.root.after(0, lambda: self._test_done(msg))

    def _test_done(self, msg: str):
        self.status_var.set(msg)
        self._set_enabled(True)
        self.toggle_btn.config(state="normal")

    def _on_toggle(self):
        if self.controller.is_running():
            self.status_var.set("Stopping…")
            self.root.update_idletasks()
            self.controller.stop()
            self.toggle_btn.config(text="Start")
            self.run_lbl.config(text="● stopped", foreground="#a00")
            self._set_enabled(True)
            self.status_var.set("Stopped.")
        else:
            if not self._apply_widgets_to_settings():
                return
            if not self.settings.api_key:
                messagebox.showwarning("No API key",
                                       f"No {self.settings.key_env} set in .env for provider "
                                       f"'{self.settings.provider}'.")
                return
            try:
                self.controller.start()
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Could not start", str(e))
                return
            self.toggle_btn.config(text="Stop")
            self.run_lbl.config(text="● listening", foreground="#0a0")
            self._set_enabled(False)
            self.status_var.set(f"Listening → {self.settings.resolved_log_dir}")

    def _set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        ro = "readonly" if enabled else "disabled"
        for w in self._toggle_widgets:
            try:
                w.config(state=ro if isinstance(w, ttk.Combobox) else state)
            except tk.TclError:
                pass

    # ---------------- live transcript ----------------
    def _poll_entries(self):
        while not self._entry_q.empty():
            self._append_entry(self._entry_q.get())
        self.root.after(200, self._poll_entries)

    def _append_entry(self, e: dict):
        try:
            t = datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone()
            stamp = t.strftime("%H:%M:%S")
        except Exception:
            stamp = "--:--:--"
        self.text.config(state="normal")
        self.text.insert("end", f"[{stamp}] ", ("err" if e.get("error") else "time",))
        self.text.insert("end", (e.get("text") or "(no text)") + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def _on_close(self):
        if self.controller.is_running():
            self.controller.stop()
        self._apply_widgets_to_settings()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
