"""Application launcher.

Runs the Tkinter UI by default. Pass `--cli` to keep the original terminal flow.
"""
from __future__ import annotations

import sys

from core import main as cli_main
from ui import main as ui_main


def _ensure_frozen_windows_console() -> None:
    """Restore console I/O when the frozen windowed build is used in CLI mode."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if sys.stdin is not None and sys.stdout is not None and sys.stderr is not None:
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        attach_parent = ctypes.c_ulong(-1).value
        if not kernel32.AttachConsole(attach_parent):
            kernel32.AllocConsole()

        if sys.stdin is None:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        if sys.stdout is None:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        if sys.stderr is None:
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        pass


if __name__ == "__main__":
    if "--cli" in sys.argv[1:]:
        _ensure_frozen_windows_console()
        sys.argv.remove("--cli")
        raise SystemExit(cli_main())
    raise SystemExit(ui_main())
