# YouTube Downloader

A YouTube downloader with a Tkinter desktop UI and the original CLI workflow.

## Features

- Desktop UI with YouTube-themed styling
- Accepts single video and playlist URLs
- Shows the main video thumbnail when available
- Lists playlist videos with thumbnails
- Prompts for the save folder before starting the download
- Downloads public YouTube videos without browser cookies
- Supports optional browser cookies for logged-in videos
- Cookie fallback order is `chrome`, then `edge`, then `brave`
- Automatically retries with browser cookies when a no-cookie YouTube auth error is detected
- Lists available video and audio formats before downloading
- Scans every playlist item and only offers common playlist-safe formats
- Lets you choose the exact numbered format you want
- Supports choosing the download folder with `--output-dir` in CLI mode
- Supports:
  - video downloads with audio
  - audio-only downloads
- Shows download progress in the UI and terminal
- Saves files to the current folder by default

## Install

1. Make sure Python 3 is installed.
2. Install the dependency:

```bash
pip install -r requirements.txt
```

Or install directly:

```bash
pip install yt-dlp Pillow
```

## Run The Desktop UI

Start the Tkinter app:

```bash
python app.py
```

## Run The Original CLI

The CLI is still available through `--cli`:

```bash
python app.py --cli "https://www.youtube.com/watch?v=VIDEO_ID"
```

Save to a specific folder:

```bash
python app.py --cli --output-dir "D:\\Videos" "https://www.youtube.com/watch?v=VIDEO_ID"
```

If you do not pass `--output-dir`, the CLI asks where to save the file before you choose a format.

## Notes About Cookies

This script does not require browser cookies for normal public videos.

If a no-cookie request fails because YouTube asks for login, the script automatically retries with browser cookies in this order: `chrome`, `edge`, `brave`.

If a video requires your logged-in YouTube session, use browser cookies:

```bash
python app.py --use-browser-cookies "https://www.youtube.com/watch?v=VIDEO_ID"
```

If your YouTube login is in another Chrome profile, run for example:

```bash
python app.py --chrome-profile "Profile 1" "https://www.youtube.com/watch?v=VIDEO_ID"
```

If Chrome cookie extraction fails on Windows:

- make sure you are signed in and recently opened YouTube in Chrome
- fully close Chrome and try again
- run the terminal as the same Windows user who uses Chrome
- do not run the terminal elevated if Chrome is used normally

## Extending Later

Good places to extend the script:

- add command-line flags for output folders
- add audio conversion post-processing
- add playlist support
- add format filtering rules
