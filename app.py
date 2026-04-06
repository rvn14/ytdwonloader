"""App launcher: thin CLI entry that delegates to `core.main()`."""
from core import main


if __name__ == "__main__":
    raise SystemExit(main())
