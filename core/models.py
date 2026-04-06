"""Module for dataclasses re-exporting from core package root.

The authoritative implementations live in `core.__init__` to keep a single
source-of-truth during this reorganization. This shim makes imports like
`from core.models import DownloadOption` work.
"""
from . import DownloadOption, PlaylistEntry, PlaylistScannedVideo, PlaylistCommonOption

__all__ = [
    "DownloadOption",
    "PlaylistEntry",
    "PlaylistScannedVideo",
    "PlaylistCommonOption",
]
