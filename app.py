#!/usr/bin/env python3
"""
Nash Downloader — PyWebView + Tailwind CSS Edition
100% pixel-perfect match to modern UI design mockups.
Requirements: pip install yt-dlp pywebview
"""

import os
import sys
import threading
import webview
import yt_dlp

DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Downloads", "NashDownloader")

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def find_ffmpeg():
    bundled = resource_path(os.path.join("ffmpeg_bin", "ffmpeg.exe"))
    if os.path.exists(bundled):
        return os.path.dirname(bundled)
    return None

class Api:
    def __init__(self):
        self.window = None

    def select_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            return result[0]
        return None

    def start_download(self, url, audio_mode, quality):
        threading.Thread(target=self._run_download, args=(url, audio_mode, quality), daemon=True).start()

    def _run_download(self, url, audio_mode, quality):
        outtmpl = os.path.join(DEFAULT_OUTPUT, "%(uploader)s - %(title)s.%(ext)s")
        os.makedirs(DEFAULT_OUTPUT, exist_ok=True)

        def hook(d):
            if d['status'] == 'downloading':
                pct = d.get('_percent_str', '0%').strip()
                speed = d.get('_speed_str', '').strip()
                title = d.get('info_dict', {}).get('title', 'Video')
                # Clean up percentage string for JS
                clean_pct = pct.replace('%', '')
                try:
                    self.window.evaluate_js(f"updateProgress('{clean_pct}', '{speed}', '{title}')")
                except:
                    pass

        ydl_opts = {
            'outtmpl': outtmpl,
            'quiet': True,
            'progress_hooks': [hook]
        }

        if audio_mode:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
        else:
            q_map = {
                "Best available": "bestvideo*+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]"
            }
            ydl_opts['format'] = q_map.get(quality, q_map["Best available"])
            ydl_opts['merge_output_format'] = "mp4"

        ffmpeg_dir = find_ffmpeg()
        if ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = ffmpeg_dir

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.window.evaluate_js("downloadComplete(true, 'Success')")
        except Exception as e:
            self.window.evaluate_js(f"downloadComplete(false, '{str(e)}')")

def main():
    api = Api()
    html_path = os.path.abspath(resource_path("index.html"))
    
    window = webview.create_window(
        "Nash Downloader",
        url=f"file://{html_path}",
        width=950,
        height=720,
        resizable=False,
        background_color='#f5f5f7'
    )
    api.window = window
    webview.start()

if __name__ == "__main__":
    main()
