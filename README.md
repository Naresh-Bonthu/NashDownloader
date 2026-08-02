# NashDownloader
Batch YouTube &amp; Instagram video downloader
# Nash Downloader

Minimal desktop app for batch-downloading YouTube & Instagram videos at the
highest available quality, built on `yt-dlp`.

## Setup (one time)

1. Install Python 3.9+ (you already have this).
2. Install dependencies:
   ```
   pip install yt-dlp
   ```
3. Install **ffmpeg** (required to merge best video + best audio into one file):
   - Windows: `winget install ffmpeg` (or download from ffmpeg.org and add to PATH)
   - Mac: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`

## Run

```
python video_downloader.py
```

## How to use

1. Paste one or more YouTube/Instagram links into the box — one per line.
2. Pick (or leave default) the output folder.
3. Optionally check "Audio only (mp3)" for audio-only downloads.
4. Click **Download All**. Progress and per-link status show live in the log.
5. You can hit **Cancel** — it finishes the current file, then stops.

## Notes on quality

- Default mode requests `bestvideo + bestaudio`, merged to mp4 — this pulls
  the highest resolution/bitrate stream YouTube or Instagram serves, not
  just the default "best" combined format (which is often capped lower).
- Files are named `Uploader - Title.ext` in your output folder.
- Instagram private/restricted posts may need login — see yt-dlp docs for
  `--cookies-from-browser` if you hit that (ask me and I'll wire it in).

## Downloading only a portion (clip)

Check "Download only a portion", enter a start and end time in `mm:ss`
(e.g. `0:22` to `1:00`), and it'll pull just that section instead of the
whole video. This applies to every link in the box, so if you're batching,
use full-video mode for mixed downloads and clip mode when all your links
need the same trim.

## Keeping it updated

YouTube/Instagram change their site frequently. If downloads start failing,
update yt-dlp:
```
pip install -U yt-dlp
```

---

## Turning this into a single .exe for a non-technical friend

A Windows `.exe` has to be built **on Windows** — it can't be cross-compiled
from another OS. You have two options:

### Option A — GitHub Actions builds it for you (no Windows needed)

1. Create a new (can be private) GitHub repo and push these files to it,
   keeping the folder structure as-is:
   - `video_downloader.py`
   - `.github/workflows/build-windows.yml`
2. Push to the `main` branch (or go to the repo's **Actions** tab and run
   the "Build Windows EXE" workflow manually).
3. It automatically downloads ffmpeg, builds the exe, and bundles ffmpeg
   inside it. Takes ~3-5 minutes.
4. Go to **Actions → (your run) → Artifacts**, download
   `NashDownloader-windows`, unzip it — that's your `NashDownloader.exe`.
5. Send that one file to your friend. They double-click it — no install,
   no Python, no ffmpeg setup needed on their end.

### Option B — Build it yourself on a Windows PC

1. On a Windows machine, put `video_downloader.py` and `build_windows_exe.bat`
   in the same folder.
2. Download an ffmpeg Windows static build (e.g. from gyan.dev — the
   "essentials" build), extract it, and copy `ffmpeg.exe` + `ffprobe.exe`
   into a subfolder named `ffmpeg_bin` next to the script.
3. Double-click `build_windows_exe.bat`. It installs PyInstaller, builds,
   and bundles ffmpeg in.
4. Find `NashDownloader.exe` in the `dist` folder — send that to your friend.

Either way, the result is a single `.exe` — no `.msi` installer needed,
and nothing extra for your friend to set up.
