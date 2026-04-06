"""customtkinter interface for the YouTube downloader."""
from __future__ import annotations

import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - dependency guidance
    raise ImportError(
        "customtkinter is required. Install the project dependencies with "
        "`pip install -r requirements.txt`."
    ) from exc

from config.settings import DEFAULTS
from services import (
    ScanResult,
    download_scan_result,
    get_playlist_option,
    get_video_option,
    scan_url,
)

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:  # pragma: no cover - graceful fallback if Pillow is missing
    Image = None
    ImageDraw = None
    ImageOps = None


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


APP_SHELL = "#080809"
HEADER_BG = "#111214"
SURFACE_BG = "#F1F1F1"
CARD_BG = "#FFFFFF"
CARD_BG_ALT = "#F8F9FC"
CARD_BORDER = "#E4E7EC"
SOFT_BG = "#ECEFF4"
ACCENT_RED = "#FF2B1D"
ACCENT_RED_DARK = "#DE1F13"
TEXT_PRIMARY = "#121826"
TEXT_SECONDARY = "#4B5565"
TEXT_MUTED = "#777A7E"
TEXT_FAINT = "#888E97"
SUCCESS_GREEN = "#15803D"

if Image is not None:
    RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
else:  # pragma: no cover - no Pillow branch
    RESAMPLE = None

def resource_path(relative_path: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


class NestedAwareScrollableFrame(ctk.CTkScrollableFrame):
    """Scrollable frame that ignores wheel input over nested scroll regions."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._blocked_scroll_masters: list[tk.Widget] = []

    def register_nested_scrollable(self, scrollable: ctk.CTkScrollableFrame) -> None:
        parent_frame = getattr(scrollable, "_parent_frame", None)
        if isinstance(parent_frame, tk.Widget):
            self._blocked_scroll_masters.append(parent_frame)

    def _mouse_wheel_all(self, event):
        if any(self._widget_descends_from(event.widget, master) for master in self._blocked_scroll_masters):
            return
        super()._mouse_wheel_all(event)

    def _widget_descends_from(self, widget: object, ancestor: tk.Widget) -> bool:
        current = widget
        while isinstance(current, tk.Widget):
            if current == ancestor:
                return True
            current = current.master
        return False


class YouTubeDownloaderUI(ctk.CTk):
    """Main desktop UI."""

    PREVIEW_SIZE = (384, 216)
    LIST_THUMB_SIZE = (200, 112)
    DETAILS_BREAKPOINT = 1260
    COMPACT_BREAKPOINT = 960

    def __init__(self) -> None:
        super().__init__(fg_color=APP_SHELL)
        self.iconbitmap(resource_path("assets/images/logo.ico"))
        self.title("YouTube Downloader")
        self.geometry("1440x920")
        self.minsize(1040, 760)

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.scan_result: ScanResult | None = None
        self.current_selection: int | None = None
        self.thumbnail_token = 0
        self.preview_item_key: str | None = None
        self.thumbnail_bytes: dict[str, bytes] = {}
        self.thumbnail_images: dict[str, ctk.CTkImage] = {}
        self.playlist_thumbnail_labels: dict[str, ctk.CTkLabel] = {}
        self.playlist_card_frames: dict[str, ctk.CTkFrame] = {}
        self.playlist_title_labels: dict[str, ctk.CTkLabel] = {}
        self.playlist_meta_labels: dict[str, ctk.CTkLabel] = {}
        self.playlist_thumb_frames: dict[str, ctk.CTkFrame] = {}
        self.playlist_indicator_frames: dict[str, ctk.CTkFrame] = {}
        self.format_card_frames: dict[int, ctk.CTkFrame] = {}
        self.format_card_buttons: dict[int, ctk.CTkButton] = {}
        self.format_row_colors: dict[int, str] = {}
        self.is_busy = False
        self.last_open_path = os.path.abspath(DEFAULTS["output_dir"])
        self.asset_font_families = self._load_asset_fonts()

        self.active_screen = "url"
        self.details_layout_mode: str | None = None
        self.url_layout_mode: str | None = None
        self.download_layout_mode: str | None = None
        self.download_actions_mode: str | None = None

        self.url_var = tk.StringVar()
        self.use_cookies_var = tk.BooleanVar(value=DEFAULTS["use_chrome_cookies"])
        self.profile_var = tk.StringVar()
        self.save_dir_var = tk.StringVar(value=os.path.abspath(DEFAULTS["output_dir"]))
        self.url_placeholder = "Paste your link here"
        self.profile_placeholder = "Default / Profile 1 (optional)"
        self.status_var = tk.StringVar(
            value="Paste a YouTube video or playlist URL to scan the available options first."
        )
        self.mode_var = tk.StringVar(value="Ready")
        self.formats_title_var = tk.StringVar(value="Available Formats")
        self.download_label_var = tk.StringVar(value="Download")
        self.preview_caption_var = tk.StringVar(value="Thumbnail preview")
        self.preview_meta_var = tk.StringVar(value="Channel and duration appear here.")
        self.media_support_var = tk.StringVar(value="Playlist and cookie details appear here.")
        self.hero_chip_1_var = tk.StringVar(value="Ready")
        self.hero_chip_2_var = tk.StringVar(value="Details")
        self.hero_chip_3_var = tk.StringVar(value="Preview")
        self.selected_format_var = tk.StringVar(value="No format selected.")
        self.download_summary_var = tk.StringVar(
            value="Choose a format on the details screen to unlock the download step."
        )
        self.progress_percent_var = tk.StringVar(value="0%")
        self.entry_placeholders: dict[ctk.CTkEntry, dict[str, object]] = {}

        self.info_vars = {
            "Title": tk.StringVar(value="-"),
            "Channel": tk.StringVar(value="-"),
            "Duration": tk.StringVar(value="-"),
            "Playlist": tk.StringVar(value="-"),
            "Videos": tk.StringVar(value="-"),
            "Cookies": tk.StringVar(value="-"),
        }
        self.save_dir_var.trace_add("write", lambda *_args: self._update_selected_summary())

        self._build_fonts()
        self._load_static_images()
        self._build_layout()
        self._install_placeholder(self.url_entry, self.url_var, self.url_placeholder)
        self._install_placeholder(self.profile_entry, self.profile_var, self.profile_placeholder)
        self._set_progress(0.0)
        self._clear_results()
        self._sync_cookie_state()
        self._show_screen("url")
        self._update_responsive_layout()

        self.bind("<Configure>", self._on_window_configure)
        self.after(100, self._process_queue)

    def _load_asset_fonts(self) -> set[str]:
        fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
        loaded_families: set[str] = set()
        if not fonts_dir.exists():
            return loaded_families

        for font_path in sorted(fonts_dir.iterdir()):
            if font_path.suffix.lower() not in {".ttf", ".otf"}:
                continue
            try:
                ctk.FontManager.load_font(str(font_path))
            except Exception:
                continue
            loaded_families.add(font_path.stem.split("-", 1)[0].replace("_", " "))

        return loaded_families

    def _pick_font_family(self, *preferred: str, fallback: str = "Segoe UI") -> str:
        for family in preferred:
            if family in self.asset_font_families:
                return family
        return fallback

    def _build_fonts(self) -> None:
        self.family_body = self._pick_font_family("Inter 18pt")
        self.family_heading = self._pick_font_family("Inter 24pt", "Inter 18pt", fallback=self.family_body)
        self.family_display = self._pick_font_family("Inter 28pt", "Inter 24pt", fallback=self.family_heading)

        self.font_brand = ctk.CTkFont(family=self.family_heading, size=18, weight="bold")
        self.font_step = ctk.CTkFont(family=self.family_body, size=13, weight="bold")
        self.font_display = ctk.CTkFont(family="Inter 28pt ExtraBold", size=48)
        self.font_heading = ctk.CTkFont(family=self.family_heading, size=24, weight="bold")
        self.font_title = ctk.CTkFont(family=self.family_heading, size=18, weight="bold")
        self.font_logo = ctk.CTkFont(family=self.family_heading, size=34, weight="bold")
        self.font_media_title = ctk.CTkFont(family=self.family_heading, size=28, weight="bold")
        self.font_media_meta = ctk.CTkFont(family=self.family_body, size=13)
        self.font_subtitle = ctk.CTkFont(family=self.family_body, size=13)
        self.font_body = ctk.CTkFont(family=self.family_body, size=13)
        self.font_body_bold = ctk.CTkFont(family="Inter 24pt Bold", size=20, weight="bold")
        self.font_small = ctk.CTkFont(family=self.family_body, size=12)
        self.font_micro = ctk.CTkFont(family=self.family_body, size=11)
        self.font_input = ctk.CTkFont(family=self.family_body, size=16)
        self.font_console = ctk.CTkFont(family=self.family_body, size=12)
        self.font_table_header = ctk.CTkFont(family=self.family_body, size=11, weight="bold")
        self.font_table_cell = ctk.CTkFont(family=self.family_body, size=12)
        self.font_table_cell_bold = ctk.CTkFont(family=self.family_body, size=12, weight="bold")

    def _load_static_images(self) -> None:
        self.logo_image_large: ctk.CTkImage | None = None
        self.logo_image_small: ctk.CTkImage | None = None
        self.back_button_icon: ctk.CTkImage | None = None
        self.mode_button_icon: ctk.CTkImage | None = None
        if Image is None:
            return

        logo_path = Path(__file__).resolve().parent.parent / "assets" / "images" / "logo.png"
        if not logo_path.exists():
            logo = None
        else:
            try:
                logo = Image.open(logo_path).convert("RGBA")
            except Exception:
                logo = None

        if logo is not None:
            self.logo_image_large = ctk.CTkImage(
                light_image=logo.copy(),
                dark_image=logo.copy(),
                size=(128, 128),
            )
            self.logo_image_small = ctk.CTkImage(
                light_image=logo.copy(),
                dark_image=logo.copy(),
                size=(30, 30),
            )

        self.back_button_icon = self._create_pill_icon("back", circle_color=TEXT_PRIMARY)
        self.mode_button_icon = self._create_pill_icon("play", circle_color=ACCENT_RED)

    def _create_pill_icon(self, kind: str, circle_color: str, glyph_color: str = "white") -> ctk.CTkImage | None:
        if Image is None or ImageDraw is None:
            return None

        icon_size = 34
        canvas = Image.new("RGBA", (icon_size, icon_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((0, 0, icon_size - 1, icon_size - 1), fill=circle_color)

        if kind == "back":
            draw.line((20, 10, 13, 17), fill=glyph_color, width=3)
            draw.line((13, 17, 20, 24), fill=glyph_color, width=3)
            draw.line((14, 17, 24, 17), fill=glyph_color, width=3)
        else:
            draw.polygon(((13, 10), (13, 24), (24, 17)), fill=glyph_color)

        return ctk.CTkImage(light_image=canvas, dark_image=canvas, size=(icon_size, icon_size))

    def _install_placeholder(self, entry: ctk.CTkEntry, variable: tk.StringVar, text: str) -> None:
        self.entry_placeholders[entry] = {
            "variable": variable,
            "text": text,
            "active": False,
        }
        entry.bind("<FocusIn>", lambda _event, target=entry: self._clear_placeholder(target), add="+")
        entry.bind("<FocusOut>", lambda _event, target=entry: self._show_placeholder_if_empty(target), add="+")
        self._show_placeholder_if_empty(entry)

    def _clear_placeholder(self, entry: ctk.CTkEntry) -> None:
        meta = self.entry_placeholders.get(entry)
        if not meta or not bool(meta["active"]):
            return
        meta["active"] = False
        entry.configure(text_color=TEXT_PRIMARY)
        variable = meta["variable"]
        if isinstance(variable, tk.StringVar):
            variable.set("")

    def _show_placeholder_if_empty(self, entry: ctk.CTkEntry) -> None:
        meta = self.entry_placeholders.get(entry)
        if not meta:
            return
        variable = meta["variable"]
        if not isinstance(variable, tk.StringVar):
            return
        if variable.get().strip():
            if bool(meta["active"]) and variable.get().strip() != str(meta["text"]):
                meta["active"] = False
                entry.configure(text_color=TEXT_PRIMARY)
            return
        meta["active"] = True
        entry.configure(text_color=TEXT_FAINT)
        variable.set(str(meta["text"]))

    def _get_entry_value(self, entry: ctk.CTkEntry) -> str:
        meta = self.entry_placeholders.get(entry)
        if not meta:
            return entry.get().strip()
        variable = meta["variable"]
        value = variable.get().strip() if isinstance(variable, tk.StringVar) else entry.get().strip()
        if bool(meta["active"]) and value == str(meta["text"]):
            return ""
        return value

    def _configure_formats_table_grid(self, frame: ctk.CTkFrame) -> None:
        column_specs = (
            (0, 58, 0),
            (1, 88, 0),
            (2, 118, 0),
            (3, 76, 0),
            (4, 86, 0),
            (5, 108, 0),
            (6, 94, 0),
            (7, 220, 1),
            (8, 132, 0),
        )
        for column, minsize, weight in column_specs:
            frame.grid_columnconfigure(column, minsize=minsize, weight=weight)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(
            self,
            fg_color=HEADER_BG,
            corner_radius=12,
            height=56,
        )
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        header.grid_columnconfigure(1, weight=1)

        logo = ctk.CTkFrame(header, fg_color="transparent")
        logo.grid(row=0, column=0, padx=(12, 10), pady=11)
        ctk.CTkLabel(
            logo,
            text="" if self.logo_image_small is not None else "YT",
            image=self.logo_image_small,
            text_color="white",
            font=self.font_step,
        ).grid(row=0, column=0)

        ctk.CTkLabel(
            header,
            text="YouTube Downloader",
            text_color="white",
            font=self.font_brand,
        ).grid(row=0, column=1, sticky="w")

        shell = ctk.CTkFrame(
            self,
            fg_color=SURFACE_BG,
            corner_radius=24,
            
        )
        shell.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self.screen_container = ctk.CTkFrame(shell, fg_color="transparent")
        self.screen_container.grid(row=0, column=0, sticky="nsew", padx=28, pady=28)
        self.screen_container.grid_columnconfigure(0, weight=1)
        self.screen_container.grid_rowconfigure(0, weight=1)

        self.screen_frames: dict[str, ctk.CTkFrame] = {}
        self._build_url_screen()
        self._build_details_screen()
        self._build_progress_screen()

    def _build_url_screen(self) -> None:
        frame = ctk.CTkFrame(self.screen_container, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.screen_frames["url"] = frame

        hero = ctk.CTkFrame(frame, fg_color="transparent")
        hero.grid(row=0, column=0, sticky="nsew")
        hero.grid_columnconfigure(0, weight=1)

        self.hero_logo_label = ctk.CTkLabel(
            hero,
            text="" if self.logo_image_large is not None else "YT",
            image=self.logo_image_large,
            text_color=ACCENT_RED,
            font=self.font_logo,
        )
        self.hero_logo_label.grid(row=0, column=0, pady=(42, 18))

        ctk.CTkLabel(
            hero,
            text="YouTube Video Downloader",
            text_color=TEXT_PRIMARY,
            font=self.font_display,
        ).grid(row=1, column=0, pady=(0, 12))

        ctk.CTkLabel(
            hero,
            text=(
                "Paste a video or playlist link below. The app scans the media first, "
                "shows the exact video or playlist details on the next screen, and keeps "
                "the existing download logic unchanged."
            ),
            text_color=TEXT_MUTED,
            font=self.font_subtitle,
            wraplength=760,
            justify="center",
        ).grid(row=2, column=0, pady=(0, 26))

        self.url_form_card = ctk.CTkFrame(
            hero,
            fg_color="transparent",
            corner_radius=0,
        )
        self.url_form_card.grid(row=3, column=0, sticky="ew", padx=140)
        self.url_form_card.grid_columnconfigure(0, weight=1)

        self.url_input_shell = ctk.CTkFrame(
            self.url_form_card,
            fg_color=ACCENT_RED,
            corner_radius=0,
        )
        self.url_input_shell.grid(row=0, column=0, sticky="ew")
        self.url_input_shell.grid_columnconfigure(0, weight=1)

        self.url_input_row = ctk.CTkFrame(
            self.url_input_shell,
            fg_color="transparent",
        )
        self.url_input_row.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.url_input_row.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            self.url_input_row,
            textvariable=self.url_var,
            placeholder_text="",
            height=56,
            corner_radius=0,
            border_width=0,
            fg_color=CARD_BG,
            text_color=TEXT_PRIMARY,
            placeholder_text_color=TEXT_FAINT,
            font=self.font_input,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda _event: self._on_scan())

        self.scan_button = ctk.CTkButton(
            self.url_input_row,
            text="Download",
            command=self._on_scan,
            height=56,
            width=190,
            corner_radius=0,
            fg_color=ACCENT_RED,
            hover_color=ACCENT_RED_DARK,
            font=self.font_body_bold,
        )
        self.scan_button.grid(row=0, column=1, padx=(14, 0))

        options_card = ctk.CTkFrame(
            self.url_form_card,
            fg_color=CARD_BG_ALT,
            corner_radius=18,
            border_width=1,
            border_color=CARD_BORDER,
        )
        options_card.grid(row=1, column=0, sticky="ew", pady=(18, 14))
        options_card.grid_columnconfigure(2, weight=1)

        self.cookies_switch = ctk.CTkSwitch(
            options_card,
            text="Use browser cookies",
            variable=self.use_cookies_var,
            command=self._sync_cookie_state,
            progress_color=ACCENT_RED,
            button_color="white",
            button_hover_color="#F7F7F7",
            text_color=TEXT_PRIMARY,
            font=self.font_body,
        )
        self.cookies_switch.grid(row=0, column=0, sticky="w", padx=18, pady=16)

        ctk.CTkLabel(
            options_card,
            text="Chrome profile",
            text_color=TEXT_MUTED,
            font=self.font_small,
        ).grid(row=0, column=1, sticky="e", padx=(8, 10))

        self.profile_entry = ctk.CTkEntry(
            options_card,
            textvariable=self.profile_var,
            placeholder_text="",
            width=220,
            height=42,
            corner_radius=14,
            border_width=1,
            border_color=CARD_BORDER,
            fg_color=CARD_BG,
            text_color=TEXT_PRIMARY,
        )
        self.profile_entry.grid(row=0, column=2, sticky="ew", padx=(0, 18), pady=14)

        self.scan_console_card = ctk.CTkFrame(
            self.url_form_card,
            fg_color="#0C111B",
            corner_radius=18,
            border_width=1,
            border_color="#272727",
        )
        self.scan_console_card.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        self.scan_console_card.grid_columnconfigure(0, weight=1)
        self.scan_console_card.grid_rowconfigure(1, weight=1)

        console_header = ctk.CTkFrame(self.scan_console_card, fg_color="transparent")
        console_header.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 8))
        console_header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            console_header,
            text="Logs",
            text_color="#E4E6EB",
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            console_header,
            text="Live scan and download events",
            text_color="#7C8AA5",
            font=self.font_micro,
        ).grid(row=0, column=1, sticky="e")

        self.scan_console_text = ctk.CTkTextbox(
            self.scan_console_card,
            fg_color="#0A0F18",
            border_width=1,
            border_color="#1C2534",
            corner_radius=14,
            text_color="#A7F3D0",
            font=self.font_console,
            wrap="word",
            height=170,
        )
        self.scan_console_text.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 18))
        self.scan_console_text.configure(state="disabled")

    def _build_details_screen(self) -> None:
        frame = NestedAwareScrollableFrame(
            self.screen_container,
            fg_color="transparent",
            scrollbar_button_color="#C8CED8",
            scrollbar_button_hover_color="#B8C0CC",
        )
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        self.screen_frames["details"] = frame

        self.details_content = ctk.CTkFrame(frame, fg_color="transparent")
        self.details_content.grid(row=0, column=0, sticky="ew", padx=(0, 18))
        self.details_content.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.details_content, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.grid_columnconfigure(1, weight=1)

        self.back_to_url_button = ctk.CTkButton(
            header,
            text="Back",
            command=lambda: self._show_screen("url"),
            image=self.back_button_icon,
            compound="left",
            anchor="w",
            border_spacing=0,
            width=128,
            height=50,
            corner_radius=24,
            border_width=0,
            border_color="#E5E7EB",
            fg_color="#F8F9FB",
            hover_color="#EEF1F5",
            text_color=TEXT_PRIMARY,
            text_color_disabled="#6B7280",
            font=self.font_title,
        )
        self.back_to_url_button.grid(row=0, column=0, padx=(0, 12))

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            title_wrap,
            text="Review Media Details",
            text_color=TEXT_PRIMARY,
            font=self.font_heading,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_wrap,
            text="Inspect the thumbnail, playlist items, and format rows before moving to download.",
            text_color=TEXT_MUTED,
            font=self.font_small,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.mode_badge = ctk.CTkFrame(
            header,
            fg_color="#FFF1EE",
            corner_radius=24,
            border_width=0,
            border_color="#FFD7D1",
        )
        self.mode_badge.grid(row=0, column=2, sticky="e")
        self.mode_badge.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.mode_badge,
            text="" if self.mode_button_icon is not None else ">",
            image=self.mode_button_icon,
            width=34,
            text_color="white",
            font=self.font_body_bold,
        ).grid(row=0, column=0, padx=(10, 8), pady=8)
        ctk.CTkLabel(
            self.mode_badge,
            textvariable=self.mode_var,
            text_color=ACCENT_RED_DARK,
            font=self.font_title,
        ).grid(row=0, column=1, padx=(0, 16), pady=10, sticky="w")

        self.details_grid = ctk.CTkFrame(self.details_content, fg_color="transparent")
        self.details_grid.grid(row=1, column=0, sticky="ew")
        self.details_grid.grid_columnconfigure(0, weight=1)
        self.details_grid.grid_rowconfigure(0, weight=0)
        self.details_grid.grid_rowconfigure(1, weight=0)

        self.media_card = ctk.CTkFrame(
            self.details_grid,
            fg_color=CARD_BG,
            corner_radius=24,
            border_width=0,
            border_color=CARD_BORDER,
        )
        self.media_card.grid(row=0, column=0, sticky="ew")
        self.media_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.media_card,
            text="Media Overview",
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        self.media_hero = ctk.CTkFrame(
            self.media_card,
            fg_color="#171C25",
            corner_radius=30,
            border_width=0,
        )
        self.media_hero.grid(row=1, column=0, sticky="ew", padx=20, pady=(4, 12))
        self.media_hero.grid_columnconfigure(0, weight=1)
        self.media_hero.grid_columnconfigure(1, weight=0)

        media_text_frame = ctk.CTkFrame(self.media_hero, fg_color="transparent")
        media_text_frame.grid(row=0, column=0, sticky="nsew", padx=(28, 18), pady=28)
        media_text_frame.grid_columnconfigure(0, weight=1)

        self.hero_mode_label = ctk.CTkLabel(
            media_text_frame,
            textvariable=self.mode_var,
            text_color="#6FB1FF",
            font=self.font_micro,
            anchor="w",
        )
        self.hero_mode_label.grid(row=0, column=0, sticky="w")

        self.hero_title_label = ctk.CTkLabel(
            media_text_frame,
            textvariable=self.preview_caption_var,
            text_color="#F7FAFC",
            font=self.font_media_title,
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.hero_title_label.grid(row=1, column=0, sticky="w", pady=(8, 10))

        self.hero_meta_label = ctk.CTkLabel(
            media_text_frame,
            textvariable=self.preview_meta_var,
            text_color="#D7E1F0",
            font=self.font_media_meta,
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.hero_meta_label.grid(row=2, column=0, sticky="w")

        self.hero_support_label = ctk.CTkLabel(
            media_text_frame,
            textvariable=self.media_support_var,
            text_color="#91A0B8",
            font=self.font_small,
            anchor="w",
            justify="left",
            wraplength=460,
        )
        self.hero_support_label.grid(row=3, column=0, sticky="w", pady=(10, 16))

        hero_chip_row = ctk.CTkFrame(media_text_frame, fg_color="transparent")
        hero_chip_row.grid(row=4, column=0, sticky="w")

        self.hero_chip_1_label = ctk.CTkLabel(
            hero_chip_row,
            textvariable=self.hero_chip_1_var,
            text_color="#E4ECF7",
            font=self.font_micro,
            fg_color="#223148",
            corner_radius=14,
            padx=12,
            pady=6,
        )
        self.hero_chip_1_label.grid(row=0, column=0, padx=(0, 8))

        self.hero_chip_2_label = ctk.CTkLabel(
            hero_chip_row,
            textvariable=self.hero_chip_2_var,
            text_color="#E4ECF7",
            font=self.font_micro,
            fg_color="#223148",
            corner_radius=14,
            padx=12,
            pady=6,
        )
        self.hero_chip_2_label.grid(row=0, column=1, padx=(0, 8))

        self.hero_chip_3_label = ctk.CTkLabel(
            hero_chip_row,
            textvariable=self.hero_chip_3_var,
            text_color="#E4ECF7",
            font=self.font_micro,
            fg_color="#223148",
            corner_radius=14,
            padx=12,
            pady=6,
        )
        self.hero_chip_3_label.grid(row=0, column=2)

        self.preview_frame = ctk.CTkFrame(
            self.media_hero,
            fg_color="transparent",
            corner_radius=0,
            border_width=0,
            width=self.PREVIEW_SIZE[0],
            height=self.PREVIEW_SIZE[1],
        )
        self.preview_frame.grid(row=0, column=1, sticky="e", padx=(0, 28), pady=28)
        self.preview_frame.grid_propagate(False)

        self.preview_label = ctk.CTkLabel(
            self.preview_frame,
            text="Thumbnail preview",
            text_color="#9AA3B2",
            font=self.font_body,
            fg_color=SOFT_BG,
            corner_radius=0,
            width=self.PREVIEW_SIZE[0],
            height=self.PREVIEW_SIZE[1],
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        self.playlist_section = ctk.CTkFrame(
            self.media_card,
            fg_color="transparent",
            corner_radius=0,
        )
        self.playlist_section.grid(row=2, column=0, sticky="ew", padx=20, pady=(18, 20))
        self.playlist_section.grid_columnconfigure(0, weight=1)
        self.playlist_section.grid_rowconfigure(1, weight=1)

        playlist_header = ctk.CTkFrame(self.playlist_section, fg_color="transparent")
        playlist_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        playlist_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            playlist_header,
            text="Playlist Queue",
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            playlist_header,
            text="Pick an item to refresh the preview above.",
            text_color=TEXT_MUTED,
            font=self.font_micro,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.playlist_scroll = ctk.CTkFrame(
            self.playlist_section,
            fg_color="transparent",
            corner_radius=0,
        )
        self.playlist_scroll.grid(row=1, column=0, sticky="ew")
        self.playlist_empty_label = ctk.CTkLabel(
            self.playlist_scroll,
            text="Playlist items appear here after scanning a playlist.",
            text_color=TEXT_MUTED,
            font=self.font_body,
        )
        self.playlist_empty_label.grid(row=0, column=0, sticky="ew", pady=28)

        self.formats_card = ctk.CTkFrame(
            self.details_grid,
            fg_color=CARD_BG,
            corner_radius=24,
            border_width=0,
            border_color=CARD_BORDER,
        )
        self.formats_card.grid(row=1, column=0, sticky="nsew", pady=(20, 0))
        self.formats_card.grid_columnconfigure(0, weight=1)
        self.formats_card.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self.formats_card,
            textvariable=self.formats_title_var,
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 4))

        ctk.CTkLabel(
            self.formats_card,
            text="Select one table row and continue.",
            text_color=TEXT_MUTED,
            font=self.font_small,
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        self.formats_table_header = ctk.CTkFrame(
            self.formats_card,
            fg_color="#EEF2F7",
            corner_radius=12,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.formats_table_header.grid(row=2, column=0, sticky="ew", padx=12)
        self._configure_formats_table_grid(self.formats_table_header)

        for column, label in enumerate(
            ("#", "Type", "Resolution", "Ext", "FPS", "Audio", "Size", "Details", "Action")
        ):
            anchor = "w" if column == 7 else "center"
            padx = (12, 8) if column == 7 else 6
            ctk.CTkLabel(
                self.formats_table_header,
                text=label,
                text_color=TEXT_FAINT,
                font=self.font_table_header,
                anchor=anchor,
            ).grid(row=0, column=column, sticky="ew", padx=padx, pady=10)

        self.formats_scroll = ctk.CTkScrollableFrame(
            self.formats_card,
            fg_color="transparent",
            corner_radius=8,
            scrollbar_button_color="#C8CED8",
            scrollbar_button_hover_color="#B8C0CC",
            height=520,
        )
        self.formats_scroll.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 0))
        self.formats_scroll.grid_columnconfigure(0, weight=1)
        self.formats_empty_label = ctk.CTkLabel(
            self.formats_scroll,
            text="Scan a URL to load the available download options.",
            text_color=TEXT_MUTED,
            font=self.font_body,
        )
        self.formats_empty_label.grid(row=0, column=0, sticky="ew", pady=36)
        frame.register_nested_scrollable(self.formats_scroll)

        footer = ctk.CTkFrame(self.formats_card, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=20, pady=(12, 20))
        footer.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            footer,
            textvariable=self.selected_format_var,
            text_color=TEXT_MUTED,
            font=self.font_small,
            justify="left",
            wraplength=520,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 12))

        self.details_next_button = ctk.CTkButton(
            footer,
            text="Continue",
            command=self._open_download_screen,
            width=160,
            height=48,
            corner_radius=18,
            fg_color=ACCENT_RED,
            hover_color=ACCENT_RED_DARK,
            font=self.font_body_bold,
        )
        self.details_next_button.grid(row=0, column=1, sticky="e")

    def _build_progress_screen(self) -> None:
        frame = ctk.CTkFrame(self.screen_container, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        self.screen_frames["download"] = frame

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.grid_columnconfigure(1, weight=1)

        self.back_to_details_button = ctk.CTkButton(
            header,
            text="Back",
            command=lambda: self._show_screen("details"),
            image=self.back_button_icon,
            compound="left",
            anchor="w",
            border_spacing=10,
            width=156,
            height=50,
            corner_radius=25,
            border_width=1,
            border_color="#E5E7EB",
            fg_color="#F8F9FB",
            hover_color="#EEF1F5",
            text_color=TEXT_PRIMARY,
            text_color_disabled="#6B7280",
            font=self.font_title,
        )
        self.back_to_details_button.grid(row=0, column=0, padx=(0, 14))

        title_wrap = ctk.CTkFrame(header, fg_color="transparent")
        title_wrap.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            title_wrap,
            text="Download Details",
            text_color=TEXT_PRIMARY,
            font=self.font_heading,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_wrap,
            text="Choose the save folder, start the download, and monitor the live log.",
            text_color=TEXT_MUTED,
            font=self.font_small,
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.download_top_grid = ctk.CTkFrame(frame, fg_color="transparent")
        self.download_top_grid.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        for column in range(2):
            self.download_top_grid.grid_columnconfigure(column, weight=1)

        self.download_setup_card = ctk.CTkFrame(
            self.download_top_grid,
            fg_color=CARD_BG,
            corner_radius=24,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.download_setup_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.download_setup_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.download_setup_card,
            text="Save Location",
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        self.save_dir_entry = ctk.CTkEntry(
            self.download_setup_card,
            textvariable=self.save_dir_var,
            placeholder_text="Choose a folder to save downloads",
            height=48,
            corner_radius=16,
            border_width=1,
            border_color=CARD_BORDER,
            fg_color=CARD_BG_ALT,
            text_color=TEXT_PRIMARY,
            font=self.font_body,
        )
        self.save_dir_entry.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))

        self.download_actions = ctk.CTkFrame(self.download_setup_card, fg_color="transparent")
        self.download_actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        for column in range(3):
            self.download_actions.grid_columnconfigure(column, weight=1)

        self.browse_button = ctk.CTkButton(
            self.download_actions,
            text="Browse",
            command=self._pick_folder,
            height=44,
            corner_radius=16,
            fg_color="#EEF2F7",
            hover_color="#E3E9F1",
            text_color=TEXT_PRIMARY,
            font=self.font_body_bold,
        )
        self.browse_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.open_folder_button = ctk.CTkButton(
            self.download_actions,
            text="Open Folder",
            command=self._open_folder,
            height=44,
            corner_radius=16,
            fg_color=TEXT_PRIMARY,
            hover_color="#1D2636",
            text_color="white",
            font=self.font_body_bold,
        )
        self.open_folder_button.grid(row=0, column=1, sticky="ew", padx=8)

        self.download_button = ctk.CTkButton(
            self.download_actions,
            textvariable=self.download_label_var,
            command=self._on_download,
            height=44,
            corner_radius=16,
            fg_color=ACCENT_RED,
            hover_color=ACCENT_RED_DARK,
            font=self.font_body_bold,
        )
        self.download_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        self.download_summary_card = ctk.CTkFrame(
            self.download_top_grid,
            fg_color=CARD_BG,
            corner_radius=24,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.download_summary_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.download_summary_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.download_summary_card,
            text="Selected Format",
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        ctk.CTkLabel(
            self.download_summary_card,
            textvariable=self.download_summary_var,
            text_color=TEXT_MUTED,
            font=self.font_body,
            justify="left",
            wraplength=480,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 20))

        self.progress_card = ctk.CTkFrame(
            frame,
            fg_color=CARD_BG,
            corner_radius=24,
            border_width=1,
            border_color=CARD_BORDER,
        )
        self.progress_card.grid(row=2, column=0, sticky="nsew")
        self.progress_card.grid_columnconfigure(0, weight=1)
        self.progress_card.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self.progress_card,
            text="Progress",
            text_color=TEXT_PRIMARY,
            font=self.font_title,
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        bar_wrap = ctk.CTkFrame(self.progress_card, fg_color="transparent")
        bar_wrap.grid(row=1, column=0, sticky="ew", padx=20)
        bar_wrap.grid_columnconfigure(0, weight=1)
        self.progress_bar = ctk.CTkProgressBar(
            bar_wrap,
            height=18,
            corner_radius=10,
            progress_color=ACCENT_RED,
            fg_color="#E8EBF2",
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            bar_wrap,
            textvariable=self.progress_percent_var,
            text_color=TEXT_SECONDARY,
            font=self.font_body_bold,
            width=46,
        ).grid(row=0, column=1, padx=(12, 0))

        ctk.CTkLabel(
            self.progress_card,
            textvariable=self.status_var,
            text_color=TEXT_MUTED,
            font=self.font_body,
            wraplength=1080,
            justify="left",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=20, pady=(12, 10))

        self.log_text = ctk.CTkTextbox(
            self.progress_card,
            fg_color=CARD_BG_ALT,
            border_width=1,
            border_color=CARD_BORDER,
            corner_radius=18,
            text_color=TEXT_PRIMARY,
            font=self.font_small,
            wrap="word",
        )
        self.log_text.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.log_text.configure(state="disabled")

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is self:
            self.after_idle(self._update_responsive_layout)

    def _update_responsive_layout(self) -> None:
        width = max(self.winfo_width(), 1)

        if width >= 1400:
            url_pad = 180
        elif width >= 1200:
            url_pad = 140
        elif width >= 1000:
            url_pad = 90
        else:
            url_pad = 36
        self.url_form_card.grid_configure(padx=url_pad)

        details_mode = "stacked"
        if details_mode != self.details_layout_mode:
            self.details_layout_mode = details_mode
            self.media_card.grid_forget()
            self.formats_card.grid_forget()
            self.details_grid.grid_columnconfigure(0, weight=1)
            self.details_grid.grid_columnconfigure(1, weight=0)
            self.details_grid.grid_rowconfigure(0, weight=0)
            self.details_grid.grid_rowconfigure(1, weight=0)
            self.media_card.grid(row=0, column=0, sticky="ew", padx=0)
            self.formats_card.grid(row=1, column=0, sticky="ew", padx=0, pady=(20, 0))

        url_mode = "stacked" if width < self.COMPACT_BREAKPOINT else "inline"
        if url_mode != self.url_layout_mode:
            self.url_layout_mode = url_mode
            self.scan_button.grid_forget()
            if url_mode == "inline":
                self.url_input_row.grid_columnconfigure(1, weight=0)
                self.scan_button.grid(row=0, column=1, padx=(14, 0), pady=0, sticky="ew")
            else:
                self.url_input_row.grid_columnconfigure(1, weight=1)
                self.scan_button.grid(row=1, column=0, columnspan=2, padx=0, pady=(14, 0), sticky="ew")

        download_mode = "stacked" if width < self.DETAILS_BREAKPOINT else "split"
        if download_mode != self.download_layout_mode:
            self.download_layout_mode = download_mode
            self.download_setup_card.grid_forget()
            self.download_summary_card.grid_forget()
            self.download_top_grid.grid_columnconfigure(0, weight=1)
            self.download_top_grid.grid_columnconfigure(1, weight=0)
            self.download_top_grid.grid_rowconfigure(0, weight=1)
            self.download_top_grid.grid_rowconfigure(1, weight=0)
            if download_mode == "split":
                self.download_top_grid.grid_columnconfigure(1, weight=1)
                self.download_setup_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
                self.download_summary_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
            else:
                self.download_top_grid.grid_rowconfigure(1, weight=1)
                self.download_setup_card.grid(row=0, column=0, sticky="ew", padx=0)
                self.download_summary_card.grid(row=1, column=0, sticky="ew", padx=0, pady=(20, 0))

        actions_mode = "stacked" if width < 1100 else "inline"
        if actions_mode != self.download_actions_mode:
            self.download_actions_mode = actions_mode
            for widget in (self.browse_button, self.open_folder_button, self.download_button):
                widget.grid_forget()
            if actions_mode == "inline":
                for column in range(3):
                    self.download_actions.grid_columnconfigure(column, weight=1)
                self.browse_button.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=0)
                self.open_folder_button.grid(row=0, column=1, sticky="ew", padx=8, pady=0)
                self.download_button.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=0)
            else:
                self.browse_button.grid(row=0, column=0, columnspan=3, sticky="ew", padx=0, pady=(0, 8))
                self.open_folder_button.grid(row=1, column=0, columnspan=3, sticky="ew", padx=0, pady=8)
                self.download_button.grid(row=2, column=0, columnspan=3, sticky="ew", padx=0, pady=(8, 0))

    def _sync_cookie_state(self) -> None:
        state = "normal" if self.use_cookies_var.get() else "disabled"
        self.profile_entry.configure(state=state)

    def _show_screen(self, name: str) -> None:
        for frame in self.screen_frames.values():
            frame.grid_remove()
        self.screen_frames[name].grid()
        self.active_screen = name
        self._update_action_states()

    def _set_progress(self, percent: float) -> None:
        clamped = max(0.0, min(100.0, float(percent)))
        self.progress_bar.set(clamped / 100.0)
        self.progress_percent_var.set(f"{int(round(clamped))}%")

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        state = "disabled" if busy else "normal"

        self.scan_button.configure(state=state)
        self.cookies_switch.configure(state=state)
        self.profile_entry.configure(state=state if not busy and self.use_cookies_var.get() else "disabled")
        self.browse_button.configure(state=state)
        self.open_folder_button.configure(state=state)
        self.back_to_url_button.configure(state=state)
        self.back_to_details_button.configure(state=state)
        self.save_dir_entry.configure(state=state)
        self.details_next_button.configure(
            state="disabled" if busy or self.scan_result is None or self.current_selection is None else "normal"
        )
        self.download_button.configure(
            state="disabled" if busy or self.scan_result is None or self.current_selection is None else "normal"
        )

        for button in self.format_card_buttons.values():
            button.configure(state=state)

    def _update_action_states(self) -> None:
        can_continue = self.scan_result is not None and self.current_selection is not None and not self.is_busy
        self.details_next_button.configure(state="normal" if can_continue else "disabled")
        self.download_button.configure(state="normal" if can_continue else "disabled")

    def _on_scan(self) -> None:
        url = self._get_entry_value(self.url_entry)
        if not url:
            messagebox.showerror("Missing URL", "Paste a YouTube video or playlist URL first.")
            return

        self.scan_result = None
        self.current_selection = None
        self.thumbnail_token += 1
        self.preview_item_key = None
        self._set_progress(0.0)
        self.status_var.set("Scanning URL...")
        self._clear_results()
        self.thumbnail_bytes.clear()
        self.thumbnail_images.clear()
        self.playlist_thumbnail_labels.clear()
        self.playlist_card_frames.clear()
        self.playlist_title_labels.clear()
        self.playlist_meta_labels.clear()
        self.playlist_thumb_frames.clear()
        self.playlist_indicator_frames.clear()
        self.format_card_frames.clear()
        self.format_card_buttons.clear()
        self._append_log(f"Scanning: {url}")
        self._set_busy(True)
        self._show_screen("url")

        worker = threading.Thread(
            target=self._scan_worker,
            args=(
                self.thumbnail_token,
                url,
                self.use_cookies_var.get(),
                self._get_entry_value(self.profile_entry) or None,
                self.save_dir_var.get().strip() or None,
            ),
            daemon=True,
        )
        worker.start()

    def _scan_worker(
        self,
        token: int,
        url: str,
        use_cookies: bool,
        chrome_profile: str | None,
        output_dir: str | None,
    ) -> None:
        try:
            result = scan_url(
                url=url,
                use_chrome_cookies=use_cookies,
                chrome_profile=chrome_profile,
                output_dir=output_dir,
                logger=self._queue_log,
            )
            self.ui_queue.put(("scan-success", (token, result)))
            self._queue_thumbnail_jobs(token, result)
        except Exception as exc:
            self.ui_queue.put(("scan-error", str(exc)))

    def _open_download_screen(self) -> None:
        if self.scan_result is None or self.current_selection is None:
            messagebox.showerror("No format selected", "Scan a URL and choose a format before continuing.")
            return
        self._update_selected_summary()
        self._show_screen("download")

    def _on_download(self) -> None:
        if self.scan_result is None or self.current_selection is None:
            messagebox.showerror("No format selected", "Scan a URL and choose a format before downloading.")
            return

        output_dir = self.save_dir_var.get().strip()
        if not output_dir:
            messagebox.showerror("Missing save folder", "Pick a save folder before downloading.")
            return

        self._set_progress(0.0)
        self.status_var.set("Preparing download...")
        self._append_log("Starting download...")
        self._set_busy(True)
        self._show_screen("download")

        worker = threading.Thread(
            target=self._download_worker,
            args=(self.scan_result, self.current_selection, output_dir),
            daemon=True,
        )
        worker.start()

    def _download_worker(self, result: ScanResult, option_number: int, output_dir: str) -> None:
        try:
            summary = download_scan_result(
                scan_result=result,
                option_number=option_number,
                output_dir=output_dir,
                logger=self._queue_log,
                progress_callback=self._queue_progress,
            )
            self.ui_queue.put(("download-success", summary))
        except Exception as exc:
            self.ui_queue.put(("download-error", str(exc)))

    def _pick_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.save_dir_var.get() or os.getcwd())
        if selected:
            self.save_dir_var.set(selected)
            self.last_open_path = selected
            self._update_selected_summary()

    def _open_folder(self) -> None:
        folder = self.last_open_path or self.save_dir_var.get().strip() or os.getcwd()
        folder = os.path.abspath(folder)
        if not os.path.exists(folder):
            messagebox.showerror("Folder Not Found", f"The folder does not exist:\n{folder}")
            return

        if sys.platform.startswith("win"):
            os.startfile(folder)
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", folder])
            return
        subprocess.Popen(["xdg-open", folder])

    def _clear_results(self) -> None:
        self.mode_var.set("Ready")
        self._reset_media_copy()
        self.formats_title_var.set("Available Formats")
        self.download_label_var.set("Download")
        self.selected_format_var.set("No format selected.")
        self.download_summary_var.set(
            "Choose a format on the details screen to unlock the download step."
        )

        self._reset_preview()

        for info_var in self.info_vars.values():
            info_var.set("-")

        for child in self.playlist_scroll.winfo_children():
            child.destroy()
        self.playlist_thumbnail_labels.clear()
        self.playlist_card_frames.clear()
        self.playlist_title_labels.clear()
        self.playlist_meta_labels.clear()
        self.playlist_thumb_frames.clear()
        self.playlist_indicator_frames.clear()
        self.playlist_empty_label = ctk.CTkLabel(
            self.playlist_scroll,
            text="Playlist items appear here after scanning a playlist.",
            text_color=TEXT_MUTED,
            font=self.font_body,
        )
        self.playlist_empty_label.grid(row=0, column=0, sticky="ew", pady=28)

        for child in self.formats_scroll.winfo_children():
            child.destroy()
        self.formats_empty_label = ctk.CTkLabel(
            self.formats_scroll,
            text="Scan a URL to load the available download options.",
            text_color=TEXT_MUTED,
            font=self.font_body,
        )
        self.formats_empty_label.grid(row=0, column=0, sticky="ew", pady=36)

        self.playlist_section.grid_remove()
        self._update_action_states()

    def _reset_media_copy(self) -> None:
        self.preview_caption_var.set("Thumbnail preview")
        self.preview_meta_var.set("Channel and duration appear here.")
        self.media_support_var.set("Playlist and cookie details appear here.")
        self.hero_chip_1_var.set("Ready")
        self.hero_chip_2_var.set("Details")
        self.hero_chip_3_var.set("Preview")

    def _set_video_media_copy(self, result: ScanResult) -> None:
        meta_parts = [result.channel]
        if result.duration_text and result.duration_text != "-":
            meta_parts.append(result.duration_text)

        self.preview_caption_var.set(result.title)
        self.preview_meta_var.set(" | ".join(part for part in meta_parts if part and part != "-"))
        self.media_support_var.set(result.cookie_text)
        self.hero_chip_1_var.set("Video")
        self.hero_chip_2_var.set(f"{len(result.all_video_options)} formats")
        self.hero_chip_3_var.set(result.duration_text if result.duration_text != "-" else "Ready")

    def _set_playlist_media_copy(self, result: ScanResult, index: int) -> None:
        if not result.playlist_entries:
            self.preview_caption_var.set(result.title)
            self.preview_meta_var.set(result.channel)
            self.media_support_var.set(
                f"{result.video_count} videos | {result.cookie_text}"
            )
            self.hero_chip_1_var.set("Playlist")
            self.hero_chip_2_var.set(f"{result.video_count} videos")
            self.hero_chip_3_var.set("Queue")
            return

        entry = result.playlist_entries[index]
        meta_parts = [entry.channel]
        if entry.duration_text and entry.duration_text != "unknown":
            meta_parts.append(entry.duration_text)
        meta_parts.append(f"Item {index + 1} of {result.video_count}")

        self.preview_caption_var.set(entry.title)
        self.preview_meta_var.set(" | ".join(part for part in meta_parts if part and part != "-"))
        self.media_support_var.set(
            f"{result.title} | {result.video_count} videos | {result.cookie_text}"
        )
        self.hero_chip_1_var.set("Playlist")
        self.hero_chip_2_var.set(f"{result.video_count} videos")
        self.hero_chip_3_var.set(f"Now showing #{index + 1}")

    def _apply_scan_result(self, result: ScanResult) -> None:
        self.scan_result = result
        self.save_dir_var.set(result.output_dir)
        self.last_open_path = result.output_dir

        self.mode_var.set("Playlist" if result.mode == "playlist" else "Single Video")
        self.info_vars["Title"].set(result.title)
        self.info_vars["Channel"].set(result.channel)
        self.info_vars["Duration"].set(result.duration_text)
        self.info_vars["Playlist"].set(result.title if result.mode == "playlist" else "-")
        self.info_vars["Videos"].set(str(result.video_count) if result.mode == "playlist" else "1")
        self.info_vars["Cookies"].set(result.cookie_text)

        if result.mode == "playlist":
            self.formats_title_var.set("Common Playlist Formats")
            self.download_label_var.set("Download Playlist")
            self.playlist_section.grid()
            self._populate_playlist(result)
            self._populate_formats(result.common_options)
            if result.playlist_entries:
                self.preview_item_key = "playlist:0"
                self._set_playlist_media_copy(result, 0)
                self._refresh_playlist_selection_styles("playlist:0")
                self._render_preview(self.preview_item_key)
            else:
                self._set_playlist_media_copy(result, 0)
        else:
            self.formats_title_var.set("Available Formats")
            self.download_label_var.set("Download")
            self._populate_formats(result.all_video_options)
            self.preview_item_key = "video"
            self._set_video_media_copy(result)
            self._render_preview(self.preview_item_key)

        self.status_var.set("Scan complete. Choose a format to continue.")
        self._update_selected_summary()
        self._set_busy(False)
        self._show_screen("details")

    def _populate_formats(self, options: list[object]) -> None:
        for child in self.formats_scroll.winfo_children():
            child.destroy()
        self.format_card_frames.clear()
        self.format_card_buttons.clear()
        self.format_row_colors.clear()

        if not options:
            self.formats_empty_label = ctk.CTkLabel(
                self.formats_scroll,
                text="No formats were found for this media.",
                text_color=TEXT_MUTED,
                font=self.font_body,
            )
            self.formats_empty_label.grid(row=0, column=0, sticky="ew", pady=36)
            self.current_selection = None
            self._update_action_states()
            return

        for row, option in enumerate(options):
            self._create_format_card(row, option)

        first = int(getattr(options[0], "number"))
        self._select_format(first)

    def _create_format_card(self, row: int, option: object) -> None:
        number = int(getattr(option, "number"))
        base_color = CARD_BG if row % 2 == 0 else "#F8FAFD"
        frame = ctk.CTkFrame(
            self.formats_scroll,
            fg_color=base_color,
            corner_radius=0,
            border_width=1,
            border_color=CARD_BORDER,
        )
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 1))
        self._configure_formats_table_grid(frame)

        badge = ctk.CTkLabel(
            frame,
            text=str(number),
            width=38,
            height=34,
            corner_radius=10,
            fg_color="#E9EEF6",
            text_color=TEXT_PRIMARY,
            font=self.font_table_cell_bold,
        )
        badge.grid(row=0, column=0, padx=10, pady=10)

        kind_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "kind")),
            text_color=TEXT_PRIMARY,
            font=self.font_table_cell_bold,
            anchor="center",
        )
        kind_label.grid(row=0, column=1, sticky="ew", padx=6, pady=12)

        resolution_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "resolution")),
            text_color=TEXT_PRIMARY,
            font=self.font_table_cell,
            anchor="center",
        )
        resolution_label.grid(row=0, column=2, sticky="ew", padx=6, pady=12)

        ext_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "extension")).upper(),
            text_color=TEXT_PRIMARY,
            font=self.font_table_cell,
            anchor="center",
        )
        ext_label.grid(row=0, column=3, sticky="ew", padx=6, pady=12)

        fps_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "fps_text")),
            text_color=TEXT_SECONDARY,
            font=self.font_table_cell,
            anchor="center",
        )
        fps_label.grid(row=0, column=4, sticky="ew", padx=6, pady=12)

        audio_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "audio_text")),
            text_color=TEXT_SECONDARY,
            font=self.font_table_cell,
            anchor="center",
        )
        audio_label.grid(row=0, column=5, sticky="ew", padx=6, pady=12)

        size_label = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "size_text")),
            text_color=TEXT_SECONDARY,
            font=self.font_table_cell,
            anchor="center",
        )
        size_label.grid(row=0, column=6, sticky="ew", padx=6, pady=12)

        details = ctk.CTkLabel(
            frame,
            text=str(getattr(option, "detail_text")),
            text_color=TEXT_MUTED,
            font=self.font_table_cell,
            anchor="w",
            justify="left",
            wraplength=280,
        )
        details.grid(row=0, column=7, sticky="ew", padx=(12, 8), pady=12)

        button = ctk.CTkButton(
            frame,
            text="Select",
            command=lambda selected=number: self._select_format(selected),
            width=110,
            height=34,
            corner_radius=10,
            fg_color="#EDEFF4",
            hover_color="#E3E7EF",
            text_color=TEXT_PRIMARY,
            font=self.font_table_cell_bold,
        )
        button.grid(row=0, column=8, padx=(6, 12), pady=10, sticky="e")

        self._bind_select(frame, lambda selected=number: self._select_format(selected))
        self._bind_select(kind_label, lambda selected=number: self._select_format(selected))
        self._bind_select(resolution_label, lambda selected=number: self._select_format(selected))
        self._bind_select(ext_label, lambda selected=number: self._select_format(selected))
        self._bind_select(fps_label, lambda selected=number: self._select_format(selected))
        self._bind_select(audio_label, lambda selected=number: self._select_format(selected))
        self._bind_select(size_label, lambda selected=number: self._select_format(selected))
        self._bind_select(details, lambda selected=number: self._select_format(selected))
        self._bind_select(badge, lambda selected=number: self._select_format(selected))

        self.format_card_frames[number] = frame
        self.format_card_buttons[number] = button
        self.format_row_colors[number] = base_color

    def _populate_playlist(self, result: ScanResult) -> None:
        for child in self.playlist_scroll.winfo_children():
            child.destroy()
        self.playlist_thumbnail_labels.clear()
        self.playlist_card_frames.clear()
        self.playlist_title_labels.clear()
        self.playlist_meta_labels.clear()
        self.playlist_thumb_frames.clear()
        self.playlist_indicator_frames.clear()

        if not result.playlist_entries:
            self.playlist_empty_label = ctk.CTkLabel(
                self.playlist_scroll,
                text="No playlist items were found.",
                text_color=TEXT_MUTED,
                font=self.font_body,
            )
            self.playlist_empty_label.grid(row=0, column=0, sticky="ew", pady=28)
            return

        for grid_column in range(4):
            self.playlist_scroll.grid_columnconfigure(grid_column, weight=1, uniform="playlist")

        for index, entry in enumerate(result.playlist_entries):
            item_key = f"playlist:{index}"
            row = index // 4
            column = index % 4
            item_width = self.LIST_THUMB_SIZE[0]
            frame = ctk.CTkFrame(
                self.playlist_scroll,
                fg_color="transparent",
                width=item_width,
                height=214,
                corner_radius=0,
                border_width=0,
            )
            frame.grid(
                row=row,
                column=column,
                sticky="nw",
                padx=(0, 18) if column < 3 else (0, 0),
                pady=(0, 18),
            )
            frame.grid_columnconfigure(0, weight=1)
            frame.grid_propagate(False)

            thumb_frame = ctk.CTkFrame(
                frame,
                fg_color=SOFT_BG,
                width=self.LIST_THUMB_SIZE[0],
                height=self.LIST_THUMB_SIZE[1],
                corner_radius=0,
                border_width=1,
                border_color=CARD_BORDER,
            )
            thumb_frame.grid(row=0, column=0, sticky="w")
            thumb_frame.grid_propagate(False)
            thumb_frame.grid_rowconfigure(0, weight=1)
            thumb_frame.grid_columnconfigure(0, weight=1)

            thumb = ctk.CTkLabel(
                thumb_frame,
                text="Preview",
                width=self.LIST_THUMB_SIZE[0],
                height=self.LIST_THUMB_SIZE[1],
                corner_radius=0,
                fg_color=SOFT_BG,
                text_color=TEXT_MUTED,
                font=self.font_micro,
            )
            thumb.grid(row=0, column=0, sticky="nsew")

            title = ctk.CTkLabel(
                frame,
                text=entry.title,
                text_color=TEXT_PRIMARY,
                font=self.font_table_cell_bold,
                anchor="nw",
                justify="left",
                wraplength=item_width,
                height=60,
            )
            title.grid(row=1, column=0, sticky="new", pady=(10, 4))

            duration_text = (
                entry.duration_text if entry.duration_text and entry.duration_text != "unknown" else "-"
            )

            meta = ctk.CTkLabel(
                frame,
                text=f"Item {index + 1} | {duration_text}",
                text_color=TEXT_MUTED,
                font=self.font_micro,
                anchor="w",
                justify="left",
                wraplength=item_width,
                height=18,
            )
            meta.grid(row=2, column=0, sticky="ew")

            indicator = ctk.CTkFrame(
                frame,
                fg_color="transparent",
                width=42,
                height=3,
                corner_radius=2,
            )
            indicator.grid(row=3, column=0, sticky="w", pady=(10, 0))
            indicator.grid_propagate(False)

            self._bind_select(frame, lambda selected=item_key: self._select_playlist_item(selected))
            self._bind_select(thumb_frame, lambda selected=item_key: self._select_playlist_item(selected))
            self._bind_select(thumb, lambda selected=item_key: self._select_playlist_item(selected))
            self._bind_select(title, lambda selected=item_key: self._select_playlist_item(selected))
            self._bind_select(meta, lambda selected=item_key: self._select_playlist_item(selected))
            self._bind_select(indicator, lambda selected=item_key: self._select_playlist_item(selected))

            self.playlist_card_frames[item_key] = frame
            self.playlist_thumb_frames[item_key] = thumb_frame
            self.playlist_thumbnail_labels[item_key] = thumb
            self.playlist_title_labels[item_key] = title
            self.playlist_meta_labels[item_key] = meta
            self.playlist_indicator_frames[item_key] = indicator

            if item_key in self.thumbnail_bytes:
                self._apply_thumbnail(item_key, self.thumbnail_bytes[item_key])

    def _bind_select(self, widget: tk.Widget, callback: object) -> None:
        widget.bind("<Button-1>", lambda _event: callback(), add="+")

    def _select_format(self, option_number: int) -> None:
        self.current_selection = int(option_number)
        self._refresh_format_selection_styles()
        self._update_selected_summary()
        self._update_action_states()

    def _refresh_format_selection_styles(self) -> None:
        for number, frame in self.format_card_frames.items():
            selected = number == self.current_selection
            base_color = self.format_row_colors.get(number, CARD_BG)
            frame.configure(
                fg_color="#FFF1EE" if selected else base_color,
                border_color=ACCENT_RED if selected else CARD_BORDER,
                border_width=1,
            )
            button = self.format_card_buttons[number]
            if selected:
                button.configure(
                    text="Selected",
                    fg_color=ACCENT_RED,
                    hover_color=ACCENT_RED_DARK,
                    text_color="white",
                )
            else:
                button.configure(
                    text="Select",
                    fg_color="#EDEFF4",
                    hover_color="#E3E7EF",
                    text_color=TEXT_PRIMARY,
                )

    def _select_playlist_item(self, item_key: str) -> None:
        if self.scan_result is None or self.scan_result.mode != "playlist":
            return
        index = int(item_key.split(":")[1])
        self.preview_item_key = item_key
        self._set_playlist_media_copy(self.scan_result, index)
        self._refresh_playlist_selection_styles(item_key)
        self._render_preview(item_key)

    def _refresh_playlist_selection_styles(self, selected_key: str | None) -> None:
        for item_key, frame in self.playlist_card_frames.items():
            selected = item_key == selected_key
            frame.configure(
                fg_color="transparent",
                border_width=0,
            )
            thumb_frame = self.playlist_thumb_frames.get(item_key)
            if thumb_frame is not None:
                thumb_frame.configure(
                    border_width=2 if selected else 1,
                    border_color=ACCENT_RED if selected else CARD_BORDER,
                    fg_color=SOFT_BG,
                )
            title = self.playlist_title_labels.get(item_key)
            if title is not None:
                title.configure(text_color=ACCENT_RED_DARK if selected else TEXT_PRIMARY)
            meta = self.playlist_meta_labels.get(item_key)
            if meta is not None:
                meta.configure(text_color=TEXT_SECONDARY if selected else TEXT_MUTED)
            indicator = self.playlist_indicator_frames.get(item_key)
            if indicator is not None:
                indicator.configure(fg_color=ACCENT_RED if selected else "transparent")

    def _reset_preview(self) -> None:
        # CTkLabel applies text updates before image updates, so clear the raw
        # Tk image handle first to avoid stale "pyimage..." references.
        try:
            self.preview_label._label.configure(image="", compound="center")
        except tk.TclError:
            pass

        self.preview_label._image = None
        self.preview_label._text = "Thumbnail preview"
        self.preview_label._compound = "center"
        self.preview_label._label.configure(text="Thumbnail preview")

    def _render_preview(self, item_key: str | None) -> None:
        if item_key is None or Image is None or ImageOps is None or RESAMPLE is None:
            self._reset_preview()
            return

        raw_bytes = self.thumbnail_bytes.get(item_key)
        if not raw_bytes:
            self._reset_preview()
            return

        image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        fitted = ImageOps.fit(image, self.PREVIEW_SIZE, method=RESAMPLE)
        self.thumbnail_images[f"preview:{item_key}"] = ctk.CTkImage(
            light_image=fitted,
            dark_image=fitted,
            size=self.PREVIEW_SIZE,
        )
        self.preview_label.configure(image=self.thumbnail_images[f"preview:{item_key}"], text="")

    def _queue_thumbnail_jobs(self, token: int, result: ScanResult) -> None:
        jobs: list[tuple[str, str]] = []
        if result.mode == "video":
            if result.thumbnail_url:
                jobs.append(("video", result.thumbnail_url))
        else:
            for index, entry in enumerate(result.playlist_entries):
                if entry.thumbnail_url:
                    jobs.append((f"playlist:{index}", entry.thumbnail_url))

        if not jobs:
            return

        worker = threading.Thread(target=self._thumbnail_worker, args=(token, jobs), daemon=True)
        worker.start()

    def _thumbnail_worker(self, token: int, jobs: list[tuple[str, str]]) -> None:
        for item_key, url in jobs:
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    data = response.read()
                self.ui_queue.put(("thumbnail", (token, item_key, data)))
            except Exception:
                continue

    def _process_queue(self) -> None:
        while True:
            try:
                event, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if event == "log":
                self._append_log(str(payload))
            elif event == "progress":
                self._apply_progress(dict(payload))
            elif event == "scan-success":
                token, result = payload
                if token == self.thumbnail_token:
                    self._apply_scan_result(result)
            elif event == "scan-error":
                self._set_busy(False)
                self.status_var.set("Scan failed.")
                self._show_screen("url")
                messagebox.showerror("Scan Failed", str(payload))
            elif event == "download-success":
                self._set_busy(False)
                self._handle_download_success(dict(payload))
            elif event == "download-error":
                self._set_busy(False)
                self.status_var.set("Download failed.")
                self._show_screen("download")
                messagebox.showerror("Download Failed", str(payload))
            elif event == "thumbnail":
                token, item_key, data = payload
                if token == self.thumbnail_token:
                    self._apply_thumbnail(item_key, data)

        self.after(100, self._process_queue)

    def _apply_thumbnail(self, item_key: str, data: bytes) -> None:
        if Image is None or ImageOps is None or RESAMPLE is None:
            return

        self.thumbnail_bytes[item_key] = data
        image = Image.open(io.BytesIO(data)).convert("RGB")

        if item_key == "video" or item_key == self.preview_item_key:
            self._render_preview(item_key)

        if item_key.startswith("playlist:"):
            thumb = ImageOps.fit(image, self.LIST_THUMB_SIZE, method=RESAMPLE)
            self.thumbnail_images[item_key] = ctk.CTkImage(
                light_image=thumb,
                dark_image=thumb,
                size=self.LIST_THUMB_SIZE,
            )
            label = self.playlist_thumbnail_labels.get(item_key)
            if label is not None:
                label.configure(image=self.thumbnail_images[item_key], text="")

    def _update_selected_summary(self) -> None:
        if self.scan_result is None or self.current_selection is None:
            self.selected_format_var.set("No format selected.")
            self.download_summary_var.set(
                "Choose a format on the details screen to unlock the download step."
            )
            return

        if self.scan_result.mode == "playlist":
            option = get_playlist_option(self.scan_result, self.current_selection)
            title_text = self.scan_result.title
            summary = (
                f"Option {option.number}: {option.kind} | {option.resolution} | "
                f"{option.extension.upper()} | {option.size_text}"
            )
            detail_text = option.detail_text
            extra = f"Playlist download for {self.scan_result.video_count} videos."
        else:
            option = get_video_option(self.scan_result, self.current_selection)
            title_text = self.scan_result.title
            summary = (
                f"Option {option.number}: {option.kind} | {option.resolution} | "
                f"{option.extension.upper()} | {option.size_text}"
            )
            detail_text = option.detail_text
            extra = "Single video download."

        self.selected_format_var.set(f"{summary}\n{detail_text}")
        self.download_summary_var.set(
            f"{title_text}\n\n{summary}\n{detail_text}\n\n{extra}\nSave folder: {self.save_dir_var.get()}"
        )

    def _apply_progress(self, payload: dict) -> None:
        overall_percent = payload.get("overall_percent")
        if overall_percent is None:
            overall_percent = payload.get("percent")
        if overall_percent is not None:
            self._set_progress(overall_percent)

        if payload.get("status") == "item-start":
            self.status_var.set(
                f"Downloading item {payload['item_index']}/{payload['item_total']}: {payload['item_title']}"
            )
            return

        if payload.get("phase") == "download" and payload.get("status") == "downloading":
            if "item_index" in payload:
                self.status_var.set(
                    f"Downloading item {payload['item_index']}/{payload['item_total']}: {payload['item_title']}"
                )
            else:
                self.status_var.set("Downloading selected format...")
            return

        if payload.get("phase") == "postprocess":
            self.status_var.set(payload.get("text", "Post-processing..."))
            return

        if payload.get("status") == "finished":
            self.status_var.set("Download finished.")

    def _handle_download_success(self, summary: dict) -> None:
        self._set_progress(100.0)
        saved_to = summary["saved_to"]
        self.last_open_path = saved_to
        self.status_var.set(f"Saved to {saved_to}")
        self._append_log(f"Saved to: {saved_to}")
        self._update_selected_summary()
        self._show_screen("download")

        skipped = summary.get("skipped") or []
        if skipped:
            self._append_log(f"Skipped items: {len(skipped)}")
            for item in skipped:
                self._append_log(f"- {item}")

        message = f"Saved to:\n{saved_to}"
        if skipped:
            message += f"\n\nDownloaded: {summary.get('downloaded', 0)}\nSkipped: {len(skipped)}"
        messagebox.showinfo("Download Complete", message)

    def _append_log(self, message: str) -> None:
        line = f"{message.rstrip()}\n"
        for widget in (self.scan_console_text, self.log_text):
            widget.configure(state="normal")
            widget.insert("end", line)
            widget.see("end")
            widget.configure(state="disabled")

    def _queue_log(self, message: str) -> None:
        self.ui_queue.put(("log", message))

    def _queue_progress(self, payload: dict) -> None:
        self.ui_queue.put(("progress", payload))


def main() -> int:
    app = YouTubeDownloaderUI()
    app.mainloop()
    return 0
