"""Settings screen: category sidebar with one form pane per category, driven by a field table."""

import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Button, Checkbox, ContentSwitcher, Footer, Header, Input, Label, ListItem, ListView, Static

from ..config import AppConfig, is_valid_rate_limit
from ..ffmpeg_utils import get_ffmpeg_version
from ..rtl_utils import markup_safe
from ..themes import THEME_OPTIONS
from ..widgets.cycle_select import CycleSelect
from ..ytdlp_engine import YtDlpEngine
from .ffmpeg_modal import FfmpegSetupModal

BROWSERS = [
    ("None (No Cookies)", "none"),
    ("Google Chrome", "chrome"),
    ("Mozilla Firefox", "firefox"),
    ("Microsoft Edge", "edge"),
    ("Brave Browser", "brave"),
    ("Opera", "opera"),
    ("Vivaldi", "vivaldi"),
    ("Apple Safari", "safari"),
]
SUBTITLE_MODES = [("Embed inside Video", "embed"), ("Save External File (.srt)", "external"), ("Embed & Keep External (.srt)", "both")]
THUMBNAIL_MODES = [("Embed into Media File", "embed"), ("Save as Image (.jpg)", "file")]
RTL_MODES = [
    ("Reshaped + BiDi (Standard)", "reshaped_bidi"),
    ("Native Terminal RTL (DirectWrite / HarfBuzz)", "native_raw"),
    ("BiDi Order Only", "bidi_only"),
    ("Disabled", "disabled"),
]

# One row per setting: (row label, widget id, config field, kind, kind argument)
#   kind "input": argument is the placeholder; "check": checkbox text; "cycle": (label, value) options
Row = Tuple[str, str, str, str, Any]
CATEGORIES: List[Tuple[str, str, str, str, List[Row]]] = [
    ("General & Paths", "pane-general", "General & Download Destination", "Configure where downloads are stored and how filenames are formatted.", [
        ("Download Directory:", "inp-download-dir", "download_dir", "input", ""),
        ("Filename Template:", "inp-filename-tmpl", "filename_template", "input", "%(title)s [%(id)s].%(ext)s"),
        ("Custom FFmpeg Path:", "inp-ffmpeg-location", "ffmpeg_location", "input", "Leave empty to auto-detect"),
    ]),
    ("Bandwidth & Queue", "pane-bandwidth", "Bandwidth & Queue Management", "Control download speed limits, retry behavior, and concurrency.", [
        ("Max Concurrent Downloads:", "inp-max-concurrent", "max_concurrent_downloads", "input", "3"),
        ("Rate Limit (0 = unlimited):", "inp-rate-limit", "rate_limit", "input", "e.g. 500K, 2M"),
        ("Max Connection Retries:", "inp-retries", "retries", "input", "10"),
        ("Auto-Resume (.part):", "cb-continuedl", "continuedl", "check", "Auto-resume interrupted downloads from byte offset"),
    ]),
    ("Cookies & Auth", "pane-auth", "Cookies & Account Authentication", "Access private or member-only videos by extracting browser session cookies or using cookies.txt.", [
        ("Browser Cookies:", "sel-browser-cookies", "browser_cookies", "cycle", BROWSERS),
        ("Custom Cookies.txt Path:", "inp-cookies-file", "cookies_file", "input", "C:/path/to/cookies.txt"),
    ]),
    ("Subtitles", "pane-subtitles", "Subtitles Configuration", "Download and embed closed captions or AI-generated subtitles.", [
        ("Download Subtitles:", "cb-subtitles", "download_subtitles", "check", "Enable Subtitle Downloads"),
        ("Auto-Generated Subtitles:", "cb-auto-subtitles", "auto_generated_subtitles", "check", "Include AI / Auto-generated Subtitles"),
        ("Subtitle Mode:", "sel-subtitle-mode", "subtitle_mode", "cycle", SUBTITLE_MODES),
        ("Languages (comma-separated):", "inp-subtitle-langs", "subtitle_langs", "input", "en,es,ja,all"),
    ]),
    ("Media & Chapters", "pane-media", "Thumbnails & Video Chapters", "Embed artwork and chapters, or remove community-reported promotions with SponsorBlock.", [
        ("Download Cover Art:", "cb-thumbnail", "download_thumbnail", "check", "Download / Embed Cover Artwork"),
        ("Thumbnail Mode:", "sel-thumbnail-mode", "thumbnail_mode", "cycle", THUMBNAIL_MODES),
        ("Embed Chapter Markers:", "cb-chapters", "embed_chapters", "check", "Embed Chapter metadata"),
        ("Split Video into Chapters:", "cb-split-chapters", "split_chapters", "check", "Split into separate chapter files (--split-chapters)"),
        ("Remove Promotions:", "cb-sponsorblock-remove", "remove_sponsor_segments", "check", "Cut SponsorBlock segments from downloaded media"),
        ("SponsorBlock Categories:", "inp-sponsorblock-categories", "sponsorblock_categories", "input", "sponsor,selfpromo"),
    ]),
    ("Metadata", "pane-metadata", "Metadata", "Add media information tags to downloaded files.", [
        ("Embed Metadata Tags:", "cb-metadata", "embed_metadata", "check", "Embed Title, Artist, Album, Year tags"),
    ]),
    ("Proxy & Geo", "pane-proxy", "Proxy & Geo-Bypass", "Configure network routing to bypass geographic restrictions.", [
        ("Proxy URL:", "inp-proxy", "proxy", "input", "socks5://127.0.0.1:1080 or http://127.0.0.1:8080"),
        ("Geo-Bypass:", "cb-geobypass", "geo_bypass", "check", "Bypass geographic video restrictions"),
    ]),
    ("Appearance", "pane-appearance", "Appearance & RTL Text Settings", "Select themes and configure Arabic / Right-to-Left (RTL) rendering modes.", [
        ("Theme Profile:", "sel-theme", "theme", "cycle", THEME_OPTIONS),
        ("Arabic / RTL Mode:", "sel-rtl-mode", "rtl_mode", "cycle", RTL_MODES),
    ]),
]
FORM_FIELDS: Dict[str, str] = {widget_id: name for *_, rows in CATEGORIES for _, widget_id, name, _, _ in rows}

COOKIE_GUIDE = (
    "[bold cyan]💡 Windows Chrome Cookies Setup Guide:[/]\n"
    "[dim]• [bold]Why Chrome locks cookies:[/] Google Chrome holds an exclusive lock on its cookie database while running on Windows, and Chrome 127+ enables Windows App-Bound Encryption.\n"
    "• [bold green]Recommended Fix:[/] Install [bold]'Get cookies.txt LOCALLY'[/bold] extension in Chrome, export your YouTube cookies, and paste the file path in [bold]Custom Cookies.txt Path[/bold] above.\n"
    "• [bold]Alternative:[/] Close all Google Chrome windows completely before downloading.[/dim]"
)


class SettingsScreen(Screen):
    """Edit settings; Ctrl+S saves and applies them app-wide, Esc discards."""

    DEFAULT_CSS = """
    SettingsScreen {
        background: $background;
    }
    #settings-main-container {
        height: 1fr;
    }
    #settings-sidebar {
        width: 28;
        height: 100%;
        background: $surface;
        border-right: solid $border;
    }
    #sidebar-header-label {
        height: 1;
        width: 100%;
        background: $panel;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #category-list {
        height: 1fr;
        background: transparent;
    }
    .cat-item {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #settings-content-switcher {
        height: 100%;
        width: 1fr;
    }
    .settings-pane {
        height: 100%;
        padding: 1 2;
    }
    .pane-title {
        color: $primary;
        text-style: bold;
    }
    .pane-desc {
        color: $text-muted;
        margin-bottom: 1;
    }
    .setting-row {
        height: 1;
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
        color: $text-muted;
    }
    .setting-row:focus-within .setting-label {
        color: $foreground;
        text-style: bold;
    }
    .setting-input {
        width: 1fr;
        background: $background;
    }
    .setting-input:focus {
        background: $boost;
    }
    .auth-btn-row {
        height: 1;
        margin: 1 0;
    }
    #btn-test-cookies {
        width: 100%;
    }
    #cookie-diag-box {
        height: auto;
        min-height: 2;
        background: $surface;
        border: solid $border;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cookie-help-guide {
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
    ]

    PANE_MAP = {f"cat-{pane_id[5:]}": pane_id for _, pane_id, *_ in CATEGORIES}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dialog_open = False  # a dialog on top suspends/resumes us without leaving the screen

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="settings-main-container"):
            with Vertical(id="settings-sidebar"):
                yield Label("CATEGORIES", id="sidebar-header-label")
                yield ListView(
                    *(ListItem(Label(name), id=f"cat-{pane_id[5:]}", classes="cat-item") for name, pane_id, *_ in CATEGORIES),
                    id="category-list",
                    initial_index=0,
                )
            with ContentSwitcher(initial="pane-general", id="settings-content-switcher"):
                for _, pane_id, title, desc, rows in CATEGORIES:
                    with Vertical(id=pane_id, classes="settings-pane"):
                        yield Label(title, classes="pane-title")
                        yield Label(desc, classes="pane-desc")
                        for label, widget_id, _, kind, arg in rows:
                            with Horizontal(classes="setting-row"):
                                yield Label(label, classes="setting-label")
                                yield self._make_widget(widget_id, kind, arg)
                        yield from self._compose_extras(pane_id)
        yield Footer()

    @staticmethod
    def _make_widget(widget_id: str, kind: str, arg: Any):
        if kind == "check":
            return Checkbox(arg, id=widget_id)
        if kind == "cycle":
            return CycleSelect(arg, value=arg[0][1], id=widget_id)
        return Input(placeholder=arg, id=widget_id, classes="setting-input")

    def _compose_extras(self, pane_id: str) -> ComposeResult:
        if pane_id == "pane-general":
            with Horizontal(classes="setting-row"):
                yield Label("FFmpeg Status:", classes="setting-label")
                yield Label("Checking...", id="lbl-settings-ffmpeg-status")
            with Horizontal(classes="setting-row"):
                yield Label("FFmpeg Setup:", classes="setting-label")
                yield Button("📥 Setup / Download FFmpeg", id="btn-settings-ffmpeg-setup", variant="primary")
        elif pane_id == "pane-auth":
            with Horizontal(classes="auth-btn-row"):
                yield Button("▶ Test Cookie Setup & Auth", id="btn-test-cookies", variant="primary")
            yield Static("[dim]Click [bold]▶ Test Cookie Setup & Auth[/bold] to verify your browser cookies or cookies.txt file.[/dim]", id="cookie-diag-box")
            yield Static(COOKIE_GUIDE, id="cookie-help-guide")

    def on_mount(self) -> None:
        self._load_form(self.app.config)
        self.query_one("#category-list", ListView).focus()

    def on_screen_suspend(self) -> None:
        if not self._dialog_open:
            self.app.theme = self.app.config.theme  # leaving without saving drops the live preview

    def on_screen_resume(self) -> None:
        if self._dialog_open:
            self._dialog_open = False
        else:
            self._load_form(self.app.config)  # unsaved edits from a previous visit are discarded

    # ------------------------------------------------------------------ form <-> config

    def _load_form(self, config: AppConfig) -> None:
        for widget_id, name in FORM_FIELDS.items():
            widget = self.query_one(f"#{widget_id}")
            value = getattr(config, name)
            widget.value = value if isinstance(widget, Checkbox) else str(value)
        self.refresh_ffmpeg_status()

    def _read_form(self) -> Dict[str, Any]:
        return {name: self.query_one(f"#{widget_id}").value for widget_id, name in FORM_FIELDS.items()}

    @work(exclusive=True, thread=True, group="ffmpeg-status")
    def refresh_ffmpeg_status(self) -> None:
        """Detect FFmpeg off the UI thread (it may scan directories and spawn a process)."""
        version = get_ffmpeg_version(self.app.config.ffmpeg_location or None)
        self.app.call_from_thread(self._show_ffmpeg_status, version)

    def _show_ffmpeg_status(self, version: Optional[str]) -> None:
        self.query_one("#lbl-settings-ffmpeg-status", Label).update(
            f"✅ Installed ({markup_safe(version[:35])})" if version else "⚠️ Not Detected (Click Setup below)"
        )
        btn = self.query_one("#btn-settings-ffmpeg-setup", Button)
        btn.label = "✅ FFmpeg Ready" if version else "📥 Setup / Download FFmpeg"
        btn.variant = "default" if version else "primary"
        btn.disabled = bool(version)

    # ------------------------------------------------------------------ navigation

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and event.item.id in self.PANE_MAP:
            self.query_one("#settings-content-switcher", ContentSwitcher).current = self.PANE_MAP[event.item.id]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and event.item.id in self.PANE_MAP:
            pane_id = self.PANE_MAP[event.item.id]
            self.query_one("#settings-content-switcher", ContentSwitcher).current = pane_id
            self._focus_in_pane(pane_id, 0)

    def _pane_focusables(self, pane_id: str) -> list:
        return [w for w in self.query_one(f"#{pane_id}").walk_children() if w.focusable]

    def _focus_in_pane(self, pane_id: str, index: int) -> None:
        widgets = self._pane_focusables(pane_id)
        if widgets:
            widgets[index % len(widgets)].focus()

    def on_key(self, event: Key) -> None:
        focused = self.focused
        cat_list = self.query_one("#category-list", ListView)
        current = self.query_one("#settings-content-switcher", ContentSwitcher).current
        if not focused or not current:
            return
        if focused is cat_list:
            if event.key in ("right", "l"):
                self._focus_in_pane(current, 0)
                event.prevent_default()
                event.stop()
            return
        widgets = self._pane_focusables(current)
        if focused not in widgets:
            return
        idx = widgets.index(focused)
        if event.key in ("down", "up"):
            self._focus_in_pane(current, idx + (1 if event.key == "down" else -1))
        elif event.key == "left" and not isinstance(focused, Input):
            cat_list.focus()
        else:
            return
        event.prevent_default()
        event.stop()

    def on_cycle_select_changed(self, event: CycleSelect.Changed) -> None:
        if event.select.id == "sel-theme":  # live preview; reverted on discard
            self.app.theme = event.value

    # ------------------------------------------------------------------ actions

    def action_save_settings(self) -> None:
        values = self._read_form()
        if not is_valid_rate_limit(values["rate_limit"]):
            self.notify("Rate limit must look like 0, 500K, 2M or 1.5G.", title="Invalid Setting", severity="error")
            return
        self.app.apply_config(self.app.config.replace(**values))
        self.notify("Settings saved successfully", title="Saved")
        self.app.navigate("search_screen")

    def action_reset_defaults(self) -> None:
        self._load_form(AppConfig())
        self.app.theme = AppConfig().theme
        self.notify("Default values loaded. Press Ctrl+S to save them or Esc to discard.", title="Defaults", severity="warning")

    def action_go_back(self) -> None:
        self.app.navigate("search_screen")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-test-cookies":
            self.action_test_cookies()
        elif event.button.id == "btn-settings-ffmpeg-setup":
            self._dialog_open = True
            self.app.push_screen(FfmpegSetupModal(is_first_launch=False), callback=self._on_ffmpeg_modal_closed)

    def _on_ffmpeg_modal_closed(self, result: Optional[bool]) -> None:
        self.query_one("#inp-ffmpeg-location", Input).value = self.app.config.ffmpeg_location
        self.refresh_ffmpeg_status()

    @work(exclusive=True, thread=True, group="cookie-test")
    def action_test_cookies(self) -> None:
        browser = self.query_one("#sel-browser-cookies", CycleSelect).value
        cookie_file = self.query_one("#inp-cookies-file", Input).value
        self.app.call_from_thread(self._update_cookie_diag, "[bold yellow]⏳ Testing cookie extraction and checking YouTube authentication...[/]")
        res = YtDlpEngine.test_cookie_setup(browser=browser, cookies_file=cookie_file)
        message, recommendation = markup_safe(res["message"]), markup_safe(res["recommendation"])
        if res["success"]:
            self.app.call_from_thread(self._update_cookie_diag, f"[bold green]✔ SUCCESS: {message}[/]\n[dim green]• {recommendation}[/]")
            self.app.call_from_thread(self.notify, f"Cookies verified: {res['count']} loaded", title="Cookie Test Passed")
        else:
            self.app.call_from_thread(self._update_cookie_diag, f"[bold red]✖ ERROR: {message}[/]\n[bold yellow]Recommendation:[/] {recommendation}")
            self.app.call_from_thread(self.notify, markup_safe(res["message"][:60]), title="Cookie Test Failed", severity="error")

    def _update_cookie_diag(self, markup: str) -> None:
        self.query_one("#cookie-diag-box", Static).update(markup)

    @work(exclusive=True, thread=True, group="update")
    def action_update_ytdlp(self) -> None:
        if getattr(sys, "frozen", False):
            # sys.executable is the app itself in a frozen build; there is no pip to run.
            self.app.call_from_thread(self.notify, "The standalone build bundles yt-dlp. Download a newer YTUI release to update it.", title="Update yt-dlp", severity="warning")
            return
        self.app.call_from_thread(self.notify, "Running yt-dlp self-update...", title="Updating")
        try:
            res = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], capture_output=True, text=True, timeout=120)
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Update failed: {markup_safe(str(e))}", title="Error", severity="error")
            return
        if res.returncode == 0:
            self.app.call_from_thread(self.notify, "yt-dlp updated. Restart YTUI to use the new version.", title="Update Complete")
        else:
            self.app.call_from_thread(self.notify, f"Update error: {markup_safe(res.stderr[-120:])}", title="Update Failed", severity="error")
