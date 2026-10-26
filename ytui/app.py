"""YTUI application: screens, navigation, and app-wide state (config, history, download queue)."""

from textual import work
from textual.app import App
from textual.binding import Binding

from .config import AppConfig
from .ffmpeg_utils import ensure_ffmpeg_in_path, is_ffmpeg_available
from .history import HistoryManager
from .manager import DownloadManager
from .rtl_utils import set_rtl_mode
from .screens.download_screen import DownloadScreen
from .screens.ffmpeg_modal import FfmpegSetupModal
from .screens.history_screen import HistoryScreen
from .screens.search_screen import SearchScreen
from .screens.settings_screen import SettingsScreen
from .themes import register_all_themes


class YtDlpApp(App):
    """Keyboard-driven yt-dlp client with a persistent download queue."""

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
        height: 1;
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
        self.manager = DownloadManager(config=self.config, history=self.history)

    def on_mount(self) -> None:
        register_all_themes(self)
        self._apply_appearance()
        self.push_screen("search_screen")
        self._check_ffmpeg()
        # After the first paint, so the import does not compete with startup rendering.
        self.set_timer(1.0, self._warm_up_ytdlp)

    @work(thread=True, group="startup", exit_on_error=False)
    def _check_ffmpeg(self) -> None:
        """FFmpeg lookup can scan directories on Windows, so it runs off the UI thread."""
        location = self.config.ffmpeg_location or None
        ensure_ffmpeg_in_path(location)
        if not self.config.skip_ffmpeg_check and not is_ffmpeg_available(location):
            self.call_from_thread(lambda: self.push_screen(FfmpegSetupModal(is_first_launch=True)))

    @work(thread=True, group="startup", exit_on_error=False)
    def _warm_up_ytdlp(self) -> None:
        import yt_dlp  # noqa: F401  (~0.4s; makes the first search start instantly)

    def _apply_appearance(self) -> None:
        if self.config.theme in self.available_themes:
            self.theme = self.config.theme
        set_rtl_mode(self.config.rtl_mode)

    def apply_config(self, config: AppConfig) -> None:
        """Make config the live settings for every screen and the download queue, and persist it."""
        self.config = config
        config.save()
        self.manager.set_config(config)
        ensure_ffmpeg_in_path(config.ffmpeg_location or None)
        self._apply_appearance()

    def navigate(self, screen_name: str) -> None:
        """Show a main screen, discarding pushed screens (format pickers, dialogs) above the base one."""
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.switch_screen(screen_name)

    def action_switch_to_search(self) -> None:
        self.navigate("search_screen")

    def action_switch_to_downloads(self) -> None:
        self.navigate("download_screen")

    def action_switch_to_history(self) -> None:
        self.navigate("history_screen")

    def action_switch_to_settings(self) -> None:
        self.navigate("settings_screen")

    def on_unmount(self) -> None:
        self.manager.shutdown()

    def action_quit_app(self) -> None:
        self.exit()


def main() -> None:
    YtDlpApp().run()


if __name__ == "__main__":
    main()
