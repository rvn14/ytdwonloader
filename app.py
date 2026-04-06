"""Application launcher.

Runs the Tkinter UI by default. Pass `--cli` to keep the original terminal flow.
"""
from __future__ import annotations

import sys

from core import main as cli_main
from ui import main as ui_main


if __name__ == "__main__":
    if "--cli" in sys.argv[1:]:
        sys.argv.remove("--cli")
        raise SystemExit(cli_main())
    raise SystemExit(ui_main())
