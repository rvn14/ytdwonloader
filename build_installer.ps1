Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv-build"
$PythonExe = Join-Path $VenvPath "Scripts\\python.exe"
$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\\Inno Setup 6\\ISCC.exe"),
    "C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe",
    "C:\\Program Files\\Inno Setup 6\\ISCC.exe"
)

Push-Location $ProjectRoot
try {
    if (-not (Test-Path $PythonExe)) {
        python -m venv $VenvPath
    }

    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements.txt pyinstaller

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
