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
        self.root.geometry("720x560")
        self.root.configure(bg="#1e1e1e")
        self.root.minsize(600, 480)

        self.log_queue = queue.Queue()
        self.output_dir = tk.StringVar(value=DEFAULT_OUTPUT)
        self.is_running = False
        self.cancel_flag = False

        self._build_ui()
        self._poll_log_queue()

    # ---------- UI ----------

    def _build_ui(self):
        FG = "#e8e8e8"
        BG = "#1e1e1e"
        PANEL = "#2a2a2a"
        ACCENT = "#5b8dee"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor=PANEL, background=ACCENT, thickness=14)

        title = tk.Label(self.root, text="Nash Downloader", font=("Segoe UI", 18, "bold"),
                          fg=FG, bg=BG)
        title.pack(pady=(16, 0))

        subtitle = tk.Label(self.root, text="YouTube & Instagram · batch · highest quality",
                             font=("Segoe UI", 10), fg="#9a9a9a", bg=BG)
        subtitle.pack(pady=(0, 12))

        # URL input
        url_frame = tk.Frame(self.root, bg=BG)
        url_frame.pack(fill="both", expand=True, padx=16)

        tk.Label(url_frame, text="Paste links (one per line):", font=("Segoe UI", 10),
                 fg=FG, bg=BG, anchor="w").pack(fill="x")

        self.url_box = tk.Text(url_frame, height=10, bg=PANEL, fg=FG, insertbackground=FG,
                                relief="flat", font=("Consolas", 10), wrap="none")
        self.url_box.pack(fill="both", expand=True, pady=(4, 8))

        # Output folder
        out_frame = tk.Frame(self.root, bg=BG)
        out_frame.pack(fill="x", padx=16, pady=(0, 8))

        tk.Label(out_frame, text="Save to:", font=("Segoe UI", 10), fg=FG, bg=BG).pack(side="left")
        out_entry = tk.Entry(out_frame, textvariable=self.output_dir, bg=PANEL, fg=FG,
                              insertbackground=FG, relief="flat")
        out_entry.pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(out_frame, text="Browse", command=self._browse_folder, bg=PANEL, fg=FG,
                  relief="flat", activebackground=ACCENT).pack(side="left")

        # Options row
        opt_frame = tk.Frame(self.root, bg=BG)
        opt_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.audio_only = tk.BooleanVar(value=False)
        tk.Checkbutton(opt_frame, text="Audio only (mp3)", variable=self.audio_only,
                        fg=FG, bg=BG, selectcolor=PANEL, activebackground=BG,
                        activeforeground=FG).pack(side="left")

        # Clip section
        clip_frame = tk.Frame(self.root, bg=BG)
        clip_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.clip_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(clip_frame, text="Download only a portion (applies to every link above)",
                        variable=self.clip_enabled, fg=FG, bg=BG, selectcolor=PANEL,
                        activebackground=BG, activeforeground=FG,
                        command=self._toggle_clip_fields).pack(side="left")

        tk.Label(clip_frame, text="  from", font=("Segoe UI", 9), fg="#9a9a9a", bg=BG).pack(side="left")
        self.clip_start = tk.Entry(clip_frame, width=8, bg=PANEL, fg=FG, insertbackground=FG,
                                    relief="flat", state="disabled")
        self.clip_start.pack(side="left", padx=4)
        self.clip_start.insert(0, "0:22")

        tk.Label(clip_frame, text="to", font=("Segoe UI", 9), fg="#9a9a9a", bg=BG).pack(side="left")
        self.clip_end = tk.Entry(clip_frame, width=8, bg=PANEL, fg=FG, insertbackground=FG,
                                  relief="flat", state="disabled")
        self.clip_end.pack(side="left", padx=4)
        self.clip_end.insert(0, "1:00")

        tk.Label(clip_frame, text="(mm:ss)", font=("Segoe UI", 8), fg="#666666", bg=BG).pack(side="left")

        # Buttons
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(fill="x", padx=16, pady=(4, 8))

        self.start_btn = tk.Button(btn_frame, text="Download All", command=self._start_download,
                                    bg=ACCENT, fg="white", font=("Segoe UI", 11, "bold"),
                                    relief="flat", padx=16, pady=6)
        self.start_btn.pack(side="left")

        self.cancel_btn = tk.Button(btn_frame, text="Cancel", command=self._cancel_download,
                                     bg=PANEL, fg=FG, relief="flat", padx=16, pady=6,
                                     state="disabled")
        self.cancel_btn.pack(side="left", padx=8)

        # Progress
        self.progress = ttk.Progressbar(self.root, style="TProgressbar", mode="determinate")
        self.progress.pack(fill="x", padx=16, pady=(4, 4))

        self.status_label = tk.Label(self.root, text="Idle", font=("Segoe UI", 9),
                                      fg="#9a9a9a", bg=BG, anchor="w")
        self.status_label.pack(fill="x", padx=16)

        # Log
        log_frame = tk.Frame(self.root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(8, 16))

        self.log_box = tk.Text(log_frame, height=8, bg=PANEL, fg="#9ada9a", relief="flat",
                                font=("Consolas", 9), state="disabled")
        self.log_box.pack(fill="both", expand=True)

    def _browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir.set(folder)

    def _toggle_clip_fields(self):
        state = "normal" if self.clip_enabled.get() else "disabled"
        self.clip_start.config(state=state)
        self.clip_end.config(state=state)

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
            try:
                start = parse_time_to_seconds(self.clip_start.get()) or 0
                end = parse_time_to_seconds(self.clip_end.get())
                if not end or end <= start:
                    raise ValueError("End time must be after start time.")
                clip_range = (start, end)
            except ValueError as e:
                messagebox.showerror("Invalid clip time", str(e))
                return

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
