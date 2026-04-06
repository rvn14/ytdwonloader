"""High-level workflows for the Tkinter UI."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core import (
    COOKIE_SOURCE_NONE,
    DownloadOption,
    PlaylistCommonOption,
    PlaylistEntry,
    PlaylistScannedVideo,
    build_common_playlist_options,
    build_download_options,
    build_playlist_entries,
    clean_ydl_error,
    create_playlist_output_dir,
    download_media,
    extract_playlist_info,
    extract_video_info,
    format_duration,
    is_playlist_url,
    normalize_and_validate_url,
    resolve_output_dir,
    select_thumbnail_url,
)


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[dict], None]


@dataclass(slots=True)
class ScanResult:
    mode: str
    url: str
    output_dir: str
    cookie_browser: str
    use_chrome_cookies: bool
    chrome_profile: str | None
    title: str
    channel: str
    duration_text: str
    cookie_text: str
    thumbnail_url: str | None = None
    video_count: int = 0
    info: dict = field(default_factory=dict)
    playlist_entries: list[PlaylistEntry] = field(default_factory=list)
    scanned_videos: list[PlaylistScannedVideo] = field(default_factory=list)
    video_options: list[DownloadOption] = field(default_factory=list)
    audio_options: list[DownloadOption] = field(default_factory=list)
    common_options: list[PlaylistCommonOption] = field(default_factory=list)

    @property
    def all_video_options(self) -> list[DownloadOption]:
        return self.video_options + self.audio_options


def scan_url(
    url: str,
    use_chrome_cookies: bool = False,
    chrome_profile: str | None = None,
    output_dir: str | None = None,
    logger: LogCallback | None = None,
) -> ScanResult:
    normalized_url = normalize_and_validate_url(url)
    resolved_output_dir = resolve_output_dir(output_dir)

    if is_playlist_url(normalized_url):
        playlist_info, cookie_browser = extract_playlist_info(
            normalized_url,
            use_chrome_cookies,
            chrome_profile,
            resolved_output_dir,
            logger=logger,
        )
        playlist_entries = build_playlist_entries(playlist_info)
        if not playlist_entries:
            raise RuntimeError("No videos were found in this playlist.")

        scanned_videos = scan_playlist(
            playlist_entries,
            use_chrome_cookies,
            chrome_profile,
            resolved_output_dir,
            logger=logger,
        )
        common_options = build_common_playlist_options(scanned_videos)
        if not common_options:
            raise RuntimeError(
                "No common downloadable format was found across the whole playlist.\n"
                "Try downloading videos individually, or split the playlist into smaller groups."
            )

        return ScanResult(
            mode="playlist",
            url=normalized_url,
            output_dir=resolved_output_dir,
            cookie_browser=cookie_browser,
            use_chrome_cookies=use_chrome_cookies,
            chrome_profile=chrome_profile,
            title=playlist_info.get("title") or "Unknown playlist",
            channel=playlist_info.get("uploader") or playlist_info.get("channel") or "-",
            duration_text="-",
            cookie_text=describe_cookie_source(cookie_browser),
            thumbnail_url=playlist_entries[0].thumbnail_url if playlist_entries else None,
            video_count=len(playlist_entries),
            info=playlist_info,
            playlist_entries=playlist_entries,
            scanned_videos=scanned_videos,
            common_options=common_options,
        )

    info, cookie_browser = extract_video_info(
        normalized_url,
        use_chrome_cookies,
        chrome_profile,
        resolved_output_dir,
        logger=logger,
    )
    video_options, audio_options = build_download_options(info)

    return ScanResult(
        mode="video",
        url=normalized_url,
        output_dir=resolved_output_dir,
        cookie_browser=cookie_browser,
        use_chrome_cookies=use_chrome_cookies,
        chrome_profile=chrome_profile,
        title=info.get("title", "Unknown title"),
        channel=info.get("uploader") or info.get("channel") or "Unknown uploader",
        duration_text=format_duration(info.get("duration")),
        cookie_text=describe_cookie_source(cookie_browser),
        thumbnail_url=select_thumbnail_url(info),
        info=info,
        video_options=video_options,
        audio_options=audio_options,
    )


def scan_playlist(
    playlist_entries: list[PlaylistEntry],
    use_chrome_cookies: bool,
    chrome_profile: str | None,
    output_dir: str,
    logger: LogCallback | None = None,
) -> list[PlaylistScannedVideo]:
    from core import scan_playlist_formats

    return scan_playlist_formats(
        playlist_entries=playlist_entries,
        use_chrome_cookies=use_chrome_cookies,
        chrome_profile=chrome_profile,
        output_dir=output_dir,
        logger=logger,
    )


def download_scan_result(
    scan_result: ScanResult,
    option_number: int,
    output_dir: str | None = None,
    logger: LogCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    resolved_output_dir = resolve_output_dir(output_dir or scan_result.output_dir)

    if scan_result.mode == "video":
        selected_option = get_video_option(scan_result, option_number)
        download_media(
            scan_result.url,
            selected_option,
            scan_result.cookie_browser,
            scan_result.chrome_profile,
            resolved_output_dir,
            progress_callback=progress_callback,
            logger=logger,
        )
        return {
            "mode": "video",
            "saved_to": resolved_output_dir,
            "downloaded": 1,
            "skipped": [],
            "selected_option": selected_option,
        }

    selected_common_option = get_playlist_option(scan_result, option_number)
    playlist_output_dir = create_playlist_output_dir(resolved_output_dir, scan_result.title)
    skipped_items: list[str] = []
    total_items = len(scan_result.scanned_videos)
    downloaded_count = 0

    for index, scanned_video in enumerate(scan_result.scanned_videos, start=1):
        if logger is not None:
            logger(f"[{index}/{total_items}] {scanned_video.title}")

        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "playlist",
                    "status": "item-start",
                    "item_index": index,
                    "item_total": total_items,
                    "item_title": scanned_video.title,
                    "overall_percent": ((index - 1) / total_items) * 100,
                }
            )

        actual_option = scanned_video.option_by_key[selected_common_option.key]

        try:
            download_media(
                scanned_video.url,
                actual_option,
                scan_result.cookie_browser,
                scan_result.chrome_profile,
                playlist_output_dir,
                progress_callback=_playlist_progress_callback(
                    progress_callback,
                    index,
                    total_items,
                    scanned_video.title,
                ),
                logger=logger,
            )
            downloaded_count += 1
        except RuntimeError as exc:
            error_text = clean_ydl_error(exc)
            skipped_items.append(f"{scanned_video.title}: {error_text}")
            if logger is not None:
                logger(f"Skipping: {error_text}")
                logger("Available formats:")
                for label in scanned_video.available_labels:
                    logger(f"  - {label}")

    if progress_callback is not None:
        progress_callback(
            {
                "phase": "playlist",
                "status": "finished",
                "item_total": total_items,
                "overall_percent": 100.0,
            }
        )

    return {
        "mode": "playlist",
        "saved_to": playlist_output_dir,
        "downloaded": downloaded_count,
        "skipped": skipped_items,
        "selected_option": selected_common_option,
    }


def get_video_option(scan_result: ScanResult, option_number: int) -> DownloadOption:
    for option in scan_result.all_video_options:
        if option.number == option_number:
            return option
    raise ValueError("Please choose a valid format before downloading.")


def get_playlist_option(scan_result: ScanResult, option_number: int) -> PlaylistCommonOption:
    for option in scan_result.common_options:
        if option.number == option_number:
            return option
    raise ValueError("Please choose a valid playlist format before downloading.")


def describe_cookie_source(cookie_browser: str) -> str:
    if cookie_browser == COOKIE_SOURCE_NONE:
        return "not using browser cookies"
    return f"using {cookie_browser} browser cookies"


def _playlist_progress_callback(
    progress_callback: ProgressCallback | None,
    item_index: int,
    item_total: int,
    item_title: str,
) -> ProgressCallback | None:
    if progress_callback is None:
        return None

    def relay(payload: dict) -> None:
        percent = payload.get("percent")
        overall_percent = ((item_index - 1) / item_total) * 100
        if percent is not None:
            overall_percent = ((item_index - 1) + (percent / 100)) / item_total * 100

        merged = dict(payload)
        merged.update(
            {
                "item_index": item_index,
                "item_total": item_total,
                "item_title": item_title,
                "overall_percent": overall_percent,
            }
        )
        progress_callback(merged)

    return relay
