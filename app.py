#!/usr/bin/env python3
import os
import sys
import json
import threading
import webview
import yt_dlp
from yt_dlp.utils import download_range_func

DEFAULT_OUTPUT = os.path.join(os.path.expanduser("~"), "Downloads", "NashDownloader")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".nashdownloader_config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_config(config):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    except OSError:
        pass

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
            chosen = result[0]
            # Remember this choice so it's still selected next time the app opens
            config = load_config()
            config['save_folder'] = chosen
            save_config(config)
            return chosen
        return None

    def get_settings(self):
        """Called on app startup so the UI can show the previously-saved folder."""
        config = load_config()
        return {
            'save_folder': config.get('save_folder') or DEFAULT_OUTPUT
        }

    def _safe_eval(self, js_function_name, *args):
        """Calls a JS function with arguments safely encoded as JSON, so titles/
        error messages containing quotes, backticks, or newlines can't break
        the injected JS or get silently dropped."""
        try:
            encoded_args = ", ".join(json.dumps(a) for a in args)
            self.window.evaluate_js(f"{js_function_name}({encoded_args})")
        except Exception:
            pass

    def get_video_info(self, url):
        """Fetches video title, uploader, thumbnail, and exact duration in seconds"""
        try:
            ydl_opts = {'quiet': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'Unknown Title'),
                    'uploader': info.get('uploader', 'Unknown Channel'),
                    'thumbnail': info.get('thumbnail', ''),
                    'duration': info.get('duration', 0)
                }
        except Exception as e:
            return {'error': str(e)}

    def start_download(self, url, audio_mode, quality, clip_start=None, clip_end=None, save_folder=None):
        threading.Thread(
            target=self._run_download,
            args=(url, audio_mode, quality, clip_start, clip_end, save_folder),
            daemon=True
        ).start()

    def _format_time(self, secs):
        """Convert seconds to MM:SS format for filename."""
        mins = secs // 60
        secs = secs % 60
        return f"{mins:02d}_{secs:02d}"

    def _run_download(self, url, audio_mode, quality, clip_start=None, clip_end=None, save_folder=None):
        # Use the user-selected folder if they picked one via "Change..." in
        # Settings/Save Location; otherwise fall back to the default Downloads path.
        target_dir = save_folder if save_folder and os.path.isdir(save_folder) else DEFAULT_OUTPUT

        # Build filename: include clip range so different clips from the same video don't overwrite
        base_filename = "%(uploader)s - %(title)s"
        if clip_start is not None and clip_end is not None:
            base_filename += f" [{self._format_time(int(clip_start))}-{self._format_time(int(clip_end))}]"
        outtmpl = os.path.join(target_dir, base_filename + ".%(ext)s")
        os.makedirs(target_dir, exist_ok=True)

        def hook(d):
            if d['status'] == 'downloading':
                pct = d.get('_percent_str', '0%').strip().replace('%', '')
                speed = d.get('_speed_str', '').strip()
                title = d.get('info_dict', {}).get('title', 'Video')
                self._safe_eval('updateProgress', pct, speed, title)
            elif d['status'] == 'finished':
                # Download phase finished, now moving to postprocessing (ffmpeg merge/trim/extract)
                # Don't show 100% yet — that's misleading since ffmpeg still needs to run
                self._safe_eval('updateProgress', '95', 'Merging with ffmpeg...', d.get('info_dict', {}).get('title', 'Video'))

        def pp_hook(d):
            # Postprocessor hook: fires during ffmpeg merge/trim/audio-extract steps
            if d.get('status') == 'started':
                self._safe_eval('updateProgress', '98', 'Processing...', 'Finalizing video')
            elif d.get('status') == 'finished':
                # Postprocessing is truly done now
                self._safe_eval('updateProgress', '100', 'Complete!', d.get('info_dict', {}).get('title', 'Video'))

        ydl_opts = {
            'outtmpl': outtmpl,
            'quiet': True,
            'progress_hooks': [hook],
            'postprocessor_hooks': [pp_hook],
        }

        if audio_mode:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
        else:
            q_map = {
                "Best available": "bestvideo+bestaudio/best",
                "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]"
            }
            ydl_opts['format'] = q_map.get(quality, q_map["Best available"])
            ydl_opts['merge_output_format'] = "mp4"

        # --- Custom clip support ---
        # clip_start/clip_end arrive as seconds (float/int) from the UI sliders.
        # download_range_func + force_keyframes_at_cuts tells yt-dlp/ffmpeg to
        # only download+cut the requested section instead of the whole video.
        if clip_start is not None and clip_end is not None:
            try:
                start_s = max(0, float(clip_start))
                end_s = float(clip_end)
                if end_s > start_s:
                    ydl_opts['download_ranges'] = download_range_func(None, [(start_s, end_s)])
                    ydl_opts['force_keyframes_at_cuts'] = True
            except (TypeError, ValueError):
                pass  # bad clip values -> fall back to downloading the full video

        ffmpeg_dir = find_ffmpeg()
        if ffmpeg_dir:
            ydl_opts['ffmpeg_location'] = ffmpeg_dir

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self._safe_eval('downloadComplete', True, 'Success')
        except Exception as e:
            self._safe_eval('downloadComplete', False, str(e))

def main():
    api = Api()
    html_path = os.path.abspath(resource_path("index.html"))
    
    window = webview.create_window(
        "Nash Downloader",
        url=f"file://{html_path}",
        width=950,
        height=720,
        resizable=True,  # <--- Enabled resizing and full-screen functionality
        background_color='#000000'
    )
    window.expose(api.get_video_info)
    window.expose(api.select_folder)
    window.expose(api.start_download)
    window.expose(api.get_settings)
    api.window = window
    webview.start()

if __name__ == "__main__":
    main()
