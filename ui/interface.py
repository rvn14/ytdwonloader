"""Tkinter interface for the YouTube downloader."""
from __future__ import annotations

import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, ttk

from config.settings import DEFAULTS
from services import ScanResult, download_scan_result, scan_url

try:
    from PIL import Image, ImageOps, ImageTk
except ImportError:  # pragma: no cover - graceful fallback if Pillow is missing
    Image = None
    ImageOps = None
    ImageTk = None


YOUTUBE_RED = "#FF0000"
YOUTUBE_RED_DARK = "#CC0000"
YOUTUBE_BLACK = "#0F0F0F"
YOUTUBE_MUTED = "#606060"
APP_BG = "#F6F6F6"
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E5E5E5"
SOFT_BG = "#FAFAFA"


class YouTubeDownloaderUI(tk.Tk):
    """Main desktop UI."""

    PREVIEW_SIZE = (360, 202)
    LIST_THUMB_SIZE = (120, 68)
    MOUSEWHEEL_STEP = 120

    def __init__(self) -> None:
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("1440x920")
        self.minsize(1180, 760)
        self.configure(bg=APP_BG)

        self.ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.scan_result: ScanResult | None = None
        self.current_selection: int | None = None
        self.thumbnail_token = 0
        self.preview_item_key: str | None = None
        self.thumbnail_bytes: dict[str, bytes] = {}
        self.preview_image: ImageTk.PhotoImage | None = None
        self.playlist_images: dict[str, ImageTk.PhotoImage] = {}
        self.last_open_path = os.path.abspath(DEFAULTS["output_dir"])

        self.url_var = tk.StringVar()
        self.use_cookies_var = tk.BooleanVar(value=DEFAULTS["use_chrome_cookies"])
        self.profile_var = tk.StringVar()
        self.save_dir_var = tk.StringVar(value=os.path.abspath(DEFAULTS["output_dir"]))
        self.status_var = tk.StringVar(value="Paste a YouTube video or playlist URL and click Scan.")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.mode_var = tk.StringVar(value="Ready")
        self.formats_title_var = tk.StringVar(value="Available Formats")
        self.download_label_var = tk.StringVar(value="Download")
        self.preview_caption_var = tk.StringVar(value="Thumbnail preview")

        self.info_vars = {
            "Title": tk.StringVar(value="-"),
            "Channel": tk.StringVar(value="-"),
            "Duration": tk.StringVar(value="-"),
            "Playlist": tk.StringVar(value="-"),
            "Videos": tk.StringVar(value="-"),
            "Cookies": tk.StringVar(value="-"),
        }

        self._build_styles()
        self._build_layout()
        self.after(100, self._process_queue)

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        self.option_add("*Font", "{Segoe UI} 10")

        style.configure("App.TFrame", background=APP_BG)
        style.configure(
            "Card.TFrame",
            background=CARD_BG,
            borderwidth=1,
            relief="solid",
            bordercolor=CARD_BORDER,
        )
        style.configure("CardTitle.TLabel", background=CARD_BG, foreground=YOUTUBE_BLACK, font=("{Segoe UI Semibold}", 12))
        style.configure("Muted.TLabel", background=CARD_BG, foreground=YOUTUBE_MUTED)
        style.configure("InfoLabel.TLabel", background=CARD_BG, foreground=YOUTUBE_MUTED, font=("{Segoe UI Semibold}", 9))
        style.configure("InfoValue.TLabel", background=CARD_BG, foreground=YOUTUBE_BLACK, font=("{Segoe UI}", 10))
        style.configure("HeroTitle.TLabel", background=APP_BG, foreground=YOUTUBE_BLACK, font=("{Segoe UI Semibold}", 24))
        style.configure("HeroSub.TLabel", background=APP_BG, foreground=YOUTUBE_MUTED, font=("{Segoe UI}", 10))
        style.configure("Mode.TLabel", background=CARD_BG, foreground=YOUTUBE_RED, font=("{Segoe UI Semibold}", 10))
        style.configure("TLabel", background=APP_BG, foreground=YOUTUBE_BLACK)
        style.configure("TCheckbutton", background=CARD_BG, foreground=YOUTUBE_BLACK)
        style.configure("TEntry", fieldbackground=SOFT_BG, bordercolor=CARD_BORDER, padding=8)
        style.configure("Accent.TButton", background=YOUTUBE_RED, foreground="white", borderwidth=0, focusthickness=0, focuscolor=YOUTUBE_RED, padding=(14, 10))
        style.map("Accent.TButton", background=[("active", YOUTUBE_RED_DARK), ("disabled", "#F3A8A8")], foreground=[("disabled", "#FBEAEA")])
        style.configure("Secondary.TButton", background=YOUTUBE_BLACK, foreground="white", borderwidth=0, focusthickness=0, focuscolor=YOUTUBE_BLACK, padding=(12, 10))
        style.map("Secondary.TButton", background=[("active", "#2A2A2A"), ("disabled", "#B5B5B5")], foreground=[("disabled", "#EFEFEF")])
        style.configure("Plain.TButton", background=SOFT_BG, foreground=YOUTUBE_BLACK, borderwidth=1, focusthickness=0, focuscolor=SOFT_BG, bordercolor=CARD_BORDER, padding=(12, 10))
        style.map("Plain.TButton", background=[("active", "#F1F1F1")])
        style.configure("Accent.Horizontal.TProgressbar", troughcolor="#EDEDED", background=YOUTUBE_RED, bordercolor="#EDEDED", lightcolor=YOUTUBE_RED, darkcolor=YOUTUBE_RED)
        style.configure("Formats.Treeview", background=CARD_BG, fieldbackground=CARD_BG, foreground=YOUTUBE_BLACK, bordercolor=CARD_BORDER, rowheight=30)
        style.map("Formats.Treeview", background=[("selected", "#FFE5E5")], foreground=[("selected", YOUTUBE_BLACK)])
        style.configure("Formats.Treeview.Heading", background=SOFT_BG, foreground=YOUTUBE_BLACK, relief="flat", bordercolor=CARD_BORDER, font=("{Segoe UI Semibold}", 9))
        style.configure("Playlist.Treeview", background=CARD_BG, fieldbackground=CARD_BG, foreground=YOUTUBE_BLACK, bordercolor=CARD_BORDER, rowheight=78)
        style.map("Playlist.Treeview", background=[("selected", "#FFE5E5")], foreground=[("selected", YOUTUBE_BLACK)])
        style.configure("Playlist.Treeview.Heading", background=SOFT_BG, foreground=YOUTUBE_BLACK, relief="flat", bordercolor=CARD_BORDER, font=("{Segoe UI Semibold}", 9))

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        shell = ttk.Frame(self, style="App.TFrame")
        shell.grid(sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        self.root_canvas = tk.Canvas(
            shell,
            bg=APP_BG,
            highlightthickness=0,
            bd=0,
        )
        self.root_canvas.grid(row=0, column=0, sticky="nsew")

        self.root_scrollbar = ttk.Scrollbar(
            shell,
            orient="vertical",
            command=self.root_canvas.yview,
        )
        self.root_scrollbar.grid(row=0, column=1, sticky="ns")
        self.root_canvas.configure(yscrollcommand=self.root_scrollbar.set)

        app = ttk.Frame(self.root_canvas, style="App.TFrame", padding=18)
        self._canvas_window_id = self.root_canvas.create_window(
            (0, 0),
            window=app,
            anchor="nw",
        )
        app.columnconfigure(0, weight=1)
        app.bind("<Configure>", self._on_app_frame_configure)
        self.root_canvas.bind("<Configure>", self._on_canvas_configure)

        self.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.bind_all("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")

        header = ttk.Frame(app, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="YouTube Downloader", style="HeroTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Single videos show exact formats. Playlists scan every item and only offer playlist-safe common choices.",
            style="HeroSub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        url_card = ttk.Frame(app, style="Card.TFrame", padding=16)
        url_card.grid(row=1, column=0, sticky="ew")
        url_card.columnconfigure(0, weight=1)
        url_card.columnconfigure(1, weight=0)
        url_card.columnconfigure(2, weight=0)

        ttk.Label(url_card, text="URL", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(url_card, textvariable=self.url_var).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 12))

        self.scan_button = ttk.Button(url_card, text="Scan", style="Accent.TButton", command=self._on_scan)
        self.scan_button.grid(row=2, column=0, sticky="w")

        options_row = ttk.Frame(url_card, style="Card.TFrame")
        options_row.grid(row=2, column=1, columnspan=2, sticky="e")
        ttk.Checkbutton(options_row, text="Use browser cookies", variable=self.use_cookies_var).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Label(options_row, text="Profile", style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(0, 8))
        ttk.Entry(options_row, textvariable=self.profile_var, width=22).grid(row=0, column=2, sticky="e")

        content = ttk.Frame(app, style="App.TFrame")
        content.grid(row=2, column=0, sticky="ew", pady=16)
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)

        info_card = ttk.Frame(content, style="Card.TFrame", padding=16)
        info_card.grid(row=0, column=0, sticky="new", padx=(0, 8))
        info_card.columnconfigure(0, weight=1)

        ttk.Label(info_card, text="Media", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")

        preview_frame = ttk.Frame(info_card, style="Card.TFrame")
        preview_frame.grid(row=1, column=0, sticky="ew", pady=(10, 12))
        preview_frame.columnconfigure(0, weight=1)

        preview_viewport = ttk.Frame(preview_frame, style="Card.TFrame")
        preview_viewport.grid(row=0, column=0, sticky="ew")
        preview_viewport.columnconfigure(0, weight=1)
        preview_viewport.rowconfigure(0, weight=1)
        preview_viewport.configure(height=self.PREVIEW_SIZE[1] + 8)
        preview_viewport.grid_propagate(False)

        self.preview_label = tk.Label(
            preview_viewport,
            bg=SOFT_BG,
            fg=YOUTUBE_MUTED,
            text="Thumbnail preview",
            relief="flat",
            bd=0,
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(preview_frame, textvariable=self.mode_var, style="Mode.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(preview_frame, textvariable=self.preview_caption_var, style="Muted.TLabel", wraplength=360).grid(row=2, column=0, sticky="w", pady=(2, 0))

        info_grid = ttk.Frame(info_card, style="Card.TFrame")
        info_grid.grid(row=2, column=0, sticky="ew")
        info_grid.columnconfigure(1, weight=1)
        for row_index, label in enumerate(self.info_vars):
            ttk.Label(info_grid, text=label.upper(), style="InfoLabel.TLabel").grid(row=row_index, column=0, sticky="nw", pady=3, padx=(0, 14))
            ttk.Label(info_grid, textvariable=self.info_vars[label], style="InfoValue.TLabel", wraplength=320, justify="left").grid(row=row_index, column=1, sticky="ew", pady=3)

        self.playlist_section = ttk.Frame(info_card, style="Card.TFrame")
        self.playlist_section.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        self.playlist_section.columnconfigure(0, weight=1)
        ttk.Label(self.playlist_section, text="Playlist Videos", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        playlist_frame = ttk.Frame(self.playlist_section, style="Card.TFrame")
        playlist_frame.grid(row=1, column=0, sticky="ew")
        playlist_frame.columnconfigure(0, weight=1)

        self.playlist_tree = ttk.Treeview(
            playlist_frame,
            columns=("channel", "duration"),
            style="Playlist.Treeview",
            show="tree headings",
            selectmode="browse",
            height=8,
        )
        self.playlist_tree.heading("#0", text="Video")
        self.playlist_tree.heading("channel", text="Channel")
        self.playlist_tree.heading("duration", text="Duration")
        self.playlist_tree.column("#0", width=340, stretch=True)
        self.playlist_tree.column("channel", width=160, anchor="w")
        self.playlist_tree.column("duration", width=90, anchor="center")
        self.playlist_tree.grid(row=0, column=0, sticky="nsew")
        self.playlist_tree.bind("<<TreeviewSelect>>", self._on_playlist_select)

        playlist_scroll = ttk.Scrollbar(playlist_frame, orient="vertical", command=self.playlist_tree.yview)
        playlist_scroll.grid(row=0, column=1, sticky="ns")
        self.playlist_tree.configure(yscrollcommand=playlist_scroll.set)

        formats_card = ttk.Frame(content, style="Card.TFrame", padding=16)
        formats_card.grid(row=0, column=1, sticky="new", padx=(8, 0))
        formats_card.columnconfigure(0, weight=1)

        ttk.Label(formats_card, textvariable=self.formats_title_var, style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))

        formats_frame = ttk.Frame(formats_card, style="Card.TFrame")
        formats_frame.grid(row=1, column=0, sticky="ew")
        formats_frame.columnconfigure(0, weight=1)

        self.formats_tree = ttk.Treeview(
            formats_frame,
            columns=("number", "kind", "resolution", "ext", "fps", "audio", "size", "details"),
            style="Formats.Treeview",
            show="headings",
            selectmode="browse",
            height=18,
        )
        for column, title, width, anchor in (
            ("number", "#", 40, "center"),
            ("kind", "Type", 80, "center"),
            ("resolution", "Resolution", 120, "center"),
            ("ext", "Ext", 55, "center"),
            ("fps", "FPS", 80, "center"),
            ("audio", "Audio", 80, "center"),
            ("size", "Size", 90, "center"),
            ("details", "Details", 320, "w"),
        ):
            self.formats_tree.heading(column, text=title)
            self.formats_tree.column(column, width=width, anchor=anchor, stretch=column == "details")
        self.formats_tree.grid(row=0, column=0, sticky="nsew")
        self.formats_tree.bind("<<TreeviewSelect>>", self._on_format_select)
        self.formats_tree.bind("<Double-1>", lambda _event: self._on_download())

        formats_scroll = ttk.Scrollbar(formats_frame, orient="vertical", command=self.formats_tree.yview)
        formats_scroll.grid(row=0, column=1, sticky="ns")
        self.formats_tree.configure(yscrollcommand=formats_scroll.set)

        controls_card = ttk.Frame(app, style="Card.TFrame", padding=16)
        controls_card.grid(row=3, column=0, sticky="ew")
        controls_card.columnconfigure(0, weight=1)

        ttk.Label(controls_card, text="Save Location", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls_card, textvariable=self.save_dir_var).grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 12))

        buttons_frame = ttk.Frame(controls_card, style="Card.TFrame")
        buttons_frame.grid(row=1, column=1, sticky="e", pady=(8, 0))
        self.browse_button = ttk.Button(buttons_frame, text="Browse", style="Plain.TButton", command=self._pick_folder)
        self.browse_button.grid(row=0, column=0, padx=(0, 8))
        self.download_button = ttk.Button(buttons_frame, textvariable=self.download_label_var, style="Accent.TButton", command=self._on_download)
        self.download_button.grid(row=0, column=1, padx=(0, 8))
        self.open_folder_button = ttk.Button(buttons_frame, text="Open Folder", style="Secondary.TButton", command=self._open_folder)
        self.open_folder_button.grid(row=0, column=2)

        self.progress_card = ttk.Frame(app, style="Card.TFrame", padding=16)
        self.progress_card.grid(row=4, column=0, sticky="nsew", pady=(16, 0))
        self.progress_card.columnconfigure(0, weight=1)
        ttk.Label(self.progress_card, text="Progress", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Progressbar(self.progress_card, variable=self.progress_var, maximum=100, style="Accent.Horizontal.TProgressbar").grid(row=1, column=0, sticky="ew", pady=(10, 8))
        ttk.Label(self.progress_card, textvariable=self.status_var, style="Muted.TLabel", wraplength=1200).grid(row=2, column=0, sticky="w", pady=(0, 8))

        self.log_text = tk.Text(
            self.progress_card,
            wrap="word",
            height=10,
            bg=SOFT_BG,
            fg=YOUTUBE_BLACK,
            bd=0,
            relief="flat",
            padx=12,
            pady=12,
            insertbackground=YOUTUBE_BLACK,
        )
        self.log_text.grid(row=3, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        log_scroll = ttk.Scrollbar(self.progress_card, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=3, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.playlist_section.grid_remove()
        self._set_busy(False)

    def _on_app_frame_configure(self, _event: tk.Event) -> None:
        self.root_canvas.configure(scrollregion=self.root_canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.root_canvas.itemconfigure(self._canvas_window_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self._is_widget_scrollable(event.widget):
            return
        delta = getattr(event, "delta", 0)
        if not delta:
            return
        units = -int(delta / self.MOUSEWHEEL_STEP)
        if units == 0:
            units = -1 if delta > 0 else 1
        self.root_canvas.yview_scroll(units, "units")

    def _on_shift_mousewheel(self, event: tk.Event) -> None:
        if self._is_widget_scrollable(event.widget):
            return
        delta = getattr(event, "delta", 0)
        if not delta:
            return
        units = -int(delta / self.MOUSEWHEEL_STEP)
        if units == 0:
            units = -1 if delta > 0 else 1
        self.root_canvas.xview_scroll(units, "units")

    def _is_widget_scrollable(self, widget: object) -> bool:
        return isinstance(widget, (tk.Text, ttk.Treeview, tk.Listbox))

    def _scroll_to_widget(self, widget: tk.Widget, *, padding: int = 24) -> None:
        self.update_idletasks()
        app_top = self.root_canvas.winfo_rooty()
        widget_top = widget.winfo_rooty()
        current_top = self.root_canvas.canvasy(0)
        target_top = max(0, current_top + (widget_top - app_top) - padding)
        scroll_region = self.root_canvas.bbox("all")
        if not scroll_region:
            return
        total_height = max(1, scroll_region[3] - scroll_region[1])
        self.root_canvas.yview_moveto(min(1.0, target_top / total_height))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.download_button.configure(state=state if self.scan_result and self.current_selection else "disabled")
        self.browse_button.configure(state=state)

    def _on_scan(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Missing URL", "Paste a YouTube video or playlist URL first.")
            return

        self.scan_result = None
        self.current_selection = None
        self.thumbnail_token += 1
        self.thumbnail_bytes.clear()
        self.playlist_images.clear()
        self.progress_var.set(0.0)
        self.status_var.set("Scanning URL...")
        self._clear_results()
        self._append_log(f"Scanning: {url}")
        self._set_busy(True)

        worker = threading.Thread(
            target=self._scan_worker,
            args=(
                self.thumbnail_token,
                url,
                self.use_cookies_var.get(),
                self.profile_var.get().strip() or None,
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

    def _on_download(self) -> None:
        if self.scan_result is None or self.current_selection is None:
            messagebox.showerror("No format selected", "Scan a URL and choose a format before downloading.")
            return

        output_dir = self.save_dir_var.get().strip()
        if not output_dir:
            messagebox.showerror("Missing save folder", "Pick a save folder before downloading.")
            return

        self.progress_var.set(0.0)
        self.status_var.set("Preparing download...")
        self._append_log("Starting download...")
        self._set_busy(True)
        self._scroll_to_widget(self.progress_card)

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
        self.preview_caption_var.set("Thumbnail preview")
        self._reset_preview()
        for info_var in self.info_vars.values():
            info_var.set("-")
        self.formats_title_var.set("Available Formats")
        self.download_label_var.set("Download")
        for item in self.formats_tree.get_children():
            self.formats_tree.delete(item)
        for item in self.playlist_tree.get_children():
            self.playlist_tree.delete(item)
        self.playlist_section.grid_remove()

    def _apply_scan_result(self, result: ScanResult) -> None:
        self.scan_result = result
        self.save_dir_var.set(result.output_dir)
        self.last_open_path = result.output_dir

        self.mode_var.set("Playlist" if result.mode == "playlist" else "Single Video")
        self.preview_caption_var.set(result.title)
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
                self.preview_caption_var.set(result.playlist_entries[0].title)
        else:
            self.formats_title_var.set("Available Formats")
            self.download_label_var.set("Download")
            self._populate_formats(result.all_video_options)
            self.preview_item_key = "video"

        self.status_var.set("Scan complete. Choose a format to continue.")
        self._set_busy(False)

    def _populate_formats(self, options: list[object]) -> None:
        for item in self.formats_tree.get_children():
            self.formats_tree.delete(item)

        for option in options:
            self.formats_tree.insert(
                "",
                "end",
                iid=str(getattr(option, "number")),
                values=(
                    getattr(option, "number"),
                    getattr(option, "kind"),
                    getattr(option, "resolution"),
                    getattr(option, "extension"),
                    getattr(option, "fps_text"),
                    getattr(option, "audio_text"),
                    getattr(option, "size_text"),
                    getattr(option, "detail_text"),
                ),
            )

        children = self.formats_tree.get_children()
        if children:
            first = children[0]
            self.formats_tree.selection_set(first)
            self.formats_tree.focus(first)
            self.current_selection = int(first)

    def _populate_playlist(self, result: ScanResult) -> None:
        for item in self.playlist_tree.get_children():
            self.playlist_tree.delete(item)

        for index, entry in enumerate(result.playlist_entries):
            item_id = f"playlist:{index}"
            self.playlist_tree.insert(
                "",
                "end",
                iid=item_id,
                text=entry.title,
                values=(entry.channel, entry.duration_text),
            )

        children = self.playlist_tree.get_children()
        if children:
            self.playlist_tree.selection_set(children[0])
            self.playlist_tree.focus(children[0])

    def _on_format_select(self, _event: object) -> None:
        selection = self.formats_tree.selection()
        if not selection:
            self.current_selection = None
            self.download_button.configure(state="disabled")
            return

        self.current_selection = int(selection[0])
        self.download_button.configure(state="normal")

    def _on_playlist_select(self, _event: object) -> None:
        if self.scan_result is None or self.scan_result.mode != "playlist":
            return

        selection = self.playlist_tree.selection()
        if not selection:
            return

        item_id = selection[0]
        index = int(item_id.split(":")[1])
        entry = self.scan_result.playlist_entries[index]
        self.preview_item_key = item_id
        self.preview_caption_var.set(entry.title)
        self._render_preview(item_id)

    def _reset_preview(self) -> None:
        self.preview_label.configure(image="", text="Thumbnail preview")
        self.preview_image = None

    def _render_preview(self, item_key: str | None) -> None:
        if item_key is None:
            self._reset_preview()
            return

        raw_bytes = self.thumbnail_bytes.get(item_key)
        if not raw_bytes or Image is None or ImageOps is None or ImageTk is None:
            self.preview_label.configure(image="", text="Thumbnail preview")
            return

        image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        fitted = ImageOps.fit(image, self.PREVIEW_SIZE, method=Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(fitted)
        self.preview_label.configure(image=self.preview_image, text="")

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
                messagebox.showerror("Scan Failed", str(payload))
            elif event == "download-success":
                self._set_busy(False)
                self._handle_download_success(dict(payload))
            elif event == "download-error":
                self._set_busy(False)
                self.status_var.set("Download failed.")
                messagebox.showerror("Download Failed", str(payload))
            elif event == "thumbnail":
                token, item_key, data = payload
                if token == self.thumbnail_token:
                    self._apply_thumbnail(item_key, data)

        self.after(100, self._process_queue)

    def _apply_thumbnail(self, item_key: str, data: bytes) -> None:
        if Image is None or ImageOps is None or ImageTk is None:
            return

        self.thumbnail_bytes[item_key] = data

        if item_key.startswith("playlist:"):
            image = Image.open(io.BytesIO(data)).convert("RGB")
            fitted = ImageOps.fit(image, self.LIST_THUMB_SIZE, method=Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(fitted)
            self.playlist_images[item_key] = photo
            if self.playlist_tree.exists(item_key):
                self.playlist_tree.item(item_key, image=photo)

        if item_key == self.preview_item_key:
            self._render_preview(item_key)

    def _apply_progress(self, payload: dict) -> None:
        overall_percent = payload.get("overall_percent")
        if overall_percent is None:
            overall_percent = payload.get("percent")
        if overall_percent is not None:
            self.progress_var.set(max(0.0, min(100.0, float(overall_percent))))

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
        self.progress_var.set(100.0)
        saved_to = summary["saved_to"]
        self.last_open_path = saved_to
        self.status_var.set(f"Saved to {saved_to}")
        self._append_log(f"Saved to: {saved_to}")

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
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message.rstrip()}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _queue_log(self, message: str) -> None:
        self.ui_queue.put(("log", message))

    def _queue_progress(self, payload: dict) -> None:
        self.ui_queue.put(("progress", payload))


def main() -> int:
    app = YouTubeDownloaderUI()
    app.mainloop()
    return 0
