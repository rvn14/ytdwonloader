# YouTube Downloader CLI

A terminal-only YouTube downloader built with Python 3 and `yt-dlp`.

## Features

- Accepts a YouTube video URL from the command line or an interactive prompt
- Prompts for the save folder before starting the download
- Downloads public YouTube videos without browser cookies
- Supports optional browser cookies for logged-in videos
- Cookie fallback order is `chrome`, then `edge`, then `brave`
- Automatically retries with browser cookies when a no-cookie YouTube auth error is detected
- Lists available video and audio formats before downloading
- Lets you choose the exact numbered format you want
- Supports choosing the download folder with `--output-dir`
- Supports:
  - video downloads with audio
  - audio-only downloads
- Shows download progress in the terminal
- Saves files to the current folder by default

## Install

1. Make sure Python 3 is installed.
2. Install the dependency:

```bash
pip install -r requirements.txt
```

Or install directly:

```bash
pip install yt-dlp
```

## Run

Pass the URL directly:

```bash
python app.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Save to a specific folder:

```bash
python app.py --output-dir "D:\\Videos" "https://www.youtube.com/watch?v=VIDEO_ID"
```

Or run without arguments and paste the URL when prompted:

```bash
python app.py
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
