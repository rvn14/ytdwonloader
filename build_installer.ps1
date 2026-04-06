Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv-build"
$PythonExe = Join-Path $VenvPath "Scripts\\python.exe"
$FfmpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
$FfmpegRoot = Join-Path $ProjectRoot "vendor\\ffmpeg"
$FfmpegBinDir = Join-Path $FfmpegRoot "bin"
$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\\Inno Setup 6\\ISCC.exe"),
    "C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe",
    "C:\\Program Files\\Inno Setup 6\\ISCC.exe"
)

function Ensure-BundledFfmpeg {
    $ffmpegExe = Join-Path $FfmpegBinDir "ffmpeg.exe"
    $ffprobeExe = Join-Path $FfmpegBinDir "ffprobe.exe"

    if ((Test-Path $ffmpegExe) -and (Test-Path $ffprobeExe)) {
        return
    }

    if (Test-Path $FfmpegRoot) {
        Remove-Item $FfmpegRoot -Recurse -Force
    }

    New-Item -ItemType Directory -Path $FfmpegBinDir -Force | Out-Null

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ytdownloader-ffmpeg-" + [guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "ffmpeg.zip"
    $extractRoot = Join-Path $tempRoot "unzipped"

    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        & curl.exe -L --fail --output $zipPath $FfmpegUrl
        Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

        $binSource = Get-ChildItem $extractRoot -Recurse -Directory |
            Where-Object {
                $_.Name -eq "bin" -and
                (Test-Path (Join-Path $_.FullName "ffmpeg.exe")) -and
                (Test-Path (Join-Path $_.FullName "ffprobe.exe"))
            } |
            Select-Object -First 1

        if (-not $binSource) {
            throw "Downloaded FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe."
        }

        Copy-Item (Join-Path $binSource.FullName "ffmpeg.exe") $FfmpegBinDir
        Copy-Item (Join-Path $binSource.FullName "ffprobe.exe") $FfmpegBinDir

        $licenseFiles = Get-ChildItem $extractRoot -Recurse -File |
            Where-Object { $_.Name -match "^(LICENSE|COPYING|README)" }
        foreach ($file in $licenseFiles) {
            Copy-Item $file.FullName (Join-Path $FfmpegRoot $file.Name) -Force
        }
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item $tempRoot -Recurse -Force
        }
    }
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path $PythonExe)) {
        python -m venv $VenvPath
    }

    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements.txt pyinstaller

    Ensure-BundledFfmpeg

    if (Test-Path build) {
        Remove-Item build -Recurse -Force
    }
    if (Test-Path dist\\YTDownloader) {
        Remove-Item dist\\YTDownloader -Recurse -Force
    }
    if (Test-Path dist\\installer) {
        Remove-Item dist\\installer -Recurse -Force
    }

    & $PythonExe -m PyInstaller --noconfirm --clean YTDownloader.spec

    $IsccPath = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $IsccPath) {
        throw "Inno Setup 6 was not found. Install it, then rerun build_installer.ps1."
    }

    & $IsccPath installer.iss
}
finally {
    Pop-Location
}
