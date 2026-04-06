#!/usr/bin/env python3
"""
Core application logic moved from top-level `app.py`.

This file contains the full implementation previously in `app.py` so other
modules can import behavior from `core` while preserving the original
functionality. The package also exposes `main()` for the CLI launcher.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


COOKIE_SOURCE_NONE = "none"
COOKIE_FALLBACK_BROWSERS = ("chrome", "edge", "brave")
APP_TITLE = "YouTube Downloader CLI"

AUTH_RELATED_ERROR_SNIPPETS = (
    "sign in",
    "confirm your age",
    "use --cookies-from-browser",
    "cookies are required",
    "login required",
    "members-only",
    "private video",
    "this video is private",
)

FFMPEG_RELATIVE_DIR = Path("vendor") / "ffmpeg" / "bin"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


@dataclass
class DownloadOption:
    """Represents one numbered item shown in the terminal menu."""

    number: int
    kind: str
    format_id: str
    format_selector: str
    resolution: str
    extension: str
    fps_text: str
    audio_text: str
    size_text: str
    detail_text: str


@dataclass
class PlaylistEntry:
    """Represents one flat-playlist item."""

    title: str
    url: str
    channel: str = "-"
    duration_text: str = "unknown"
    thumbnail_url: str | None = None


@dataclass
class PlaylistScannedVideo:
    """Formats discovered for one playlist video."""

    title: str
    url: str
    option_by_key: dict[str, DownloadOption]
    available_labels: list[str]
    channel: str = "-"
    duration_text: str = "unknown"
    thumbnail_url: str | None = None


@dataclass
class PlaylistCommonOption:
    """A normalized/common format choice available across the entire playlist."""

    number: int
    key: str
    kind: str
    resolution: str
    extension: str
    fps_text: str
    audio_text: str
    size_text: str
    detail_text: str


class QuietYDLLogger:
    """Keeps yt-dlp output compact while still surfacing warnings and errors."""

    def debug(self, message: str) -> None:
        if message.startswith("[debug]"):
            return

    def warning(self, message: str) -> None:
        return

    def error(self, message: str) -> None:
        return


class ProgressPrinter:
    """Prints a simple single-line progress view that updates in place."""

    def __init__(self, message_callback: Callable[[dict], None] | None = None) -> None:
        self._last_length = 0
        self._last_update = 0.0
        self._message_callback = message_callback

    def download_hook(self, data: dict) -> None:
        status = data.get("status")

        if status == "downloading":
            now = time.monotonic()
            if now - self._last_update < 0.1:
                return
            self._last_update = now

            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            speed = data.get("speed")
            eta = data.get("eta")

            percent_value = None
            if total:
                percent_value = downloaded / total * 100
                percent = f"{percent_value:5.1f}%"
                total_text = human_size(total)
            else:
                percent = "  ?.?%"
                total_text = "unknown"

            line = (
                f"[download] {percent}  "
                f"{human_size(downloaded)}/{total_text}  "
                f"speed {human_size(speed) + '/s' if speed else 'unknown'}  "
                f"ETA {format_eta(eta)}"
            )
            self._emit(
                {
                    "phase": "download",
                    "status": "downloading",
                    "text": line,
                    "percent": percent_value,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                    "speed": speed,
                    "eta": eta,
                }
            )

        elif status == "finished":
            filename = os.path.basename(data.get("filename", "download"))
            self._emit(
                {
                    "phase": "download",
                    "status": "finished",
                    "text": f"[download] Finished: {filename}",
                    "percent": 100.0,
                    "filename": filename,
                },
                newline=True,
            )

    def postprocessor_hook(self, data: dict) -> None:
        status = data.get("status")
        postprocessor = data.get("postprocessor", "post-processing")

        if status in {"started", "processing"}:
            self._emit(
                {
                    "phase": "postprocess",
                    "status": status,
                    "text": f"[postprocess] {postprocessor}...",
                }
            )
        elif status == "finished":
            self._emit(
                {
                    "phase": "postprocess",
                    "status": "finished",
                    "text": "[postprocess] Completed.",
                },
                newline=True,
            )

    def _emit(self, payload: dict, newline: bool = False) -> None:
        if self._message_callback is not None:
            self._message_callback(payload)
            return
        self._print_inline(payload["text"], newline=newline)

    def _print_inline(self, message: str, newline: bool = False) -> None:
        padded = message.ljust(self._last_length)
        end = "\n" if newline else ""
        print(f"\r{padded}", end=end, flush=True)
        self._last_length = len(padded) if not newline else 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive YouTube downloader using yt-dlp."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="YouTube video or playlist URL. If omitted, the script asks for it interactively.",
    )
    parser.add_argument(
        "--chrome-profile",
        default=None,
        help=(
            "Optional Chrome profile name/path for cookies, for example "
            "'Default' or 'Profile 1'."
        ),
    )
    parser.add_argument(
        "--use-chrome-cookies",
        "--use-browser-cookies",
        action="store_true",
        help=(
            "Try browser cookies in this order: chrome, edge, brave. "
            "Useful when the video requires a logged-in session."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Folder to save downloads to. Defaults to the current directory.",
    )
    return parser.parse_args()


def prompt_for_url(initial_url: str | None) -> str:
    if initial_url:
        return initial_url.strip()
    return input("URL: ").strip()


def normalize_and_validate_url(url: str) -> str:
    if not url:
        raise ValueError("No URL was provided.")

    if "://" not in url:
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host not in YOUTUBE_HOSTS:
        raise ValueError("This CLI expects a YouTube video or playlist URL.")

    if host.endswith("youtu.be"):
        if parsed.path.strip("/"):
            return url
        raise ValueError("The shortened YouTube URL is missing a video ID.")

    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    if query.get("list"):
        return url

    if path == "/watch" and query.get("v"):
        return url

    allowed_prefixes = ("/shorts/", "/live/", "/embed/")
    if any(path.startswith(prefix) for prefix in allowed_prefixes):
        return url

    raise ValueError("The URL does not look like a direct YouTube video link.")


def is_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parse_qs(parsed.query).get("list"))


def build_base_options(
    cookie_browser: str | None = None,
    chrome_profile: str | None = None,
    output_dir: str | None = None,
) -> dict:
    options = {
        "noplaylist": True,
        "paths": {"home": output_dir or os.getcwd()},
        "outtmpl": {"default": "%(title)s [%(id)s].%(ext)s"},
        "quiet": True,
        "no_warnings": True,
        "logger": QuietYDLLogger(),
    }

    if shutil.which("node"):
        options["js_runtimes"] = {"node": {}}

    ffmpeg_location = resolve_ffmpeg_location()
    if ffmpeg_location is not None:
        options["ffmpeg_location"] = ffmpeg_location

    if cookie_browser:
        options["cookiesfrombrowser"] = (cookie_browser, chrome_profile, None, None)

    return options


def resolve_ffmpeg_location() -> str | None:
    candidate_dirs = []

    if hasattr(sys, "_MEIPASS"):
        candidate_dirs.append(Path(sys._MEIPASS) / FFMPEG_RELATIVE_DIR)

    candidate_dirs.append(Path(__file__).resolve().parent.parent / FFMPEG_RELATIVE_DIR)

    seen: set[Path] = set()
    for candidate_dir in candidate_dirs:
        resolved_dir = candidate_dir.resolve()
        if resolved_dir in seen:
            continue
        seen.add(resolved_dir)
        if has_ffmpeg_binaries(resolved_dir):
            return str(resolved_dir)

    ffmpeg_path = shutil.which(binary_name("ffmpeg"))
    if ffmpeg_path:
        return str(Path(ffmpeg_path).resolve().parent)

    return None


def has_ffmpeg_binaries(directory: Path) -> bool:
    return (
        directory.is_dir()
        and (directory / binary_name("ffmpeg")).exists()
        and (directory / binary_name("ffprobe")).exists()
    )


def binary_name(command: str) -> str:
    if sys.platform == "win32":
        return f"{command}.exe"
    return command


def build_playlist_options(
    cookie_browser: str | None = None,
    chrome_profile: str | None = None,
    output_dir: str | None = None,
) -> dict:
    options = build_base_options(
        cookie_browser=cookie_browser,
        chrome_profile=chrome_profile,
        output_dir=output_dir,
    )
    options.update(
        {
            "noplaylist": False,
            "extract_flat": "in_playlist",
        }
    )
    return options


def extract_video_info(
    url: str,
    use_chrome_cookies: bool,
    chrome_profile: str | None,
    output_dir: str,
    logger: Callable[[str], None] | None = None,
) -> tuple[dict, str]:
    metadata_options = {"ignore_no_formats_error": True}

    if use_chrome_cookies:
        return extract_video_info_with_cookie_fallback(
            url,
            chrome_profile,
            output_dir,
            logger=logger,
            metadata_options=metadata_options,
        )

    try:
        options = build_base_options(output_dir=output_dir)
        options.update(metadata_options)
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        return unwrap_video_info(info), COOKIE_SOURCE_NONE
    except Exception as exc:
        if is_auth_related_error(exc):
            log_message(
                "Metadata requires a logged-in session. Retrying with browser cookies...",
                logger=logger,
                stream="stderr",
            )
            return extract_video_info_with_cookie_fallback(
                url,
                chrome_profile,
                output_dir,
                initial_error=exc,
                logger=logger,
            )
        raise RuntimeError(build_metadata_error_message(exc)) from exc


def extract_video_info_with_cookie_fallback(
    url: str,
    chrome_profile: str | None,
    output_dir: str,
    initial_error: Exception | None = None,
    logger: Callable[[str], None] | None = None,
    metadata_options: dict | None = None,
) -> tuple[dict, str]:
    cookie_errors: list[tuple[str, Exception]] = []

    for browser in COOKIE_FALLBACK_BROWSERS:
        try:
            options = build_base_options(
                cookie_browser=browser,
                chrome_profile=chrome_profile,
                output_dir=output_dir,
            )
            if metadata_options:
                options.update(metadata_options)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
            return unwrap_video_info(info), browser
        except Exception as exc:
            cookie_errors.append((browser, exc))

    raise RuntimeError(
        build_cookie_error_message(cookie_errors, chrome_profile, initial_error)
    )


def extract_playlist_info(
    url: str,
    use_chrome_cookies: bool,
    chrome_profile: str | None,
    output_dir: str,
    logger: Callable[[str], None] | None = None,
) -> tuple[dict, str]:
    metadata_options = {"ignore_no_formats_error": True}

    if use_chrome_cookies:
        return extract_playlist_info_with_cookie_fallback(
            url,
            chrome_profile,
            output_dir,
            logger=logger,
            metadata_options=metadata_options,
        )

    try:
        options = build_playlist_options(output_dir=output_dir)
        options.update(metadata_options)
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        return info, COOKIE_SOURCE_NONE
    except Exception as exc:
        if is_auth_related_error(exc):
            log_message(
                "Playlist metadata requires a logged-in session. Retrying with browser cookies...",
                logger=logger,
                stream="stderr",
            )
            return extract_playlist_info_with_cookie_fallback(
                url,
                chrome_profile,
                output_dir,
                initial_error=exc,
                logger=logger,
            )
        raise RuntimeError(build_playlist_error_message(exc)) from exc


def extract_playlist_info_with_cookie_fallback(
    url: str,
    chrome_profile: str | None,
    output_dir: str,
    initial_error: Exception | None = None,
    logger: Callable[[str], None] | None = None,
    metadata_options: dict | None = None,
) -> tuple[dict, str]:
    cookie_errors: list[tuple[str, Exception]] = []

    for browser in COOKIE_FALLBACK_BROWSERS:
        try:
            options = build_playlist_options(
                cookie_browser=browser,
                chrome_profile=chrome_profile,
                output_dir=output_dir,
            )
            if metadata_options:
                options.update(metadata_options)
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
            return info, browser
        except Exception as exc:
            cookie_errors.append((browser, exc))

    raise RuntimeError(
        build_cookie_error_message(cookie_errors, chrome_profile, initial_error)
    )


def unwrap_video_info(info: dict) -> dict:
    if info.get("entries"):
        entry = next((item for item in info["entries"] if item), None)
        if entry:
            return entry
    return info


def build_playlist_entries(playlist_info: dict) -> list[PlaylistEntry]:
    entries: list[PlaylistEntry] = []

    for item in playlist_info.get("entries") or []:
        if not item:
            continue

        video_id = item.get("id")
        if not video_id:
            continue

        title = item.get("title") or str(video_id)
        entries.append(
            PlaylistEntry(
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                channel=item.get("channel") or item.get("uploader") or "-",
                duration_text=format_duration(item.get("duration")),
                thumbnail_url=select_thumbnail_url(item),
            )
        )

    return entries


def build_download_options(info: dict) -> tuple[list[DownloadOption], list[DownloadOption]]:
    formats = info.get("formats") or []
    best_audio = select_best_audio_format(formats)

    video_options: list[DownloadOption] = []
    audio_options: list[DownloadOption] = []
    seen_video_keys: set[tuple] = set()
    seen_audio_keys: set[tuple] = set()

    for format_info in sorted(
        formats,
        key=lambda item: (
            item.get("vcodec") == "none",
            -(item.get("height") or 0),
            -(item.get("fps") or 0),
            item.get("ext") or "",
            item.get("format_id") or "",
        ),
    ):
        if not is_downloadable_format(format_info):
            continue

        has_video = format_has_video(format_info)
        has_audio = format_has_audio(format_info)
        ext = format_info.get("ext") or "unknown"
        format_id = str(format_info.get("format_id", "unknown"))

        if has_video:
            if not has_audio and not best_audio:
                continue

            resolution = get_resolution_text(format_info)
            fps_text = f"{format_info.get('fps')} fps" if format_info.get("fps") else "-"
            size_bytes = estimate_size_bytes(format_info, None if has_audio else best_audio)
            audio_text = "yes" if has_audio else "merged"
            selector = format_id if has_audio else f"{format_id}+bestaudio/best"
            detail_text = f"fmt {format_id}"
            dedupe_key = (resolution, ext, fps_text, audio_text, selector)

            if dedupe_key in seen_video_keys:
                continue
            seen_video_keys.add(dedupe_key)

            video_options.append(
                DownloadOption(
                    number=0,
                    kind="Video",
                    format_id=format_id,
                    format_selector=selector,
                    resolution=resolution,
                    extension=ext,
                    fps_text=fps_text,
                    audio_text=audio_text,
                    size_text=human_size(size_bytes),
                    detail_text=detail_text,
                )
            )

        elif has_audio:
            abr = format_info.get("abr")
            detail_text = f"{int(abr)} kbps" if abr else f"fmt {format_id}"
            dedupe_key = (ext, detail_text, format_id)

            if dedupe_key in seen_audio_keys:
                continue
            seen_audio_keys.add(dedupe_key)

            audio_options.append(
                DownloadOption(
                    number=0,
                    kind="Audio",
                    format_id=format_id,
                    format_selector=format_id,
                    resolution="audio only",
                    extension=ext,
                    fps_text="-",
                    audio_text="yes",
                    size_text=human_size(estimate_size_bytes(format_info)),
                    detail_text=f"{detail_text} | fmt {format_id}",
                )
            )

    if not video_options and not audio_options:
        raise RuntimeError("No usable download formats were found for this video.")

    assign_numbers(video_options, start=1)
    assign_numbers(audio_options, start=len(video_options) + 1)
    return video_options, audio_options


def filter_download_options_for_url(
    url: str,
    video_options: list[DownloadOption],
    audio_options: list[DownloadOption],
    cookie_browser: str,
    chrome_profile: str | None,
    output_dir: str,
    logger: Callable[[str], None] | None = None,
) -> tuple[list[DownloadOption], list[DownloadOption]]:
    valid_video_options = [
        option
        for option in video_options
        if can_download_selector(
            url,
            option.format_selector,
            cookie_browser,
            chrome_profile,
            output_dir,
        )
    ]
    valid_audio_options = [
        option
        for option in audio_options
        if can_download_selector(
            url,
            option.format_selector,
            cookie_browser,
            chrome_profile,
            output_dir,
        )
    ]

    if not valid_video_options and not valid_audio_options:
        raise RuntimeError(
            "No downloadable formats passed yt-dlp validation for this video.\n"
            "This is usually caused by an upstream YouTube/yt-dlp compatibility issue."
        )

    if logger is not None:
        removed_count = (len(video_options) + len(audio_options)) - (
            len(valid_video_options) + len(valid_audio_options)
        )
        if removed_count > 0:
            logger(
                f"Filtered out {removed_count} unavailable format option(s) after validation."
            )

    assign_numbers(valid_video_options, start=1)
    assign_numbers(valid_audio_options, start=len(valid_video_options) + 1)
    return valid_video_options, valid_audio_options


def assign_numbers(options: list[DownloadOption], start: int) -> None:
    for index, option in enumerate(options, start=start):
        option.number = index


def is_downloadable_format(format_info: dict) -> bool:
    if format_info.get("ext") == "mhtml":
        return False
    if format_info.get("protocol") == "mhtml":
        return False
    if not format_has_video(format_info) and not format_has_audio(format_info):
        return False
    format_note = str(format_info.get("format_note", "")).lower()
    return "storyboard" not in format_note


def format_has_video(format_info: dict) -> bool:
    if format_info.get("vcodec") not in (None, "none"):
        return True
    return format_info.get("video_ext") not in (None, "none")


def format_has_audio(format_info: dict) -> bool:
    if format_info.get("acodec") not in (None, "none"):
        return True
    if format_info.get("audio_ext") not in (None, "none"):
        return True
    return str(format_info.get("resolution", "")).lower() == "audio only"


def select_best_audio_format(formats: Iterable[dict]) -> dict | None:
    audio_formats = [
        item
        for item in formats
        if is_downloadable_format(item)
        and not format_has_video(item)
        and format_has_audio(item)
    ]
    if not audio_formats:
        return None

    return max(
        audio_formats,
        key=lambda item: (
            item.get("abr") or 0,
            estimate_size_bytes(item),
            item.get("ext") == "m4a",
        ),
    )


def estimate_size_bytes(primary_format: dict, extra_format: dict | None = None) -> int | None:
    size = primary_format.get("filesize") or primary_format.get("filesize_approx")
    if extra_format:
        extra_size = extra_format.get("filesize") or extra_format.get("filesize_approx")
        if size is not None and extra_size is not None:
            size += extra_size
    return size


def get_resolution_text(format_info: dict) -> str:
    resolution = format_info.get("resolution")
    if resolution and resolution != "audio only":
        return str(resolution)

    height = format_info.get("height")
    width = format_info.get("width")
    if height and width:
        return f"{width}x{height}"
    if height:
        return f"{height}p"
    return "unknown"


def sanitize_path_component(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")
    return cleaned or "Playlist"


def create_playlist_output_dir(base_output_dir: str, playlist_title: str) -> str:
    playlist_dir = os.path.join(base_output_dir, sanitize_path_component(playlist_title))
    os.makedirs(playlist_dir, exist_ok=True)
    return playlist_dir


def parse_first_number(text: str) -> int:
    match = re.search(r"(\d+)", text or "")
    return int(match.group(1)) if match else 0


def parse_audio_bitrate(detail_text: str) -> int:
    left_side = (detail_text or "").split("|", maxsplit=1)[0].strip()
    return parse_first_number(left_side)


def make_playlist_group_key(option: DownloadOption) -> str:
    if option.kind == "Video":
        return f"video::{option.resolution}::{option.extension}"
    return f"audio::{option.extension}"


def is_better_group_match(candidate: DownloadOption, current: DownloadOption) -> bool:
    if candidate.kind == "Video":
        candidate_fps = parse_first_number(candidate.fps_text)
        current_fps = parse_first_number(current.fps_text)

        if candidate_fps != current_fps:
            return candidate_fps > current_fps

        candidate_audio_pref = 1 if candidate.audio_text == "yes" else 0
        current_audio_pref = 1 if current.audio_text == "yes" else 0
        if candidate_audio_pref != current_audio_pref:
            return candidate_audio_pref > current_audio_pref

        candidate_size = parse_size_guess(candidate.size_text)
        current_size = parse_size_guess(current.size_text)
        return candidate_size > current_size

    candidate_bitrate = parse_audio_bitrate(candidate.detail_text)
    current_bitrate = parse_audio_bitrate(current.detail_text)

    if candidate_bitrate != current_bitrate:
        return candidate_bitrate > current_bitrate

    candidate_size = parse_size_guess(candidate.size_text)
    current_size = parse_size_guess(current.size_text)
    return candidate_size > current_size


def parse_size_guess(size_text: str) -> float:
    if not size_text or size_text == "unknown":
        return 0.0

    match = re.match(r"([\d.]+)\s*([A-Za-z]+)", size_text.strip())
    if not match:
        return 0.0

    value = float(match.group(1))
    unit = match.group(2).upper()

    unit_scale = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
    }
    return value * unit_scale.get(unit, 1)


def build_playlist_option_mapping(
    video_options: list[DownloadOption], audio_options: list[DownloadOption]
) -> dict[str, DownloadOption]:
    mapping: dict[str, DownloadOption] = {}

    for option in video_options + audio_options:
        key = make_playlist_group_key(option)
        current = mapping.get(key)
        if current is None or is_better_group_match(option, current):
            mapping[key] = option

    return mapping


def build_playlist_option_label(option: DownloadOption) -> str:
    if option.kind == "Video":
        return (
            f"{option.resolution} | {option.extension} | "
            f"{option.fps_text} | {option.audio_text}"
        )

    bitrate = parse_audio_bitrate(option.detail_text)
    bitrate_text = f"{bitrate} kbps" if bitrate else option.detail_text.split("|", 1)[0].strip()
    return f"audio only | {option.extension} | {bitrate_text}"


def sort_playlist_grouped_options(options: list[DownloadOption]) -> list[DownloadOption]:
    return sorted(
        options,
        key=lambda option: (
            option.kind != "Video",
            -parse_first_number(option.resolution) if option.kind == "Video" else 0,
            option.extension,
            -parse_audio_bitrate(option.detail_text) if option.kind == "Audio" else 0,
        ),
    )


def scan_playlist_formats(
    playlist_entries: list[PlaylistEntry],
    use_chrome_cookies: bool,
    chrome_profile: str | None,
    output_dir: str,
    logger: Callable[[str], None] | None = None,
) -> list[PlaylistScannedVideo]:
    if logger is None:
        print_section("Playlist Format Scan")
        print("Scanning all videos in the playlist to discover available formats...")
    else:
        logger("Scanning all videos in the playlist to discover available formats...")

    scanned: list[PlaylistScannedVideo] = []

    for index, entry in enumerate(playlist_entries, start=1):
        log_message(
            f"[{index}/{len(playlist_entries)}] {entry.title}",
            logger=logger,
        )

        try:
            info, _ = extract_video_info(
                entry.url,
                use_chrome_cookies,
                chrome_profile,
                output_dir,
                logger=logger,
            )
            video_options, audio_options = build_download_options(info)
            option_by_key = build_playlist_option_mapping(video_options, audio_options)
            grouped_options = sort_playlist_grouped_options(list(option_by_key.values()))
            available_labels = [build_playlist_option_label(option) for option in grouped_options]

            scanned.append(
                PlaylistScannedVideo(
                    title=entry.title,
                    url=entry.url,
                    channel=entry.channel,
                    duration_text=entry.duration_text,
                    thumbnail_url=entry.thumbnail_url or select_thumbnail_url(info),
                    option_by_key=option_by_key,
                    available_labels=available_labels,
                )
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Unable to scan playlist formats.\n"
                f"Video: {entry.title}\n"
                f"Details:\n  - {clean_ydl_error(exc)}"
            ) from exc

    return scanned


def build_common_playlist_options(
    scanned_videos: list[PlaylistScannedVideo],
) -> list[PlaylistCommonOption]:
    if not scanned_videos:
        return []

    common_keys = set(scanned_videos[0].option_by_key.keys())
    for scanned in scanned_videos[1:]:
        common_keys &= set(scanned.option_by_key.keys())

    if not common_keys:
        return []

    representative_pairs = [
        (key, scanned_videos[0].option_by_key[key])
        for key in common_keys
    ]
    representative_pairs.sort(
        key=lambda item: (
            item[1].kind != "Video",
            -parse_first_number(item[1].resolution) if item[1].kind == "Video" else 0,
            item[1].extension,
            -parse_audio_bitrate(item[1].detail_text) if item[1].kind == "Audio" else 0,
        )
    )

    common_options: list[PlaylistCommonOption] = []

    for number, (key, representative) in enumerate(representative_pairs, start=1):
        matched_options = [scanned.option_by_key[key] for scanned in scanned_videos]

        if representative.kind == "Video":
            fps_values = [parse_first_number(option.fps_text) for option in matched_options]
            fps_values = [value for value in fps_values if value > 0]

            if not fps_values:
                fps_text = "-"
            elif min(fps_values) == max(fps_values):
                fps_text = f"{fps_values[0]} fps"
            else:
                fps_text = f"{min(fps_values)}-{max(fps_values)} fps"

            audio_values = {option.audio_text for option in matched_options}
            audio_text = next(iter(audio_values)) if len(audio_values) == 1 else "mixed"

            detail_text = f"available in all {len(scanned_videos)} videos"

            common_options.append(
                PlaylistCommonOption(
                    number=number,
                    key=key,
                    kind="Video",
                    resolution=representative.resolution,
                    extension=representative.extension,
                    fps_text=fps_text,
                    audio_text=audio_text,
                    size_text="playlist",
                    detail_text=detail_text,
                )
            )
            continue

        bitrate_values = [parse_audio_bitrate(option.detail_text) for option in matched_options]
        bitrate_values = [value for value in bitrate_values if value > 0]

        if not bitrate_values:
            detail_text = f"{representative.extension} audio in all {len(scanned_videos)} videos"
        elif min(bitrate_values) == max(bitrate_values):
            detail_text = f"{bitrate_values[0]} kbps in all {len(scanned_videos)} videos"
        else:
            detail_text = (
                f"{min(bitrate_values)}-{max(bitrate_values)} kbps "
                f"across {len(scanned_videos)} videos"
            )

        common_options.append(
            PlaylistCommonOption(
                number=number,
                key=key,
                kind="Audio",
                resolution="audio only",
                extension=representative.extension,
                fps_text="-",
                audio_text="yes",
                size_text="playlist",
                detail_text=detail_text,
            )
        )

    return common_options


def print_playlist_video_formats(scanned_videos: list[PlaylistScannedVideo]) -> None:
    print_section("Available Formats Per Playlist Video")
    for index, scanned in enumerate(scanned_videos, start=1):
        print(f"{index}. {scanned.title}")
        for label in scanned.available_labels:
            print(f"   - {label}")
        print()


def print_playlist_common_format_menu(common_options: list[PlaylistCommonOption]) -> None:
    print_section("Common Playlist Formats")
    print(
        f"{'#':<4} {'Type':<8} {'Resolution':<14} {'Ext':<6} "
        f"{'FPS':<10} {'Audio':<8} {'Size':<12} Details"
    )
    print("-" * 110)

    for option in common_options:
        print(render_option_line(option))

    print("-" * 110)
    print("Choose one of the common playlist formats above, or q to quit.")


def prompt_for_playlist_common_option(
    options: list[PlaylistCommonOption],
) -> PlaylistCommonOption | None:
    lookup = {str(option.number): option for option in options}

    while True:
        choice = input("Format: ").strip().lower()

        if choice in {"q", "quit", "exit"}:
            return None
        if choice in lookup:
            return lookup[choice]

        print("Please enter one of the listed numbers, or q to quit.")


def print_available_formats_from_scan(scanned_video: PlaylistScannedVideo) -> None:
    print("  Available formats:")
    for label in scanned_video.available_labels:
        print(f"    - {label}")


def print_video_summary(info: dict, cookie_browser: str) -> None:
    title = info.get("title", "Unknown title")
    uploader = info.get("uploader") or info.get("channel") or "Unknown uploader"
    duration = format_duration(info.get("duration"))
    cookie_text = (
        "not using browser cookies"
        if cookie_browser == COOKIE_SOURCE_NONE
        else f"using {cookie_browser} browser cookies"
    )

    print_section("Video")
    print_key_value("Title", title)
    print_key_value("Channel", uploader)
    print_key_value("Duration", duration)
    print_key_value("Cookies", cookie_text)


def print_playlist_summary(
    playlist_info: dict, playlist_entries: list[PlaylistEntry], cookie_browser: str
) -> None:
    title = playlist_info.get("title") or "Unknown playlist"
    uploader = playlist_info.get("uploader") or playlist_info.get("channel") or "-"
    cookie_text = (
        "not using browser cookies"
        if cookie_browser == COOKIE_SOURCE_NONE
        else f"using {cookie_browser} browser cookies"
    )

    print_section("Playlist")
    print_key_value("Title", title)
    print_key_value("Channel", uploader)
    print_key_value("Videos", str(len(playlist_entries)))
    print_key_value("Cookies", cookie_text)


def print_format_menu(video_options: list[DownloadOption], audio_options: list[DownloadOption]) -> None:
    print_section("Formats")
    print(
        f"{'#':<4} {'Type':<8} {'Resolution':<14} {'Ext':<6} "
        f"{'FPS':<8} {'Audio':<8} {'Size':<12} Details"
    )
    print("-" * 100)

    if video_options:
        print("VIDEO")
        for option in video_options:
            print(render_option_line(option))

    if audio_options:
        if video_options:
            print("-" * 100)
        print("AUDIO")
        for option in audio_options:
            print(render_option_line(option))

    print("-" * 100)
    print("Enter a format number, or q to quit.")


def render_option_line(option: object) -> str:
    return (
        f"{getattr(option, 'number'):<4} "
        f"{getattr(option, 'kind'):<8} "
        f"{getattr(option, 'resolution'):<14} "
        f"{getattr(option, 'extension'):<6} "
        f"{getattr(option, 'fps_text'):<10} "
        f"{getattr(option, 'audio_text'):<8} "
        f"{getattr(option, 'size_text'):<12} "
        f"{getattr(option, 'detail_text')}"
    )


def prompt_for_option(options: list[DownloadOption]) -> DownloadOption | None:
    lookup = {str(option.number): option for option in options}

    while True:
        choice = input("Format: ").strip().lower()

        if choice in {"q", "quit", "exit"}:
            return None
        if choice in lookup:
            return lookup[choice]

        print("Please enter one of the listed numbers, or q to quit.")


def download_media(
    url: str,
    option: DownloadOption,
    cookie_browser: str,
    chrome_profile: str | None,
    output_dir: str,
    progress_callback: Callable[[dict], None] | None = None,
    logger: Callable[[str], None] | None = None,
) -> None:
    progress = ProgressPrinter(message_callback=progress_callback)
    selected_cookie_browser = (
        None if cookie_browser == COOKIE_SOURCE_NONE else cookie_browser
    )
    ydl_options = build_base_options(
        cookie_browser=selected_cookie_browser,
        chrome_profile=chrome_profile if selected_cookie_browser else None,
        output_dir=output_dir,
    )
    ydl_options.update(
        {
            "format": option.format_selector,
            "progress_hooks": [progress.download_hook],
            "postprocessor_hooks": [progress.postprocessor_hook],
        }
    )

    try:
        with YoutubeDL(ydl_options) as ydl:
            ydl.download([url])
    except DownloadError as exc:
        if selected_cookie_browser is None and is_auth_related_error(exc):
            log_message(
                "\nDownload requires a logged-in session. Retrying with browser cookies...",
                logger=logger,
                stream="stderr",
            )
            retry_download_with_cookie_fallback(
                url,
                option,
                chrome_profile,
                output_dir,
                progress_callback=progress_callback,
                logger=logger,
            )
            return
        raise RuntimeError(f"Download failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unexpected download failure: {exc}") from exc


def can_download_selector(
    url: str,
    format_selector: str,
    cookie_browser: str,
    chrome_profile: str | None,
    output_dir: str,
) -> bool:
    selected_cookie_browser = (
        None if cookie_browser == COOKIE_SOURCE_NONE else cookie_browser
    )
    ydl_options = build_base_options(
        cookie_browser=selected_cookie_browser,
        chrome_profile=chrome_profile if selected_cookie_browser else None,
        output_dir=output_dir,
    )
    ydl_options.update(
        {
            "format": format_selector,
            "skip_download": True,
        }
    )

    try:
        with YoutubeDL(ydl_options) as ydl:
            ydl.download([url])
        return True
    except Exception:
        return False


def retry_download_with_cookie_fallback(
    url: str,
    option: DownloadOption,
    chrome_profile: str | None,
    output_dir: str,
    progress_callback: Callable[[dict], None] | None = None,
    logger: Callable[[str], None] | None = None,
) -> None:
    cookie_errors: list[tuple[str, Exception]] = []

    for browser in COOKIE_FALLBACK_BROWSERS:
        progress = ProgressPrinter(message_callback=progress_callback)
        ydl_options = build_base_options(
            cookie_browser=browser,
            chrome_profile=chrome_profile,
            output_dir=output_dir,
        )
        ydl_options.update(
            {
                "format": option.format_selector,
                "progress_hooks": [progress.download_hook],
                "postprocessor_hooks": [progress.postprocessor_hook],
            }
        )

        try:
            log_message(
                f"Trying browser cookies from {browser}...",
                logger=logger,
                stream="stderr",
            )
            with YoutubeDL(ydl_options) as ydl:
                ydl.download([url])
            log_message(
                f"Retry succeeded using {browser} cookies.",
                logger=logger,
                stream="stderr",
            )
            return
        except Exception as exc:
            cookie_errors.append((browser, exc))

    raise RuntimeError(build_cookie_error_message(cookie_errors, chrome_profile))


def human_size(size_bytes: int | float | None) -> str:
    if size_bytes is None:
        return "unknown"

    size = float(size_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    return f"{size:.1f} {units[unit_index]}"


def log_message(
    message: str,
    logger: Callable[[str], None] | None = None,
    *,
    stream: str = "stdout",
) -> None:
    if logger is not None:
        logger(message)
        return

    if stream == "stderr":
        print(message, file=sys.stderr)
        return

    print(message)


def select_thumbnail_url(info: dict) -> str | None:
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        valid = [item for item in thumbnails if item.get("url")]
        if valid:
            valid.sort(
                key=lambda item: (
                    item.get("width") or 0,
                    item.get("height") or 0,
                )
            )
            return valid[-1]["url"]

    thumbnail = info.get("thumbnail")
    return str(thumbnail) if thumbnail else None


def clean_ydl_error(error: Exception) -> str:
    message = str(error).strip()
    for prefix in ("ERROR: ERROR: ", "ERROR: "):
        if message.startswith(prefix):
            message = message[len(prefix):]
    return message


def is_auth_related_error(error: Exception) -> bool:
    message = clean_ydl_error(error).lower()
    return any(snippet in message for snippet in AUTH_RELATED_ERROR_SNIPPETS)


def build_metadata_error_message(error: Exception) -> str:
    details = clean_ydl_error(error)
    return f"Unable to read YouTube metadata.\nDetails:\n  - {details}"


def build_playlist_error_message(error: Exception) -> str:
    details = clean_ydl_error(error)
    return f"Unable to read playlist metadata.\nDetails:\n  - {details}"


def build_cookie_error_message(
    errors: list[tuple[str, Exception]],
    chrome_profile: str | None,
    initial_error: Exception | None = None,
) -> str:
    profile_text = chrome_profile or "Default"
    browser_results = "\n".join(
        f"  - {browser}: {clean_ydl_error(error)}" for browser, error in errors
    )
    initial_details = ""
    if initial_error is not None:
        initial_details = f"Initial no-cookie error:\n  - {clean_ydl_error(initial_error)}\n"

    return (
        "Unable to complete the YouTube request using browser cookies.\n"
        f"Profile: {profile_text}\n"
        "Browsers tried in order: chrome, edge, brave.\n"
        "On Windows, this usually means yt-dlp could not decrypt or copy the "
        "browser cookie database.\n"
        "Try these fixes:\n"
        "  1. Fully close Chrome and run the script again.\n"
        "  2. Run the terminal as the same Windows user who uses Chrome.\n"
        "  3. Do not run the terminal elevated if Chrome is used normally.\n"
        "  4. If your YouTube login is in another profile, run with "
        '`--chrome-profile "Profile 1"` or the correct profile name.\n'
        "  5. If Chrome still fails, sign in to YouTube in Edge or Brave and try again.\n"
        f"{initial_details}Details:\n{browser_results}"
    )


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "unknown"

    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_eta(seconds: int | float | None) -> str:
    if seconds is None:
        return "--:--"
    return format_duration(seconds)


def resolve_output_dir(output_dir: str | None) -> str:
    resolved = os.path.abspath(output_dir or os.getcwd())
    os.makedirs(resolved, exist_ok=True)
    return resolved


def configure_console_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue

        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (LookupError, OSError, ValueError):
            try:
                stream.reconfigure(errors="replace")
            except (LookupError, OSError, ValueError):
                continue


def print_header() -> None:
    line = "=" * 72
    print(line)
    print(APP_TITLE)
    print(line)
    print("Paste a YouTube video or playlist URL, choose a save folder, then pick a format.\n")


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * 72)


def print_key_value(label: str, value: str) -> None:
    print(f"{label:<10}: {value}")


def prompt_for_output_dir(initial_output_dir: str, playlist_name: str | None = None) -> str:
    while True:
        print_section("Save Location")
        print_key_value("Current", initial_output_dir)
        if playlist_name:
            print_key_value("Playlist", playlist_name)
            print("A new folder with the playlist name will be created inside this location.")
        print("Press Enter to keep this folder, or type a new path.")
        choice = input("Folder: ").strip().strip('"')

        if not choice:
            return initial_output_dir

        try:
            resolved = resolve_output_dir(choice)
            print_key_value("Selected", resolved)
            return resolved
        except OSError as exc:
            print(f"Invalid folder: {exc}")


def main() -> int:
    configure_console_output()
    args = parse_arguments()
    use_chrome_cookies = args.use_chrome_cookies or bool(args.chrome_profile)
    output_dir = resolve_output_dir(args.output_dir)

    try:
        print_header()
        url = normalize_and_validate_url(prompt_for_url(args.url))

        if is_playlist_url(url):
            playlist_info, cookie_browser = extract_playlist_info(
                url, use_chrome_cookies, args.chrome_profile, output_dir
            )
            playlist_entries = build_playlist_entries(playlist_info)
            if not playlist_entries:
                raise RuntimeError("No videos were found in this playlist.")

            playlist_title = playlist_info.get("title") or "Playlist"

            print_playlist_summary(playlist_info, playlist_entries, cookie_browser)

            scanned_videos = scan_playlist_formats(
                playlist_entries=playlist_entries,
                use_chrome_cookies=use_chrome_cookies,
                chrome_profile=args.chrome_profile,
                output_dir=output_dir,
            )

            print_playlist_video_formats(scanned_videos)

            common_options = build_common_playlist_options(scanned_videos)
            if not common_options:
                raise RuntimeError(
                    "No common downloadable format was found across the whole playlist.\n"
                    "Try downloading videos individually, or split the playlist into smaller groups."
                )

            print_playlist_common_format_menu(common_options)

            selected_common_option = prompt_for_playlist_common_option(common_options)
            if selected_common_option is None:
                print("Playlist download cancelled.")
                return 0

            if args.output_dir is None:
                output_dir = prompt_for_output_dir(output_dir, playlist_title)
            playlist_output_dir = create_playlist_output_dir(output_dir, playlist_title)

            print_section("Starting Playlist")
            print_key_value("Playlist", playlist_title)
            print_key_value("Videos", str(len(scanned_videos)))
            print_key_value(
                "Selection",
                f"{selected_common_option.kind} | {selected_common_option.resolution} | "
                f"{selected_common_option.extension}",
            )
            print_key_value("Save to", playlist_output_dir)

            downloaded_count = 0
            skipped_items: list[str] = []

            for index, scanned_video in enumerate(scanned_videos, start=1):
                actual_option = scanned_video.option_by_key[selected_common_option.key]

                print_section(f"Item {index}/{len(scanned_videos)}")
                print_key_value("Title", scanned_video.title)
                print_key_value(
                    "Target",
                    f"{actual_option.kind} | {actual_option.resolution} | "
                    f"{actual_option.extension} | {actual_option.detail_text}",
                )

                try:
                    download_media(
                        scanned_video.url,
                        actual_option,
                        cookie_browser,
                        args.chrome_profile,
                        playlist_output_dir,
                    )
                    downloaded_count += 1
                except RuntimeError as exc:
                    error_text = clean_ydl_error(exc)
                    skipped_items.append(f"{scanned_video.title}: {error_text}")
                    print(f"  Skipping: {error_text}")
                    print_available_formats_from_scan(scanned_video)

            print_section("Playlist Summary")
            print_key_value("Downloaded", str(downloaded_count))
            print_key_value("Skipped", str(len(skipped_items)))

            if skipped_items:
                print_section("Skipped Items")
                for item in skipped_items:
                    print(f"- {item}")

            print(f"Saved playlist to: {playlist_output_dir}")
            return 0

        info, cookie_browser = extract_video_info(
            url, use_chrome_cookies, args.chrome_profile, output_dir
        )

        if args.output_dir is None:
            output_dir = prompt_for_output_dir(output_dir)

        video_options, audio_options = build_download_options(info)
        all_options = video_options + audio_options

        print_video_summary(info, cookie_browser)
        print_section("Download")
        print_key_value("Save to", output_dir)
        print_format_menu(video_options, audio_options)

        selected_option = prompt_for_option(all_options)
        if selected_option is None:
            print("Download cancelled.")
            return 0

        print_section("Starting")
        print_key_value(
            "Selection",
            f"{selected_option.kind} | {selected_option.resolution} | "
            f"{selected_option.extension} | {selected_option.detail_text}",
        )

        download_media(
            url,
            selected_option,
            cookie_browser,
            args.chrome_profile,
            output_dir,
        )
        print(f"Saved to: {output_dir}")
        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 1
    except ValueError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
