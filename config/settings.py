"""Application default settings."""
from pathlib import Path

DEFAULTS = {
    "output_dir": str(Path.cwd()),
    "use_chrome_cookies": False,
}

__all__ = ["DEFAULTS"]
