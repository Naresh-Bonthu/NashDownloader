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


def resource_path(relative_path):
    """Resolve a path that works both when run as a script and when
    bundled into a single-file PyInstaller exe."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def find_ffmpeg():
    """Look for a bundled ffmpeg first, fall back to system PATH."""
    bundled = resource_path(os.path.join("ffmpeg_bin", "ffmpeg.exe"))
    if os.path.exists(bundled):
        return os.path.dirname(bundled)
    return None  # yt-dlp will use system PATH


def parse_time_to_seconds(value):
    """Accepts 'ss', 'mm:ss', or 'h:mm:ss'. Returns float seconds or None."""
    value = value.strip()
    if not value:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    parts = value.split(":")
    if not all(re.fullmatch(r"\d+", p) for p in parts):
        raise ValueError(f"Invalid time: {value}")
    parts = [int(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return h * 3600 + m * 60 + s


class DownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Nash Downloader")
        self.root.geometry("800x700")
        self.root.configure(bg="#f5f5f7")
        self.root.minsize(700, 600)

        self.log_queue = queue.Queue()
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT)
        self.is_running = False
        self.cancel_flag = False
        self.video_duration = 0  # For slider

        self._build_ui()
        self._poll_log_queue()

    # ---------- UI ----------

    def _build_ui(self):
        FG = "#1d1d1f"
        BG = "#f5f5f7"
        PANEL = "#ffffff"
        PANEL_BORDER = "#e5e5e7"
        ACCENT = "#0071e3"
        ACCENT_HOVER = "#0077ed"
        TEXT_SECONDARY = "#86868b"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#e5e5e7", background=ACCENT, thickness=6)

        # Title
        title = tk.Label(self.root, text="Nash Downloader", font=("SF Pro Display", 28, "bold"),
                          fg=FG, bg=BG)
        title.pack(pady=(24, 4))

        subtitle = tk.Label(self.root, text="Download videos at the highest quality",
                             font=("SF Pro Text", 13), fg=TEXT_SECONDARY, bg=BG)
        subtitle.pack(pady=(0, 20))

        # URL input card
        url_frame = tk.Frame(self.root, bg=BG)
        url_frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        tk.Label(url_frame, text="Links", font=("SF Pro Text", 11, "bold"),
                 fg=FG, bg=BG, anchor="w").pack(fill="x", pady=(0, 6))

        # Text box in card
        box_frame = tk.Frame(url_frame, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        box_frame.pack(fill="both", expand=True)

        self.url_box = tk.Text(box_frame, height=8, bg=PANEL, fg=FG, insertbackground=FG,
                                relief="flat", font=("Menlo", 10), wrap="none", padx=12, pady=10)
        self.url_box.pack(fill="both", expand=True)
        
        # Hover effect
        self.url_box.bind("<Enter>", lambda e: box_frame.config(highlightbackground="#d2d2d7"))
        self.url_box.bind("<Leave>", lambda e: box_frame.config(highlightbackground=PANEL_BORDER))

        # Output folder
        out_frame = tk.Frame(self.root, bg=BG)
        out_frame.pack(fill="x", padx=20, pady=(0, 12))

        tk.Label(out_frame, text="Save to", font=("SF Pro Text", 11, "bold"),
                 fg=FG, bg=BG).pack(anchor="w", pady=(0, 6))

        out_inner = tk.Frame(out_frame, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        out_inner.pack(fill="x")

        out_entry = tk.Entry(out_inner, textvariable=self.output_dir, bg=PANEL, fg=FG,
                              insertbackground=FG, relief="flat", font=("SF Pro Text", 10))
        out_entry.pack(side="left", fill="both", expand=True, padx=12, pady=9)

        browse_btn = tk.Button(out_inner, text="Browse", command=self._browse_folder, bg=PANEL, fg=ACCENT,
                                relief="flat", font=("SF Pro Text", 10, "bold"), cursor="hand2")
        browse_btn.pack(side="left", padx=8)
        
        # Button hover
        browse_btn.bind("<Enter>", lambda e: browse_btn.config(fg=ACCENT_HOVER))
        browse_btn.bind("<Leave>", lambda e: browse_btn.config(fg=ACCENT))

        # Options row
        opt_frame = tk.Frame(self.root, bg=BG)
        opt_frame.pack(fill="x", padx=20, pady=(0, 12))

        self.audio_only = tk.BooleanVar(value=False)
        audio_check = tk.Checkbutton(opt_frame, text="Audio only (mp3)", variable=self.audio_only,
                                      fg=FG, bg=BG, selectcolor=BG, activebackground=BG,
                                      activeforeground=FG, font=("SF Pro Text", 10), cursor="hand2")
        audio_check.pack(side="left")

        # Clip section with slider
        clip_frame = tk.Frame(self.root, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        clip_frame.pack(fill="x", padx=20, pady=(0, 12))

        self.clip_enabled = tk.BooleanVar(value=False)
        clip_check = tk.Checkbutton(clip_frame, text="Download a portion", variable=self.clip_enabled, 
                                     fg=FG, bg=PANEL, selectcolor=PANEL, activebackground=PANEL,
                                     activeforeground=FG, font=("SF Pro Text", 10, "bold"), cursor="hand2",
                                     command=self._toggle_clip_fields)
        clip_check.pack(anchor="w", padx=12, pady=(10, 8))

        # Slider container (hidden by default)
        self.slider_container = tk.Frame(clip_frame, bg=PANEL)
        self.slider_container.pack(fill="x", padx=12, pady=(0, 10))

        # Start time slider
        start_label = tk.Label(self.slider_container, text="Start", font=("SF Pro Text", 10), fg=TEXT_SECONDARY, bg=PANEL)
        start_label.pack(anchor="w")
        self.clip_start_slider = tk.Scale(self.slider_container, from_=0, to=3600, orient="horizontal",
                                           bg=PANEL, fg=FG, highlightthickness=0, troughcolor="#e5e5e7",
                                           activebackground=ACCENT, state="disabled", command=self._update_start_label)
        self.clip_start_slider.pack(fill="x", pady=(2, 8))
        self.start_time_label = tk.Label(self.slider_container, text="0:00", font=("SF Pro Text", 10), fg=FG, bg=PANEL)
        self.start_time_label.pack(anchor="w")

        # End time slider
        end_label = tk.Label(self.slider_container, text="End", font=("SF Pro Text", 10), fg=TEXT_SECONDARY, bg=PANEL)
        end_label.pack(anchor="w", pady=(12, 0))
        self.clip_end_slider = tk.Scale(self.slider_container, from_=0, to=3600, orient="horizontal",
                                         bg=PANEL, fg=FG, highlightthickness=0, troughcolor="#e5e5e7",
                                         activebackground=ACCENT, state="disabled", command=self._update_end_label)
        self.clip_end_slider.set(60)
        self.clip_end_slider.pack(fill="x", pady=(2, 8))
        self.end_time_label = tk.Label(self.slider_container, text="1:00", font=("SF Pro Text", 10), fg=FG, bg=PANEL)
        self.end_time_label.pack(anchor="w")

        self.slider_container.pack_forget()  # Hide by default

        # Buttons
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(fill="x", padx=20, pady=(12, 8))

        self.start_btn = tk.Button(btn_frame, text="Download All", command=self._start_download,
                                    bg=ACCENT, fg="white", font=("SF Pro Text", 11, "bold"),
                                    relief="flat", padx=24, pady=8, cursor="hand2",
                                    activebackground=ACCENT_HOVER)
        self.start_btn.pack(side="left")
        self.start_btn.bind("<Enter>", lambda e: self.start_btn.config(bg=ACCENT_HOVER))
        self.start_btn.bind("<Leave>", lambda e: self.start_btn.config(bg=ACCENT))

        self.cancel_btn = tk.Button(btn_frame, text="Cancel", command=self._cancel_download,
                                     bg=PANEL, fg=ACCENT, relief="flat", padx=24, pady=8,
                                     state="disabled", font=("SF Pro Text", 11, "bold"), cursor="hand2")
        self.cancel_btn.pack(side="left", padx=12)
        self.cancel_btn.bind("<Enter>", lambda e: self.cancel_btn.config(bg="#f2f2f7") if self.cancel_btn.cget("state") == "normal" else None)
        self.cancel_btn.bind("<Leave>", lambda e: self.cancel_btn.config(bg=PANEL) if self.cancel_btn.cget("state") == "normal" else None)

        # Progress
        self.progress = ttk.Progressbar(self.root, style="TProgressbar", mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=(8, 4))

        self.status_label = tk.Label(self.root, text="Ready", font=("SF Pro Text", 10),
                                      fg=TEXT_SECONDARY, bg=BG, anchor="w")
        self.status_label.pack(fill="x", padx=20)

        # Log
        log_label = tk.Label(self.root, text="Activity", font=("SF Pro Text", 11, "bold"),
                              fg=FG, bg=BG, anchor="w")
        log_label.pack(fill="x", padx=20, pady=(12, 6))

        log_frame = tk.Frame(self.root, bg=PANEL, highlightthickness=1, highlightbackground=PANEL_BORDER)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self.log_box = tk.Text(log_frame, height=6, bg=PANEL, fg="#555555", relief="flat",
                                font=("Menlo", 9), state="disabled", padx=10, pady=10)
        self.log_box.pack(fill="both", expand=True)

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)

    def _toggle_clip_fields(self):
        if self.clip_enabled.get():
            self.slider_container.pack(fill="x", padx=12, pady=(0, 10))
            self.clip_start_slider.config(state="normal")
            self.clip_end_slider.config(state="normal")
        else:
            self.slider_container.pack_forget()
            self.clip_start_slider.config(state="disabled")
            self.clip_end_slider.config(state="disabled")

    def _update_start_label(self, val):
        seconds = int(float(val))
        mins, secs = divmod(seconds, 60)
        self.start_time_label.config(text=f"{mins}:{secs:02d}")
        # Ensure start < end
        if seconds >= self.clip_end_slider.get():
            self.clip_end_slider.set(seconds + 10)

    def _update_end_label(self, val):
        seconds = int(float(val))
        mins, secs = divmod(seconds, 60)
        self.end_time_label.config(text=f"{mins}:{secs:02d}")

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
        if self.clip_enabled.get():
            start = int(float(self.clip_start_slider.get()))
            end = int(float(self.clip_end_slider.get()))
            if end <= start:
                messagebox.showerror("Invalid clip range", "End time must be after start time.")
                return
            clip_range = (start, end)

        self.is_running = True
        self.cancel_flag = False
        self.start_btn.config(state="disabled")
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

        if self.audio_only.get():
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",  # best
                }],
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [self._progress_hook],
            }
        else:
            ydl_opts = {
                # best video + best audio, merged; falls back gracefully
                "format": "bestvideo*+bestaudio/best",
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
                    self.start_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)


def main():
    root = tk.Tk()
    app = DownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
