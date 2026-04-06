#!/usr/bin/env python3
"""
Interactive YouTube downloader built with yt-dlp.

Features:
- Accepts a YouTube URL from the command line or an interactive prompt
- Extracts formats first and displays them in a numbered list
- Supports video downloads (with audio merged when needed) and audio-only downloads
- Supports optional Chrome browser cookies when login is needed
- Shows download progress directly in the terminal

The code is intentionally beginner-friendly and split into small functions so it
is easy to extend later.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


COOKIE_BROWSER = "chrome"
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

    def __init__(self) -> None:
        self._last_length = 0
        self._last_update = 0.0

    def download_hook(self, data: dict) -> None:
        status = data.get("status")

        if status == "downloading":
            now = time.monotonic()
            # Throttle updates so the terminal remains readable.
            if now - self._last_update < 0.1:
                return
            self._last_update = now

            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            speed = data.get("speed")
            eta = data.get("eta")

            if total:
                percent = f"{downloaded / total * 100:5.1f}%"
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
            self._print_inline(line)

        elif status == "finished":
            filename = os.path.basename(data.get("filename", "download"))
            self._print_inline(f"[download] Finished: {filename}", newline=True)

    def postprocessor_hook(self, data: dict) -> None:
        status = data.get("status")
        postprocessor = data.get("postprocessor", "post-processing")

        if status in {"started", "processing"}:
            self._print_inline(f"[postprocess] {postprocessor}...")
        elif status == "finished":
            self._print_inline("[postprocess] Completed.", newline=True)

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
        help="YouTube video URL. If omitted, the script asks for it interactively.",
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
            "Try browser cookies in this order: chrome, edge, brave. Use this "
            "only when the video requires a logged-in browser session."
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

    # Allow the user to paste youtube.com/... without typing https:// first.
    if "://" not in url:
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host not in YOUTUBE_HOSTS:
        raise ValueError("This CLI expects a YouTube video URL.")

    if host.endswith("youtu.be"):
        if parsed.path.strip("/"):
            return url
        raise ValueError("The shortened YouTube URL is missing a video ID.")

    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)

    if path == "/watch" and query.get("v"):
        return url

    allowed_prefixes = ("/shorts/", "/live/", "/embed/")
    if any(path.startswith(prefix) for prefix in allowed_prefixes):
        return url

    raise ValueError("The URL does not look like a direct YouTube video link.")


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

    if cookie_browser:
        options["cookiesfrombrowser"] = (cookie_browser, chrome_profile, None, None)

    return options


def extract_video_info(
    url: str, use_chrome_cookies: bool, chrome_profile: str | None, output_dir: str
) -> tuple[dict, str]:
    if use_chrome_cookies:
        return extract_video_info_with_cookie_fallback(url, chrome_profile, output_dir)

    try:
        with YoutubeDL(build_base_options(output_dir=output_dir)) as ydl:
            info = ydl.extract_info(url, download=False)
        return unwrap_video_info(info), COOKIE_SOURCE_NONE
    except Exception as exc:  # yt-dlp raises multiple exception types here.
        if is_auth_related_error(exc):
            print(
                "Metadata requires a logged-in session! Retrying with browser cookies...",
                file=sys.stderr,
            )
            return extract_video_info_with_cookie_fallback(
                url, chrome_profile, output_dir, initial_error=exc
            )
        raise RuntimeError(build_metadata_error_message(exc)) from exc


def extract_video_info_with_cookie_fallback(
    url: str,
    chrome_profile: str | None,
    output_dir: str,
    initial_error: Exception | None = None,
) -> tuple[dict, str]:
    cookie_errors: list[tuple[str, Exception]] = []

    for browser in COOKIE_FALLBACK_BROWSERS:
        try:
            with YoutubeDL(
                build_base_options(
                    cookie_browser=browser,
                    chrome_profile=chrome_profile,
                    output_dir=output_dir,
                )
            ) as ydl:
                info = ydl.extract_info(url, download=False)
            return unwrap_video_info(info), browser
        except Exception as exc:  # yt-dlp raises multiple exception types here.
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


def print_format_menu(video_options: list[DownloadOption], audio_options: list[DownloadOption]) -> None:
    print_section("Formats")
    print(f"{'#':<4} {'Type':<8} {'Resolution':<14} {'Ext':<6} {'FPS':<8} {'Audio':<8} {'Size':<12} Details")
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


def render_option_line(option: DownloadOption) -> str:
    return (
        f"{option.number:<4} "
        f"{option.kind:<8} "
        f"{option.resolution:<14} "
        f"{option.extension:<6} "
        f"{option.fps_text:<8} "
        f"{option.audio_text:<8} "
        f"{option.size_text:<12} "
        f"{option.detail_text}"
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
) -> None:
    progress = ProgressPrinter()
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
            print(
                "\nDownload requires a logged-in session. Retrying with browser cookies...",
                file=sys.stderr,
            )
            retry_download_with_cookie_fallback(url, option, chrome_profile, output_dir)
            return
        raise RuntimeError(f"Download failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Unexpected download failure: {exc}") from exc


def retry_download_with_cookie_fallback(
    url: str, option: DownloadOption, chrome_profile: str | None, output_dir: str
) -> None:
    cookie_errors: list[tuple[str, Exception]] = []

    for browser in COOKIE_FALLBACK_BROWSERS:
        progress = ProgressPrinter()
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
            print(f"Trying browser cookies from {browser}...", file=sys.stderr)
            with YoutubeDL(ydl_options) as ydl:
                ydl.download([url])
            print(f"Retry succeeded using {browser} cookies.", file=sys.stderr)
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


def clean_ydl_error(error: Exception) -> str:
    message = str(error).strip()
    for prefix in ("ERROR: ERROR: ", "ERROR: "):
        if message.startswith(prefix):
            message = message[len(prefix) :]
    return message


def is_auth_related_error(error: Exception) -> bool:
    message = clean_ydl_error(error).lower()
    return any(snippet in message for snippet in AUTH_RELATED_ERROR_SNIPPETS)


def build_metadata_error_message(error: Exception) -> str:
    details = clean_ydl_error(error)
    return f"Unable to read YouTube metadata.\nDetails:\n  - {details}"


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
        "`--chrome-profile \"Profile 1\"` or the correct profile name.\n"
        "  5. If Chrome still fails, sign in to YouTube in Edge or Brave and try "
        "again with the same command.\n"
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


def print_header() -> None:
    line = "=" * 72
    print(line)
    print(APP_TITLE)
    print(line)
    print("Paste a YouTube video URL, choose a save folder, then pick a format.\n")


def print_section(title: str) -> None:
    print(f"\n{title}")
    print("-" * 72)


def print_key_value(label: str, value: str) -> None:
    print(f"{label:<10}: {value}")


def prompt_for_output_dir(initial_output_dir: str) -> str:
    while True:
        print_section("Save Location")
        print_key_value("Current", initial_output_dir)
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
    args = parse_arguments()
    use_chrome_cookies = args.use_chrome_cookies or bool(args.chrome_profile)
    output_dir = resolve_output_dir(args.output_dir)

    try:
        print_header()
        url = normalize_and_validate_url(prompt_for_url(args.url))
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


if __name__ == "__main__":
    raise SystemExit(main())
