# YTDownloader

A Windows-friendly YouTube downloader with a desktop UI and optional CLI mode.

## What It Does

- Scans a video or playlist before downloading
- Shows title, channel, duration, and thumbnail
- Lets you choose the exact video or audio format
- Supports playlist downloads with common playlist-safe formats
- Supports optional browser cookies when YouTube requires login
- Lets you choose where downloads are saved

## Install

### Windows Installer

Run:

```powershell
YTDownloader-Setup.exe
```

Notes:

- Python is not required on the target machine
- If SmartScreen appears, click `More info` then `Run anyway`

## Run From Source

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start the desktop app:

```powershell
python app.py
```

## CLI Mode

From source:

```powershell
python app.py --cli "https://www.youtube.com/watch?v=VIDEO_ID"
```

From the packaged app:

```powershell
dist\YTDownloader\YTDownloader.exe --cli "https://www.youtube.com/watch?v=VIDEO_ID"
```

Choose an output folder in CLI mode:

```powershell
python app.py --cli --output-dir "D:\Videos" "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Cookie Support

For normal public videos, cookies are usually not needed.

If YouTube requires login, the app can use browser cookies and falls back in this order:

- `chrome`
- `edge`
- `brave`
