#!/usr/bin/env python3
"""
Nash Downloader — minimal batch video downloader for YouTube & Instagram.
Built on yt-dlp. Highest available quality, multiple links at once.

Requirements:
    pip install yt-dlp
    ffmpeg installed and on PATH (for merging video+audio into one file)

Run:
    python video_downloader.py
"""

import os
import re
import sys
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import yt_dlp
    from yt_dlp.utils import download_range_func
except ImportError:
    print("Missing dependency. Run: pip install yt-dlp")
    sys.exit(1)


DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Downloads", "NashDownloader")

# ---------- Palette ----------
BG = "#f5f5f7"
CARD = "#ffffff"
BORDER = "#e5e5ea"
FG = "#1d1d1f"
SECONDARY = "#86868b"
ACCENT = "#0a5cff"
ACCENT_HOVER = "#0e4fd6"
GREEN = "#28a745"
RED = "#e0433f"


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def find_ffmpeg():
    bundled = resource_path(os.path.join("ffmpeg_bin", "ffmpeg.exe"))
    if os.path.exists(bundled):
        return os.path.dirname(bundled)
    return None


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------- Custom widgets ----------

class Toggle(tk.Canvas):
    """A simple iOS-style toggle switch."""

    def __init__(self, parent, command=None, initial=False, **kwargs):
        super().__init__(parent, width=44, height=24, bg=parent["bg"],
                          highlightthickness=0, cursor="hand2", **kwargs)
        self.command = command
        self.state = initial
        self.bind("<Button-1>", self._flip)
        self._draw()

    def _draw(self):
        self.delete("all")
        color = ACCENT if self.state else "#d1d1d6"
        self.create_oval(2, 2, 22, 22, fill=color, outline=color)
        self.create_rectangle(12, 2, 32, 22, fill=color, outline=color)
        self.create_oval(22, 2, 42, 22, fill=color, outline=color)
        knob_x = 32 if self.state else 12
        self.create_oval(knob_x - 9, 3, knob_x + 9, 21, fill="white", outline="#d1d1d6")

    def _flip(self, _event=None):
        self.state = not self.state
        self._draw()
        if self.command:
            self.command(self.state)

    def get(self):
        return self.state

    def set(self, value):
        self.state = bool(value)
        self._draw()


class RangeSlider(tk.Canvas):
    """A dual-handle range slider (start/end) on a track, like a video trimmer."""

    def __init__(self, parent, minimum=0, maximum=100, on_change=None, **kwargs):
        super().__init__(parent, height=32, bg=parent["bg"], highlightthickness=0, **kwargs)
        self.minimum = minimum
        self.maximum = max(maximum, minimum + 1)
        self.start_val = minimum
        self.end_val = self.maximum
        self.on_change = on_change
        self._dragging = None
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_dragging", None))

    def set_range(self, minimum, maximum):
        self.minimum = minimum
        self.maximum = max(maximum, minimum + 1)
        self.start_val = minimum
        self.end_val = self.maximum
        self._redraw()

    def set_values(self, start, end):
        self.start_val = max(self.minimum, min(start, self.maximum))
        self.end_val = max(self.minimum, min(end, self.maximum))
        self._redraw()

    def _val_to_x(self, val):
        w = max(self.winfo_width(), 20) - 20
        span = self.maximum - self.minimum or 1
        return 10 + (val - self.minimum) / span * w

    def _x_to_val(self, x):
        w = max(self.winfo_width(), 20) - 20
        span = self.maximum - self.minimum or 1
        val = self.minimum + (x - 10) / w * span
        return max(self.minimum, min(val, self.maximum))

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width() or 400
        y = 16
        self.create_line(10, y, w - 10, y, fill="#d1d1d6", width=4, capstyle="round")
        x1, x2 = self._val_to_x(self.start_val), self._val_to_x(self.end_val)
        self.create_line(x1, y, x2, y, fill=ACCENT, width=4, capstyle="round")
        for x in (x1, x2):
            self.create_oval(x - 8, y - 8, x + 8, y + 8, fill="white", outline=ACCENT, width=2)

    def _on_click(self, event):
        x1, x2 = self._val_to_x(self.start_val), self._val_to_x(self.end_val)
        self._dragging = "start" if abs(event.x - x1) < abs(event.x - x2) else "end"
        self._on_drag(event)

    def _on_drag(self, event):
        if not self._dragging:
            return
        val = self._x_to_val(event.x)
        if self._dragging == "start":
            self.start_val = min(val, self.end_val - 1)
        else:
            self.end_val = max(val, self.start_val + 1)
        self._redraw()
        if self.on_change:
            self.on_change(self.start_val, self.end_val)


class HoverButton(tk.Button):
    """Button with a hover-color transition."""

    def __init__(self, parent, bg_normal, bg_hover, **kwargs):
        super().__init__(parent, bg=bg_normal, relief="flat", cursor="hand2", **kwargs)
        self.bg_normal = bg_normal
        self.bg_hover = bg_hover
        self.bind("<Enter>", lambda e: self.config(bg=self.bg_hover) if self["state"] != "disabled" else None)
        self.bind("<Leave>", lambda e: self.config(bg=self.bg_normal) if self["state"] != "disabled" else None)


# ---------- Main App ----------

class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nash Downloader")
        self.root.geometry("880x760")
        self.root.configure(bg=BG)
        self.root.minsize(760, 640)

        self.log_queue = queue.Queue()
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT)
        self.is_running = False
        self.cancel_flag = False
        self.video_duration = 300  # default 5 min until we know real duration
        self.audio_mode = False

        self._build_ui()
        self._poll_log_queue()

    # ---------- UI ----------

    def _card(self, parent, **pack_kwargs):
        card = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x", padx=20, pady=(0, 14), **pack_kwargs)
        return card

    def _section_header(self, parent, number, text):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=16, pady=(14, 10))
        badge = tk.Canvas(row, width=22, height=22, bg=CARD, highlightthickness=0)
        badge.create_oval(1, 1, 21, 21, fill=ACCENT, outline=ACCENT)
        badge.create_text(11, 11, text=str(number), fill="white", font=("SF Pro Text", 10, "bold"))
        badge.pack(side="left", padx=(0, 8))
        tk.Label(row, text=text, font=("SF Pro Text", 13, "bold"), fg=FG, bg=CARD).pack(side="left")
        return row

    def _build_ui(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=20, pady=(20, 16))

        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left")
        tk.Label(title_box, text="Nash Downloader", font=("SF Pro Display", 22, "bold"),
                 fg=FG, bg=BG).pack(anchor="w")
        tk.Label(title_box, text="Download videos effortlessly", font=("SF Pro Text", 11),
                 fg=SECONDARY, bg=BG).pack(anchor="w")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        # ---- Section 1: Video URL(s) ----
        card1 = self._card(body)
        self._section_header(card1, 1, "Video URLs")

        url_row = tk.Frame(card1, bg=CARD)
        url_row.pack(fill="x", padx=16, pady=(0, 6))

        url_box_frame = tk.Frame(url_row, bg="#fafafa", highlightthickness=1, highlightbackground=BORDER)
        url_box_frame.pack(side="left", fill="both", expand=True)
        self.url_box = tk.Text(url_box_frame, height=4, bg="#fafafa", fg=FG, insertbackground=FG,
                                relief="flat", font=("Menlo", 10), wrap="none", padx=10, pady=8)
        self.url_box.pack(fill="both", expand=True)

        paste_btn = HoverButton(url_row, "#ffffff", "#f2f2f7", text="📋 Paste",
                                 fg=ACCENT, font=("SF Pro Text", 10, "bold"),
                                 highlightthickness=1, highlightbackground=BORDER,
                                 command=self._paste_clipboard, padx=12, pady=6)
        paste_btn.pack(side="left", padx=(8, 0), anchor="n")

        tk.Label(card1, text="One link per line — batch multiple downloads at once.",
                 font=("SF Pro Text", 9), fg=SECONDARY, bg=CARD).pack(anchor="w", padx=16, pady=(0, 14))

        # ---- Section 2: Download options ----
        card2 = self._card(body)
        self._section_header(card2, 2, "Download Options")

        opts_row = tk.Frame(card2, bg=CARD)
        opts_row.pack(fill="x", padx=16, pady=(0, 12))

        fmt_box = tk.Frame(opts_row, bg=CARD)
        fmt_box.pack(side="left")
        tk.Label(fmt_box, text="Format", font=("SF Pro Text", 9), fg=SECONDARY, bg=CARD).pack(anchor="w")
        seg = tk.Frame(fmt_box, bg="#f2f2f7", highlightthickness=1, highlightbackground=BORDER)
        seg.pack(pady=(4, 0))
        self.video_seg_btn = tk.Button(seg, text="🎬 Video", relief="flat", cursor="hand2",
                                        font=("SF Pro Text", 10, "bold"), padx=14, pady=6,
                                        command=lambda: self._set_format("video"))
        self.audio_seg_btn = tk.Button(seg, text="🎵 Audio", relief="flat", cursor="hand2",
                                        font=("SF Pro Text", 10, "bold"), padx=14, pady=6,
                                        command=lambda: self._set_format("audio"))
        self.video_seg_btn.pack(side="left")
        self.audio_seg_btn.pack(side="left")

        qual_box = tk.Frame(opts_row, bg=CARD)
        qual_box.pack(side="left", padx=(24, 0))
        tk.Label(qual_box, text="Quality", font=("SF Pro Text", 9), fg=SECONDARY, bg=CARD).pack(anchor="w")
        self.quality_var = tk.StringVar(value="Best available")
        quality_menu = ttk.Combobox(qual_box, textvariable=self.quality_var, state="readonly",
                                     values=["Best available", "1080p", "720p", "480p", "360p"],
                                     width=16, font=("SF Pro Text", 10))
        quality_menu.pack(pady=(4, 0))

        portion_box = tk.Frame(opts_row, bg=CARD)
        portion_box.pack(side="right")
        tk.Label(portion_box, text="Download portion", font=("SF Pro Text", 10), fg=FG, bg=CARD).pack(side="left", padx=(0, 8))
        self.portion_toggle = Toggle(portion_box, command=self._on_portion_toggle)
        self.portion_toggle.pack(side="left")

        self.slider_frame = tk.Frame(card2, bg=CARD)

        slider_row = tk.Frame(self.slider_frame, bg=CARD)
        slider_row.pack(fill="x", padx=16, pady=(4, 4))

        self.start_display = tk.Label(slider_row, text="0:00", font=("SF Pro Text", 10, "bold"),
                                       fg=FG, bg="#fafafa", padx=10, pady=6,
                                       highlightthickness=1, highlightbackground=BORDER)
        self.start_display.pack(side="left")

        self.range_slider = RangeSlider(slider_row, minimum=0, maximum=self.video_duration,
                                         on_change=self._on_slider_change)
        self.range_slider.pack(side="left", fill="x", expand=True, padx=10)

        self.end_display = tk.Label(slider_row, text=fmt_time(self.video_duration), font=("SF Pro Text", 10, "bold"),
                                     fg=FG, bg="#fafafa", padx=10, pady=6,
                                     highlightthickness=1, highlightbackground=BORDER)
        self.end_display.pack(side="left")

        self.selected_label = tk.Label(self.slider_frame, text="", font=("SF Pro Text", 9),
                                        fg=SECONDARY, bg=CARD)
        self.selected_label.pack(pady=(2, 14))

        self._set_format("video")

        # ---- Section 3: Save location ----
        card3 = self._card(body)
        self._section_header(card3, 3, "Save Location")

        save_row = tk.Frame(card3, bg=CARD)
        save_row.pack(fill="x", padx=16, pady=(0, 14))

        folder_icon = tk.Label(save_row, text="📁", font=("SF Pro Text", 16), bg=CARD)
        folder_icon.pack(side="left", padx=(0, 10))

        path_box = tk.Frame(save_row, bg=CARD)
        path_box.pack(side="left", fill="x", expand=True)
        self.path_label = tk.Label(path_box, text=os.path.basename(self.output_dir.get()) or "Downloads",
                                    font=("SF Pro Text", 11, "bold"), fg=FG, bg=CARD, anchor="w")
        self.path_label.pack(fill="x", anchor="w")
        self.path_sub_label = tk.Label(path_box, text=self.output_dir.get(),
                                        font=("SF Pro Text", 9), fg=SECONDARY, bg=CARD, anchor="w")
        self.path_sub_label.pack(fill="x", anchor="w")

        change_btn = HoverButton(save_row, "#ffffff", "#f2f2f7", text="Change", fg=FG,
                                  font=("SF Pro Text", 10, "bold"), highlightthickness=1,
                                  highlightbackground=BORDER, command=self._browse_folder,
                                  padx=14, pady=6)
        change_btn.pack(side="right")

        # ---- Download button ----
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(4, 6))

        self.start_btn = HoverButton(btn_row, ACCENT, ACCENT_HOVER, text="⬇  Download",
                                      fg="white", font=("SF Pro Text", 12, "bold"),
                                      command=self._start_download, pady=12)
        self.start_btn.pack(fill="x")

        self.cancel_btn = HoverButton(btn_row, "#ffffff", "#f2f2f7", text="Cancel",
                                       fg=RED, font=("SF Pro Text", 10, "bold"),
                                       highlightthickness=1, highlightbackground=BORDER,
                                       command=self._cancel_download, state="disabled")

        tk.Label(btn_row, text="🛡 Safe  ·  ⚡ Fast  ·  ✨ High Quality", font=("SF Pro Text", 9),
                 fg=SECONDARY, bg=BG).pack(pady=(8, 0))

        # ---- Progress ----
        prog_frame = tk.Frame(self.root, bg=BG)
        prog_frame.pack(fill="x", padx=20, pady=(4, 4))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#e5e5ea", background=ACCENT, thickness=6)
        self.progress = ttk.Progressbar(prog_frame, style="TProgressbar", mode="determinate")
        self.progress.pack(fill="x")

        self.status_label = tk.Label(self.root, text="Ready", font=("SF Pro Text", 10),
                                      fg=SECONDARY, bg=BG, anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(2, 8))

        # ---- Log ----
        log_frame = tk.Frame(self.root, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.log_box = tk.Text(log_frame, height=6, bg=CARD, fg="#555555", relief="flat",
                                font=("Menlo", 9), state="disabled", padx=10, pady=8)
        self.log_box.pack(fill="both", expand=True)

    # ---------- Segmented control / toggle handlers ----------

    def _set_format(self, mode):
        self.audio_mode = (mode == "audio")
        if self.audio_mode:
            self.audio_seg_btn.config(bg=ACCENT, fg="white")
            self.video_seg_btn.config(bg="#f2f2f7", fg=FG)
        else:
            self.video_seg_btn.config(bg=ACCENT, fg="white")
            self.audio_seg_btn.config(bg="#f2f2f7", fg=FG)

    def _on_portion_toggle(self, state):
        if state:
            self.slider_frame.pack(fill="x")
            self._update_selected_label()
        else:
            self.slider_frame.pack_forget()

    def _on_slider_change(self, start, end):
        self.start_display.config(text=fmt_time(start))
        self.end_display.config(text=fmt_time(end))
        self._update_selected_label()

    def _update_selected_label(self):
        start, end = self.range_slider.start_val, self.range_slider.end_val
        dur = int(end - start)
        self.selected_label.config(text=f"Selected: {fmt_time(dur)} ({dur} seconds)")

    def _paste_clipboard(self):
        try:
            text = self.root.clipboard_get()
            self.url_box.insert("insert", text)
        except tk.TclError:
            pass

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)
            self.path_label.config(text=os.path.basename(folder) or folder)
            self.path_sub_label.config(text=folder)

    # ---------- Download logic ----------

    def _start_download(self):
        if self.is_running:
            return

        urls_raw = self.url_box.get("1.0", "end").strip()
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]

        if not urls:
            messagebox.showwarning("No links", "Paste at least one YouTube or Instagram link.")
            return

        out_dir = self.output_dir.get().strip() or DEFAULT_OUTPUT
        os.makedirs(out_dir, exist_ok=True)

        clip_range = None
        if self.portion_toggle.get():
            start, end = int(self.range_slider.start_val), int(self.range_slider.end_val)
            if end <= start:
                messagebox.showerror("Invalid clip range", "End time must be after start time.")
                return
            clip_range = (start, end)

        self.is_running = True
        self.cancel_flag = False
        self.start_btn.config(state="disabled", text="Downloading…")
        self.cancel_btn.pack(fill="x", pady=(8, 0))
        self.cancel_btn.config(state="normal")
        self.progress["value"] = 0
        self.progress["maximum"] = len(urls)
        self._log_clear()

        thread = threading.Thread(target=self._run_batch, args=(urls, out_dir, clip_range), daemon=True)
        thread.start()

    def _cancel_download(self):
        self.cancel_flag = True
        self.log_queue.put(("status", "Cancelling after current file..."))

    def _run_batch(self, urls, out_dir, clip_range=None):
        total = len(urls)
        succeeded, failed = 0, []

        for i, url in enumerate(urls, start=1):
            if self.cancel_flag:
                self.log_queue.put(("log", f"Cancelled before: {url}"))
                break

            self.log_queue.put(("status", f"Downloading {i}/{total}: {url}"))
            self.log_queue.put(("log", f"→ Starting: {url}"))

            ok = self._download_one(url, out_dir, clip_range)
            if ok:
                succeeded += 1
                self.log_queue.put(("log", f"✓ Done: {url}"))
            else:
                failed.append(url)
                self.log_queue.put(("log", f"✗ Failed: {url}"))

            self.log_queue.put(("progress", i))

        summary = f"Finished. {succeeded}/{total} succeeded."
        if failed:
            summary += f" {len(failed)} failed."
        self.log_queue.put(("status", summary))
        self.log_queue.put(("done", None))

    def _download_one(self, url, out_dir, clip_range=None):
        outtmpl = os.path.join(out_dir, "%(uploader)s - %(title)s.%(ext)s")
        if clip_range:
            outtmpl = os.path.join(out_dir, "%(uploader)s - %(title)s [clip].%(ext)s")

        quality_map = {
            "Best available": "bestvideo*+bestaudio/best",
            "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
            "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
        }

        if self.audio_mode:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",
                }],
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
            }
        else:
            ydl_opts = {
                "format": quality_map.get(self.quality_var.get(), quality_map["Best available"]),
                "merge_output_format": "mp4",
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
            }

        if clip_range:
            start, end = clip_range
            ydl_opts["download_ranges"] = download_range_func(None, [(start, end)])
            ydl_opts["force_keyframes_at_cuts"] = True

        ffmpeg_dir = find_ffmpeg()
        if ffmpeg_dir:
            ydl_opts["ffmpeg_location"] = ffmpeg_dir

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return True
        except Exception as e:
            self.log_queue.put(("log", f"   Error: {e}"))
            return False

    def _progress_hook(self, d):
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            self.log_queue.put(("status", f"  {pct} at {speed}"))

    # ---------- Log helpers ----------

    def _log_clear(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _log_write(self, text):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._log_write(payload)
                elif kind == "status":
                    self.status_label.config(text=payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self.is_running = False
                    self.start_btn.config(state="normal", text="⬇  Download")
                    self.cancel_btn.pack_forget()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    root = tk.Tk()
    app = DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
