"""Terminal TUI Application for yt-dlp."""

import sys
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header

from config import AppConfig
from ffmpeg_utils import ensure_ffmpeg_in_path, is_ffmpeg_available
from history import HistoryManager
from manager import DownloadManager
from rtl_utils import set_rtl_mode
from screens.download_screen import DownloadScreen
from screens.ffmpeg_modal import FfmpegSetupModal
from screens.history_screen import HistoryScreen
from screens.search_screen import SearchScreen
from screens.settings_screen import SettingsScreen
from themes import register_all_themes



class YtDlpApp(App):
    """Clean, high-density terminal tool with customizable theme profiles."""

    TITLE = "YTUI"
    SUB_TITLE = "Terminal Media Downloader"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    * {
        scrollbar-background: $surface;
        scrollbar-background-hover: $surface;
        scrollbar-background-active: $panel;
        scrollbar-color: $boost;
        scrollbar-color-hover: $secondary;
        scrollbar-color-active: $primary;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    Screen {
        background: $background;
        color: $foreground;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        scrollbar-background: $surface;
        scrollbar-color: $boost;
        scrollbar-color-hover: $secondary;
        scrollbar-color-active: $primary;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    ScrollBar {
        background: $surface;
        color: $boost;
    }
    ScrollBar.-vertical {
        width: 1;
        background: $surface;
    }
    ScrollBar.-horizontal {
        height: 1;
        background: $surface;
    }
    ScrollBar > .scrollbar--bar {
        color: $boost;
        background: $surface;
    }
    ScrollBar > .scrollbar--bar:hover {
        color: $secondary;
        background: $surface;
    }
    ScrollBar.-active > .scrollbar--bar {
        color: $primary;
        background: $panel;
    }
    ScrollBarCorner {
        background: $surface;
    }
    Header {
        background: $surface;
        color: $primary;
        height: 1;
        dock: top;
    }
    Footer {
        background: $surface;
        color: $text-muted;
        height: 1;
        dock: bottom;
    }
    Footer > .footer--key {
        background: $panel;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    Footer > .footer--description {
        color: $text-muted;
        padding: 0 1 0 0;
    }
    Footer > .footer--highlight {
        background: $boost;
        color: $foreground;
    }
    Input {
        background: $surface;
        border: none;
        height: 1;
        padding: 0 1;
        color: $foreground;
    }
    Input:focus {
        background: $panel;
        color: $foreground;
        text-style: bold;
    }
    Checkbox {
        background: transparent;
        color: $foreground;
        border: none;
        height: auto;
        padding: 0;
    }
    Checkbox:focus {
        background: transparent;
        color: $primary;
        text-style: bold;
    }
    Checkbox > .toggle--label {
        color: $foreground;
        background: transparent;
    }
    Checkbox:focus > .toggle--label {
        color: $primary;
    }
    Checkbox > .toggle--button {
        color: $surface;
        background: $boost;
    }
    Checkbox:focus > .toggle--button {
        color: $background;
        background: $primary;
    }
    Checkbox.-on > .toggle--button {
        color: $background;
        background: $primary;
    }
    DataTable {
        background: $background;
        border: none;
        padding: 0;
        color: $foreground;
    }
    DataTable > .datatable--header {
        background: $surface;
        color: $primary;
        text-style: bold;
        border-bottom: solid $border;
    }
    DataTable > .datatable--cursor {
        background: $panel;
        color: $primary;
        text-style: bold;
    }
    DataTable > .datatable--hover {
        background: $boost;
    }
    ListView {
        background: $background;
        padding: 0;
    }
    ListItem {
        background: transparent;
        margin: 0;
        padding: 0 1;
        border: none;
        color: $foreground;
    }
    ListItem:focus {
        background: $panel;
        color: $primary;
        text-style: bold;
    }
    ProgressBar {
        height: 1;
        padding: 0;
        border: none;
    }
    ProgressBar > .progressbar--bar {
        color: $primary;
        background: $panel;
    }
    ProgressBar > .progressbar--complete {
        color: $success;
    }
    Checkbox {
        background: transparent;
        border: none;
        padding: 0 1;
        height: 1;
    }
    Checkbox > .toggle--label {
        color: $foreground;
    }
    Select {
        background: $surface;
        border: none;
        height: 1;
        padding: 0 1;
    }
    SelectCurrent {
        border: none;
        height: 1;
        padding: 0 1;
    }
    Button {
        height: 1;
        min-width: 6;
        padding: 0 1;
        border: none;
        background: $panel;
        color: $foreground;
    }
    Button:focus, Button:hover {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    Button.-primary {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    Button.-success {
        background: $success;
        color: $background;
        text-style: bold;
    }
    Button.-warning {
        background: $warning;
        color: $background;
        text-style: bold;
    }
    Button.-error {
        background: $error;
        color: $background;
        text-style: bold;
    }
    ToastHolder {
        dock: top;
        align: right top;
        height: auto;
        width: auto;
    }
    Toast {
        background: $surface;
        color: $foreground;
        border: solid $border;
        border-left: thick $primary;
        padding: 0 1;
        width: auto;
        min-width: 32;
        max-width: 60;
    }
    Toast > .toast--title {
        color: $primary;
        text-style: bold;
    }
    Toast > .toast--message {
        color: $text-muted;
    }
    Toast.-information {
        border-left: thick $primary;
    }
    Toast.-warning {
        border-left: thick $warning;
    }
    Toast.-error {
        border-left: thick $error;
    }
    LoadingIndicator {
        color: $primary;
        background: transparent;
        height: 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "switch_to_search", "Search", show=True),
        Binding("ctrl+j", "switch_to_downloads", "Queue", show=True),
        Binding("ctrl+y", "switch_to_history", "History", show=True),
        Binding("ctrl+o", "switch_to_settings", "Config", show=True),
        Binding("ctrl+q", "quit_app", "Quit", show=True),
    ]

    SCREENS = {
        "search_screen": SearchScreen,
        "download_screen": DownloadScreen,
        "history_screen": HistoryScreen,
        "settings_screen": SettingsScreen,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = AppConfig.load()
        self.history = HistoryManager()
        self.manager = DownloadManager.get_instance(config=self.config, history=self.history)

    def on_mount(self) -> None:
        # Register all custom theme profiles
        register_all_themes(self)

        # Apply persisted theme and RTL mode
        try:
            self.theme = self.config.theme
        except Exception:
            pass
        try:
            set_rtl_mode(getattr(self.config, "rtl_mode", "reshaped_bidi"))
        except Exception:
            pass

        # Ensure FFmpeg is configured in PATH
        ensure_ffmpeg_in_path(getattr(self.config, "ffmpeg_location", None))

        self.push_screen("search_screen")

        # Prompt for FFmpeg download on first run / if missing
        if not is_ffmpeg_available(getattr(self.config, "ffmpeg_location", None)) and not getattr(self.config, "skip_ffmpeg_check", False):
            self.push_screen(FfmpegSetupModal(is_first_launch=True))

    def action_switch_to_search(self) -> None:
        self.switch_screen("search_screen")

    def action_switch_to_downloads(self) -> None:
        self.switch_screen("download_screen")

    def action_switch_to_history(self) -> None:
        self.switch_screen("history_screen")

    def action_switch_to_settings(self) -> None:
        self.switch_screen("settings_screen")

    def on_unmount(self) -> None:
        self.manager.shutdown()

    def action_quit_app(self) -> None:
        self.manager.shutdown()
        self.exit()


def main():
    app = YtDlpApp()
    app.run()


if __name__ == "__main__":
    main()
