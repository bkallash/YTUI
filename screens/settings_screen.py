"""High-performance, compact, keyboard-navigable configuration screen styled with shadcn zinc."""

import subprocess
import sys
from typing import List, Optional, Tuple

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Checkbox, ContentSwitcher, Footer, Header, Input, Label, ListItem, ListView, Static

from config import AppConfig, get_default_download_dir, sanitize_path, sanitize_sponsorblock_categories
from ffmpeg_utils import find_ffmpeg, get_ffmpeg_version, is_ffmpeg_available
from rtl_utils import set_rtl_mode
from screens.ffmpeg_modal import FfmpegSetupModal
from themes import THEME_OPTIONS
from ytdlp_engine import YtDlpEngine



class CycleSelect(Static):
    """Ultra-fast, zero-overhead selector widget that cycles options without heavy modal overlays."""

    can_focus = True

    class Changed(Message):
        """Posted when the selected option changes."""

        def __init__(self, select: "CycleSelect", value: str):
            super().__init__()
            self.select = select
            self.value = value

    DEFAULT_CSS = """
    CycleSelect {
        width: 1fr;
        height: 1;
        background: transparent;
        color: $foreground;
        padding: 0 1;
        border: none;
    }
    CycleSelect:focus {
        background: $boost;
        color: $primary;
        text-style: bold;
    }
    """

    def __init__(self, options: List[Tuple[str, str]], value: str, id: Optional[str] = None, **kwargs):
        super().__init__(id=id, **kwargs)
        self.options = options
        self._current_idx = 0
        for i, (lbl, val) in enumerate(options):
            if val == value:
                self._current_idx = i
                break

    @property
    def value(self) -> str:
        if self.options and 0 <= self._current_idx < len(self.options):
            return self.options[self._current_idx][1]
        return ""

    @value.setter
    def value(self, new_val: str) -> None:
        for i, (lbl, val) in enumerate(self.options):
            if val == new_val:
                self._current_idx = i
                self._update_display()
                return

    def on_mount(self) -> None:
        self._update_display()

    def _update_display(self) -> None:
        if self.options:
            lbl, _ = self.options[self._current_idx]
            self.update(f"◀  [bold]{lbl}[/]  ▶")
        else:
            self.update("◀  None  ▶")

    def cycle_next(self) -> None:
        if self.options:
            self._current_idx = (self._current_idx + 1) % len(self.options)
            self._update_display()
            self.post_message(self.Changed(self, self.value))

    def cycle_prev(self) -> None:
        if self.options:
            self._current_idx = (self._current_idx - 1) % len(self.options)
            self._update_display()
            self.post_message(self.Changed(self, self.value))

    def on_click(self) -> None:
        self.cycle_next()

    def on_key(self, event: Key) -> None:
        if event.key in ("right", "enter", "space", "l"):
            self.cycle_next()
            event.prevent_default()
            event.stop()
        elif event.key in ("left", "h"):
            self.cycle_prev()
            event.prevent_default()
            event.stop()


class SettingsScreen(Screen):
    """Clean two-panel category-based settings interface with zero bloat and instant navigation."""

    DEFAULT_CSS = """
    SettingsScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #settings-main-container {
        height: 1fr;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #settings-sidebar {
        width: 28;
        height: 100%;
        background: $surface;
        border-right: solid $border;
        padding: 0;
    }
    #sidebar-header-label {
        height: 1;
        width: 100%;
        background: $panel;
        color: $primary;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid $border;
    }
    #category-list {
        height: 1fr;
        width: 100%;
        background: transparent;
        padding: 0;
    }
    .cat-item {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    .cat-item:focus {
        background: $panel;
        color: $primary;
        text-style: bold;
    }
    #settings-content-switcher {
        height: 100%;
        width: 1fr;
        background: $background;
        padding: 0;
    }
    .settings-pane {
        height: 100%;
        width: 100%;
        background: $background;
        padding: 1 2;
    }
    .pane-title {
        color: $primary;
        text-style: bold;
        height: 1;
        margin-bottom: 0;
    }
    .pane-desc {
        color: $text-muted;
        height: 1;
        margin-bottom: 1;
    }
    .setting-row {
        height: 1;
        width: 100%;
        margin-bottom: 1;
        align: left middle;
        background: $surface;
        padding: 0 1;
    }
    .setting-row:focus-within {
        background: $panel;
    }
    .setting-label {
        width: 28;
        padding: 0;
        color: $text-muted;
    }
    .setting-row:focus-within .setting-label {
        color: $foreground;
        text-style: bold;
    }
    .setting-input {
        width: 1fr;
        height: 1;
        background: $background;
        border: none;
        padding: 0 1;
        color: $foreground;
    }
    .setting-input:focus {
        background: $boost;
        color: $foreground;
        text-style: bold;
    }
    Checkbox {
        height: 1;
        padding: 0;
        background: transparent;
        border: none;
    }
    Checkbox:focus {
        color: $primary;
        text-style: bold;
    }
    .auth-btn-row {
        height: 1;
        width: 100%;
        margin-top: 1;
        margin-bottom: 1;
    }
    #btn-test-cookies {
        width: 100%;
        height: 1;
        background: $primary;
        color: $background;
        text-style: bold;
    }
    #btn-test-cookies:focus, #btn-test-cookies:hover {
        background: $accent;
        color: $foreground;
    }
    #cookie-diag-box {
        width: 100%;
        height: auto;
        min-height: 2;
        background: $surface;
        border: solid $border;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cookie-help-guide {
        width: 100%;
        height: auto;
        background: $surface;
        border-left: thick $primary;
        padding: 0 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_settings", "Save", show=True),
        Binding("escape", "go_back", "Discard", show=True),
        Binding("ctrl+r", "reset_defaults", "Defaults", show=True),
        Binding("ctrl+u", "update_ytdlp", "Update yt-dlp", show=True),
        Binding("ctrl+j", "app.switch_to_downloads", "Queue", show=False),
        Binding("ctrl+y", "app.switch_to_history", "History", show=False),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=False),
        Binding("ctrl+q", "app.quit_app", "Quit", show=True),
    ]

    PANE_MAP = {
        "cat-general": "pane-general",
        "cat-bandwidth": "pane-bandwidth",
        "cat-auth": "pane-auth",
        "cat-subtitles": "pane-subtitles",
        "cat-media": "pane-media",
        "cat-metadata": "pane-metadata",
        "cat-proxy": "pane-proxy",
        "cat-appearance": "pane-appearance",
    }

    def __init__(self, config: Optional[AppConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or AppConfig.load()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="settings-main-container"):
            # Left Sidebar: Categories
            with Vertical(id="settings-sidebar"):
                yield Label("CATEGORIES", id="sidebar-header-label")
                with ListView(id="category-list", initial_index=0):
                    yield ListItem(Label("General & Paths"), id="cat-general", classes="cat-item")
                    yield ListItem(Label("Bandwidth & Queue"), id="cat-bandwidth", classes="cat-item")
                    yield ListItem(Label("Cookies & Auth"), id="cat-auth", classes="cat-item")
                    yield ListItem(Label("Subtitles"), id="cat-subtitles", classes="cat-item")
                    yield ListItem(Label("Media & Chapters"), id="cat-media", classes="cat-item")
                    yield ListItem(Label("Metadata"), id="cat-metadata", classes="cat-item")
                    yield ListItem(Label("Proxy & Geo"), id="cat-proxy", classes="cat-item")
                    yield ListItem(Label("Appearance"), id="cat-appearance", classes="cat-item")

            # Right Content Panel: Active Category Pane
            with ContentSwitcher(initial="pane-general", id="settings-content-switcher"):

                # 1. General & Download Paths
                with Vertical(id="pane-general", classes="settings-pane"):
                    yield Label("General & Download Destination", classes="pane-title")
                    yield Label("Configure where downloads are stored and how filenames are formatted.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Download Directory:", classes="setting-label")
                        yield Input(value=self.config.download_dir, id="inp-download-dir", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Filename Template:", classes="setting-label")
                        yield Input(value=self.config.filename_template, id="inp-filename-tmpl", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Custom FFmpeg Path:", classes="setting-label")
                        yield Input(value=getattr(self.config, "ffmpeg_location", ""), id="inp-ffmpeg-location", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("FFmpeg Status:", classes="setting-label")
                        yield Label(self._get_ffmpeg_status_text(), id="lbl-settings-ffmpeg-status")
                    with Horizontal(classes="setting-row"):
                        yield Label("FFmpeg Setup:", classes="setting-label")
                        ffmpeg_detected = is_ffmpeg_available(getattr(self.config, "ffmpeg_location", ""))
                        btn = Button(
                            "✅ FFmpeg Ready" if ffmpeg_detected else "📥 Setup / Download FFmpeg",
                            id="btn-settings-ffmpeg-setup",
                            variant="default" if ffmpeg_detected else "primary",
                            disabled=ffmpeg_detected,
                        )
                        yield btn

                # 2. Bandwidth & Concurrency
                with Vertical(id="pane-bandwidth", classes="settings-pane"):
                    yield Label("Bandwidth & Queue Management", classes="pane-title")
                    yield Label("Control download speed limits, retry behavior, and concurrency.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Max Concurrent Downloads:", classes="setting-label")
                        yield Input(value=str(self.config.max_concurrent_downloads), id="inp-max-concurrent", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Rate Limit (0 = unlimited):", classes="setting-label")
                        yield Input(value=str(self.config.rate_limit), id="inp-rate-limit", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Max Connection Retries:", classes="setting-label")
                        yield Input(value=str(self.config.retries), id="inp-retries", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Auto-Resume (.part):", classes="setting-label")
                        yield Checkbox("Auto-resume interrupted downloads from byte offset", value=self.config.continuedl, id="cb-continuedl")

                # 3. Authentication & Cookies
                with Vertical(id="pane-auth", classes="settings-pane"):
                    yield Label("Cookies & Account Authentication", classes="pane-title")
                    yield Label("Access private or member-only videos by extracting browser session cookies or using cookies.txt.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Browser Cookies:", classes="setting-label")
                        browsers = [
                            ("None (No Cookies)", "none"),
                            ("Google Chrome", "chrome"),
                            ("Mozilla Firefox", "firefox"),
                            ("Microsoft Edge", "edge"),
                            ("Brave Browser", "brave"),
                            ("Opera", "opera"),
                            ("Vivaldi", "vivaldi"),
                            ("Apple Safari", "safari"),
                        ]
                        yield CycleSelect(browsers, value=self.config.browser_cookies, id="sel-browser-cookies")
                    with Horizontal(classes="setting-row"):
                        yield Label("Custom Cookies.txt Path:", classes="setting-label")
                        yield Input(value=self.config.cookies_file, id="inp-cookies-file", placeholder="C:/path/to/cookies.txt", classes="setting-input")

                    with Horizontal(classes="auth-btn-row"):
                        yield Button("▶ Test Cookie Setup & Auth", id="btn-test-cookies", variant="primary")

                    yield Static(
                        "[dim]Click [bold]▶ Test Cookie Setup & Auth[/bold] to verify your browser cookies or cookies.txt file.[/dim]",
                        id="cookie-diag-box",
                    )

                    yield Static(
                        "[bold cyan]💡 Windows Chrome Cookies Setup Guide:[/]\n"
                        "[dim]• [bold]Why Chrome locks cookies:[/] Google Chrome holds an exclusive lock on its cookie database while running on Windows, and Chrome 127+ enables Windows App-Bound Encryption.\n"
                        "• [bold green]Recommended Fix:[/] Install [bold]'Get cookies.txt LOCALLY'[/bold] extension in Chrome, export your YouTube cookies, and paste the file path in [bold]Custom Cookies.txt Path[/bold] above.\n"
                        "• [bold]Alternative:[/] Close all Google Chrome windows completely before downloading.[/dim]",
                        id="cookie-help-guide",
                    )

                # 4. Subtitles
                with Vertical(id="pane-subtitles", classes="settings-pane"):
                    yield Label("Subtitles Configuration", classes="pane-title")
                    yield Label("Download and embed closed captions or AI-generated subtitles.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Download Subtitles:", classes="setting-label")
                        yield Checkbox("Enable Subtitle Downloads", value=self.config.download_subtitles, id="cb-subtitles")
                    with Horizontal(classes="setting-row"):
                        yield Label("Auto-Generated Subtitles:", classes="setting-label")
                        yield Checkbox("Include AI / Auto-generated Subtitles", value=self.config.auto_generated_subtitles, id="cb-auto-subtitles")
                    with Horizontal(classes="setting-row"):
                        yield Label("Subtitle Mode:", classes="setting-label")
                        sub_modes = [
                            ("Embed inside Video", "embed"),
                            ("Save External File (.srt)", "external"),
                            ("Embed & Keep External (.srt)", "both"),
                        ]
                        yield CycleSelect(sub_modes, value=self.config.subtitle_mode, id="sel-subtitle-mode")
                    with Horizontal(classes="setting-row"):
                        yield Label("Languages (comma-separated):", classes="setting-label")
                        yield Input(value=self.config.subtitle_langs, id="inp-subtitle-langs", placeholder="en,es,ja,all", classes="setting-input")

                # 5. Thumbnails & Chapters
                with Vertical(id="pane-media", classes="settings-pane"):
                    yield Label("Thumbnails & Video Chapters", classes="pane-title")
                    yield Label("Embed artwork and chapters, or remove community-reported promotions with SponsorBlock.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Download Cover Art:", classes="setting-label")
                        yield Checkbox("Download / Embed Cover Artwork", value=self.config.download_thumbnail, id="cb-thumbnail")
                    with Horizontal(classes="setting-row"):
                        yield Label("Thumbnail Mode:", classes="setting-label")
                        thumb_modes = [("Embed into Media File", "embed"), ("Save as Image (.jpg / .webp)", "file")]
                        yield CycleSelect(thumb_modes, value=self.config.thumbnail_mode, id="sel-thumbnail-mode")
                    with Horizontal(classes="setting-row"):
                        yield Label("Embed Chapter Markers:", classes="setting-label")
                        yield Checkbox("Embed Chapter metadata", value=self.config.embed_chapters, id="cb-chapters")
                    with Horizontal(classes="setting-row"):
                        yield Label("Split Video into Chapters:", classes="setting-label")
                        yield Checkbox("Split into separate chapter files (--split-chapters)", value=self.config.split_chapters, id="cb-split-chapters")
                    with Horizontal(classes="setting-row"):
                        yield Label("Remove Promotions:", classes="setting-label")
                        yield Checkbox("Cut SponsorBlock segments from downloaded media", value=self.config.remove_sponsor_segments, id="cb-sponsorblock-remove")
                    with Horizontal(classes="setting-row"):
                        yield Label("SponsorBlock Categories:", classes="setting-label")
                        yield Input(
                            value=self.config.sponsorblock_categories,
                            id="inp-sponsorblock-categories",
                            placeholder="sponsor,selfpromo",
                            classes="setting-input",
                        )

                # 6. Metadata
                with Vertical(id="pane-metadata", classes="settings-pane"):
                    yield Label("Metadata", classes="pane-title")
                    yield Label("Add media information tags to downloaded files.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Embed Metadata Tags:", classes="setting-label")
                        yield Checkbox("Embed Title, Artist, Album, Year tags", value=self.config.embed_metadata, id="cb-metadata")

                # 7. Proxy & Network
                with Vertical(id="pane-proxy", classes="settings-pane"):
                    yield Label("Proxy & Geo-Bypass", classes="pane-title")
                    yield Label("Configure network routing to bypass geographic restrictions.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Proxy URL:", classes="setting-label")
                        yield Input(value=self.config.proxy, id="inp-proxy", placeholder="socks5://127.0.0.1:1080 or http://127.0.0.1:8080", classes="setting-input")
                    with Horizontal(classes="setting-row"):
                        yield Label("Geo-Bypass:", classes="setting-label")
                        yield Checkbox("Bypass geographic video restrictions", value=self.config.geo_bypass, id="cb-geobypass")

                # 8. Appearance & Themes
                with Vertical(id="pane-appearance", classes="settings-pane"):
                    yield Label("Appearance & RTL Text Settings", classes="pane-title")
                    yield Label("Select themes and configure Arabic / Right-to-Left (RTL) rendering modes.", classes="pane-desc")
                    with Horizontal(classes="setting-row"):
                        yield Label("Theme Profile:", classes="setting-label")
                        yield CycleSelect(THEME_OPTIONS, value=self.config.theme, id="sel-theme")
                    with Horizontal(classes="setting-row"):
                        yield Label("Arabic / RTL Mode:", classes="setting-label")
                        rtl_modes = [
                            ("Reshaped + BiDi (Standard)", "reshaped_bidi"),
                            ("Native Terminal RTL (DirectWrite / HarfBuzz)", "native_raw"),
                            ("BiDi Order Only", "bidi_only"),
                            ("Disabled", "disabled"),
                        ]
                        yield CycleSelect(rtl_modes, value=getattr(self.config, "rtl_mode", "reshaped_bidi"), id="sel-rtl-mode")

        yield Footer()

    def on_mount(self) -> None:
        self._original_theme: str = self.config.theme
        try:
            self.query_one("#category-list", ListView).focus()
        except Exception:
            pass

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Instantly switch the content pane when category selection changes."""
        if event.item and event.item.id in self.PANE_MAP:
            try:
                switcher = self.query_one("#settings-content-switcher", ContentSwitcher)
                switcher.current = self.PANE_MAP[event.item.id]
            except Exception:
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """When a category is selected with Enter, jump focus into its first input."""
        if event.item and event.item.id in self.PANE_MAP:
            pane_id = self.PANE_MAP[event.item.id]
            try:
                switcher = self.query_one("#settings-content-switcher", ContentSwitcher)
                switcher.current = pane_id
                self._focus_first_in_pane(pane_id)
            except Exception:
                pass

    def _focus_first_in_pane(self, pane_id: str) -> None:
        """Focus the first interactive widget inside a pane."""
        try:
            pane = self.query_one(f"#{pane_id}")
            focusable = [w for w in pane.walk_children() if getattr(w, "can_focus", False)]
            if focusable:
                focusable[0].focus()
        except Exception:
            pass

    def on_cycle_select_changed(self, event: CycleSelect.Changed) -> None:
        """Live-preview theme changes without saving."""
        if event.select.id == "sel-theme":
            try:
                self.app.theme = event.value
            except Exception:
                pass

    def on_key(self, event: Key) -> None:
        focused = self.focused
        if not focused:
            return

        cat_list = self.query_one("#category-list", ListView)

        # 1. From category list: press right arrow or enter to enter pane
        if focused == cat_list or isinstance(focused, ListItem):
            if event.key in ("right", "l"):
                switcher = self.query_one("#settings-content-switcher", ContentSwitcher)
                if switcher.current:
                    self._focus_first_in_pane(switcher.current)
                    event.prevent_default()
                    event.stop()
            return

        # 2. Inside a pane: navigate between inputs
        switcher = self.query_one("#settings-content-switcher", ContentSwitcher)
        if switcher.current:
            try:
                pane = self.query_one(f"#{switcher.current}")
                focusable = [w for w in pane.walk_children() if getattr(w, "can_focus", False)]
            except Exception:
                focusable = []

            if focusable and focused in focusable:
                idx = focusable.index(focused)
                if event.key in ("down",):
                    next_w = focusable[(idx + 1) % len(focusable)]
                    next_w.focus()
                    event.prevent_default()
                    event.stop()
                elif event.key in ("up",):
                    prev_w = focusable[(idx - 1) % len(focusable)]
                    prev_w.focus()
                    event.prevent_default()
                    event.stop()
                elif event.key in ("left",) and not isinstance(focused, Input):
                    # Return focus to category list when on checkbox/select
                    cat_list.focus()
                    event.prevent_default()
                    event.stop()
                elif event.key in ("enter", "space") and isinstance(focused, Checkbox):
                    focused.value = not focused.value
                    event.prevent_default()
                    event.stop()

    def _get_ffmpeg_status_text(self) -> str:
        loc = getattr(self.config, "ffmpeg_location", "")
        if is_ffmpeg_available(loc):
            ver = get_ffmpeg_version(loc) or "Detected"
            return f"✅ Installed ({ver[:35]})"
        return "⚠️ Not Detected (Click Setup below)"

    def _save_form_values(self) -> None:
        raw_dl = self.query_one("#inp-download-dir", Input).value
        self.config.download_dir = sanitize_path(raw_dl) or get_default_download_dir()
        self.config.filename_template = self.query_one("#inp-filename-tmpl", Input).value.strip()

        raw_ffmpeg = self.query_one("#inp-ffmpeg-location", Input).value
        self.config.ffmpeg_location = sanitize_path(raw_ffmpeg)

        concur_str = self.query_one("#inp-max-concurrent", Input).value.strip()
        self.config.max_concurrent_downloads = max(1, int(concur_str) if concur_str.isdigit() else 3)

        self.config.rate_limit = self.query_one("#inp-rate-limit", Input).value.strip()

        retries_str = self.query_one("#inp-retries", Input).value.strip()
        self.config.retries = int(retries_str) if retries_str.isdigit() else 10

        self.config.continuedl = self.query_one("#cb-continuedl", Checkbox).value

        sel_browser = self.query_one("#sel-browser-cookies", CycleSelect).value
        self.config.browser_cookies = str(sel_browser) if sel_browser else "none"
        raw_cookies = self.query_one("#inp-cookies-file", Input).value
        self.config.cookies_file = sanitize_path(raw_cookies)

        self.config.download_subtitles = self.query_one("#cb-subtitles", Checkbox).value
        self.config.auto_generated_subtitles = self.query_one("#cb-auto-subtitles", Checkbox).value
        sel_sub_mode = self.query_one("#sel-subtitle-mode", CycleSelect).value
        self.config.subtitle_mode = str(sel_sub_mode) if sel_sub_mode else "embed"
        self.config.subtitle_langs = self.query_one("#inp-subtitle-langs", Input).value.strip()

        self.config.download_thumbnail = self.query_one("#cb-thumbnail", Checkbox).value
        sel_thumb_mode = self.query_one("#sel-thumbnail-mode", CycleSelect).value
        self.config.thumbnail_mode = str(sel_thumb_mode) if sel_thumb_mode else "embed"
        self.config.embed_chapters = self.query_one("#cb-chapters", Checkbox).value
        self.config.split_chapters = self.query_one("#cb-split-chapters", Checkbox).value
        self.config.remove_sponsor_segments = self.query_one("#cb-sponsorblock-remove", Checkbox).value
        raw_sponsorblock_categories = self.query_one("#inp-sponsorblock-categories", Input).value
        self.config.sponsorblock_categories = sanitize_sponsorblock_categories(raw_sponsorblock_categories)

        self.config.embed_metadata = self.query_one("#cb-metadata", Checkbox).value

        self.config.proxy = self.query_one("#inp-proxy", Input).value.strip()
        self.config.geo_bypass = self.query_one("#cb-geobypass", Checkbox).value

        sel_theme = self.query_one("#sel-theme", CycleSelect).value
        self.config.theme = str(sel_theme) if sel_theme else "shadcn-zinc"

        sel_rtl = self.query_one("#sel-rtl-mode", CycleSelect).value
        self.config.rtl_mode = str(sel_rtl) if sel_rtl else "reshaped_bidi"

    def action_save_settings(self) -> None:
        try:
            self._save_form_values()
            self.config.save()
            try:
                from manager import DownloadManager

                DownloadManager.get_instance().config = self.config
            except Exception:
                pass
            try:
                self.app.theme = self.config.theme
            except Exception:
                pass
            try:
                set_rtl_mode(self.config.rtl_mode)
            except Exception:
                pass
            self.notify("Settings saved successfully", title="Saved", severity="information")
            self.app.switch_screen("search_screen")
        except Exception as e:
            self.notify(f"Could not save settings: {e}", title="Error", severity="error")

    def action_reset_defaults(self) -> None:
        self.config = AppConfig()
        self.config.save()
        self.notify("Settings reset to defaults", title="Reset", severity="warning")
        self.app.switch_screen("search_screen")
        self.app.switch_screen("settings_screen")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-test-cookies":
            self.action_test_cookies()
        elif event.button.id == "btn-settings-ffmpeg-setup":
            self.app.push_screen(FfmpegSetupModal(is_first_launch=False), callback=self._on_ffmpeg_modal_closed)

    def _on_ffmpeg_modal_closed(self, result: Optional[bool]) -> None:
        try:
            self.config = AppConfig.load()
            lbl = self.query_one("#lbl-settings-ffmpeg-status", Label)
            lbl.update(self._get_ffmpeg_status_text())
            inp = self.query_one("#inp-ffmpeg-location", Input)
            inp.value = getattr(self.config, "ffmpeg_location", "")
            btn = self.query_one("#btn-settings-ffmpeg-setup", Button)
            detected = is_ffmpeg_available(getattr(self.config, "ffmpeg_location", ""))
            btn.label = "✅ FFmpeg Ready" if detected else "📥 Setup / Download FFmpeg"
            btn.variant = "default" if detected else "primary"
            btn.disabled = detected
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def action_test_cookies(self) -> None:
        try:
            sel_browser = self.query_one("#sel-browser-cookies", CycleSelect).value
            raw_cookie_file = self.query_one("#inp-cookies-file", Input).value
            cookie_file = sanitize_path(raw_cookie_file)
        except Exception:
            return

        self.app.call_from_thread(
            self._update_cookie_diag,
            "[bold yellow]⏳ Testing cookie extraction and checking YouTube authentication...[/]",
        )

        res = YtDlpEngine.test_cookie_setup(browser=sel_browser, cookies_file=cookie_file)

        if res["success"]:
            msg = (
                f"[bold green]✔ SUCCESS: {res['message']}[/]\n"
                f"[dim green]• {res['recommendation']}[/]"
            )
            self.app.call_from_thread(self._update_cookie_diag, msg)
            self.app.call_from_thread(
                self.notify,
                f"Cookies verified: {res['count']} loaded",
                title="Cookie Test Passed",
                severity="information",
            )
        else:
            msg = (
                f"[bold red]✖ ERROR: {res['message']}[/]\n"
                f"[bold yellow]Recommendation:[/] {res['recommendation']}"
            )
            self.app.call_from_thread(self._update_cookie_diag, msg)
            self.app.call_from_thread(
                self.notify,
                res["message"][:60],
                title="Cookie Test Failed",
                severity="error",
            )

    def _update_cookie_diag(self, markup: str) -> None:
        try:
            box = self.query_one("#cookie-diag-box", Static)
            box.update(markup)
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def action_update_ytdlp(self) -> None:
        self.app.call_from_thread(self.notify, "Running yt-dlp self-update...", title="Updating", severity="information")
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                self.app.call_from_thread(self.notify, "yt-dlp updated successfully", title="Update Complete", severity="information")
            else:
                self.app.call_from_thread(self.notify, f"Update error: {res.stderr[:60]}", title="Update Failed", severity="error")
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Update failed: {e}", title="Error", severity="error")

    def action_go_back(self) -> None:
        try:
            self.app.theme = self._original_theme
        except Exception:
            pass
        self.config = AppConfig.load()
        self.app.switch_screen("search_screen")
