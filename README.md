# YTDownloader

YouTube downloader with a desktop UI, optional CLI mode, and a Windows installer.

## Features

- Scan a video or playlist before downloading
- Pick the exact video or audio format
- Download playlists with common playlist-safe formats
- Use optional browser cookies when YouTube requires login
- Bundle FFmpeg in the Windows build for merged video+audio downloads

## Windows Install

Use the installer:

```powershell
dist\installer\YTDownloader-Setup.exe
```

Notes:

- Python is not required on the target machine
- Windows may show SmartScreen for an unsigned installer

## Portable Build

Run the bundled app directly:

```powershell
dist\YTDownloader\YTDownloader.exe
```

Keep the full `dist\YTDownloader\` folder together.

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

Choose a save folder:

```powershell
python app.py --cli --output-dir "D:\Videos" "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Build

Packaging flow:

`Python app -> PyInstaller --onedir -> Inno Setup installer`

Build everything:

```powershell
.\build_installer.ps1
```

Outputs:

- `dist\YTDownloader\`
- `dist\installer\YTDownloader-Setup.exe`

## Cookies

For public videos, cookies are usually not needed.

If YouTube requires login, the app falls back in this order:

- `chrome`
- `edge`
- `brave`
