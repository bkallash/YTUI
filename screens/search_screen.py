"""Search, URL input, and playlist picker screen styled with shadcn zinc."""

from typing import List, Optional

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Label

from config import AppConfig
from manager import DownloadManager, DownloadTask
from rtl_utils import fix_rtl, rtl_truncate
from ytdlp_engine import ExtractionResult, SearchResultItem, YtDlpEngine, is_url


def truncate_str(s: str, max_len: int = 45) -> str:
    """Truncate string with ellipsis if longer than max_len and format RTL correctly."""
    return rtl_truncate(s, max_len=max_len)



class PlaylistModalScreen(ModalScreen[List[SearchResultItem]]):
    """Modal dialog allowing selection of specific tracks/videos from a playlist."""

    DEFAULT_CSS = """
    PlaylistModalScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.75);
    }
    #playlist-dialog {
        width: 80%;
        height: 75%;
        background: $surface;
        border: solid $border;
        padding: 1;
    }
    .playlist-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        height: 1;
        margin-bottom: 1;
    }
    #playlist-list {
        height: 1fr;
        background: $background;
        border: solid $border;
        padding: 0 1;
        margin-bottom: 1;
    }
    #playlist-actions {
        height: 1;
        align: center middle;
    }
    .modal-btn {
        margin: 0 1;
        height: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_empty", "Cancel"),
    ]

    def __init__(self, title: str, entries: List[SearchResultItem], **kwargs):
        super().__init__(**kwargs)
        self.playlist_title = title
        self.entries = entries
        self.checkboxes: List[Checkbox] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="playlist-dialog"):
            yield Label(f"Playlist: {fix_rtl(self.playlist_title)} ({len(self.entries)} items)", classes="playlist-title")
            with VerticalScroll(id="playlist-list"):
                for i, item in enumerate(self.entries):
                    cb = Checkbox(f"{i+1}. {fix_rtl(item.title)} [{item.duration_str}]", value=True, id=f"cb-item-{i}")
                    self.checkboxes.append(cb)
                    yield cb

            with Horizontal(id="playlist-actions"):
                yield Button("Select All", variant="default", id="btn-select-all", classes="modal-btn")
                yield Button("Deselect All", variant="default", id="btn-deselect-all", classes="modal-btn")
                yield Button(f"Queue Selected ({len(self.entries)})", variant="success", id="btn-queue-selected", classes="modal-btn")
                yield Button("Cancel (Esc)", variant="error", id="btn-cancel", classes="modal-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-select-all":
            for cb in self.checkboxes:
                cb.value = True
        elif btn_id == "btn-deselect-all":
            for cb in self.checkboxes:
                cb.value = False
        elif btn_id == "btn-queue-selected":
            selected = [self.entries[i] for i, cb in enumerate(self.checkboxes) if cb.value]
            self.dismiss(selected)
        elif btn_id == "btn-cancel":
            self.dismiss([])

    def action_dismiss_empty(self) -> None:
        self.dismiss([])


class SearchScreen(Screen):
    """Main search screen for entering URLs or searching YouTube keywords."""

    DEFAULT_CSS = """
    SearchScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #search-box-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0 1;
        margin: 0;
        border-bottom: solid $border;
    }
    #search-input-row {
        height: 1;
        width: 100%;
        align: left middle;
        margin-top: 0;
    }
    .search-label {
        color: $primary;
        text-style: bold;
        margin-right: 1;
    }
    #input-query {
        width: 1fr;
        height: 1;
        margin-right: 1;
        background: $background;
        color: $foreground;
        border: none;
    }
    #input-query:focus {
        background: $panel;
        color: $foreground;
        text-style: bold;
    }
    #btn-search {
        min-width: 12;
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $primary;
    }
    #btn-search:focus, #btn-search:hover {
        background: $primary;
        color: $background;
        text-style: bold;
    }
    #search-hints {
        color: $text-muted;
        height: 1;
        width: 100%;
    }
    #results-container {
        height: 1fr;
        width: 100%;
        margin: 0;
        padding: 0;
        background: $background;
    }
    #results-table {
        height: 100%;
        width: 100%;
        background: $background;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "focus_search", "Search", show=True),
        Binding("ctrl+j", "app.switch_to_downloads", "Queue", show=True),
        Binding("ctrl+y", "app.switch_to_history", "History", show=True),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=True),
        Binding("ctrl+q", "app.quit_app", "Quit", show=True),
        Binding("slash", "focus_search", "Focus Search", show=False),
    ]

    def __init__(self, config: Optional[AppConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or AppConfig.load()
        self.search_results: List[SearchResultItem] = []
        self.is_loading = False
        self.cols_initialized = False
        self.col_keys = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="search-box-container"):
            with Horizontal(id="search-input-row"):
                yield Label("Search / URL:", classes="search-label")
                yield Input(
                    placeholder="Paste video URL or type keywords (e.g. 'lofi beats')...",
                    id="input-query",
                )
                yield Button("Search / Fetch", id="btn-search")

            yield Label("Tips: Paste direct links (YouTube, Twitter, SoundCloud, TikTok, Vimeo, Reddit) or type keywords.", id="search-hints")

        with Vertical(id="results-container"):
            yield DataTable(id="results-table", cursor_type="row")

        yield Footer()

    def on_mount(self) -> None:
        self._update_table_columns()
        self.query_one("#input-query", Input).focus()

    def on_resize(self, event) -> None:
        self._update_table_columns()
        if self.search_results:
            self._populate_results_table(self.search_results)

    def _update_table_columns(self) -> None:
        table = self.query_one("#results-table", DataTable)
        screen_w = max(72, self.size.width)
        # Dedicated: # (3) + Duration (8) + Views (11) = 22 (+4 padding = 26)
        rem = max(35, screen_w - 26)
        title_w = max(20, int(rem * 0.60))
        chan_w = max(12, rem - title_w)

        if not self.cols_initialized:
            c0 = table.add_column("#", width=3)
            c1 = table.add_column("Title", width=title_w)
            c2 = table.add_column("Channel", width=chan_w)
            c3 = table.add_column("Duration", width=8)
            c4 = table.add_column("Views", width=11)
            self.col_keys = [c0, c1, c2, c3, c4]
            self.cols_initialized = True
        else:
            table.columns[self.col_keys[1]].width = title_w
            table.columns[self.col_keys[2]].width = chan_w
            table.refresh()

    def action_focus_search(self) -> None:
        self.query_one("#input-query", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "down":
            inp = self.query_one("#input-query", Input)
            if inp.has_focus:
                table = self.query_one("#results-table", DataTable)
                if table.row_count > 0:
                    table.focus()
                    event.prevent_default()
                    event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.process_query()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search":
            self.process_query()

    def process_query(self) -> None:
        inp = self.query_one("#input-query", Input)
        query = inp.value.strip()
        if not query:
            self.notify("Please enter a URL or search keywords.", severity="warning")
            return

        if is_url(query):
            self.extract_url_formats(query)
        else:
            self.perform_search(query)

    @work(exclusive=True, thread=True)
    def perform_search(self, query: str) -> None:
        self.app.call_from_thread(self._set_loading, True, f"Searching YouTube for '{query}'...")
        results = YtDlpEngine.search(query, max_results=25, config=self.config)
        self.search_results = results
        self.app.call_from_thread(self._populate_results_table, results)
        self.app.call_from_thread(self._set_loading, False)

    @work(exclusive=True, thread=True)
    def extract_url_formats(self, url: str) -> None:
        self.app.call_from_thread(self._set_loading, True, f"Extracting formats for {url}...")
        try:
            extraction = YtDlpEngine.extract_info(url, config=self.config)
            self.app.call_from_thread(self._handle_extraction_result, extraction)
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Extraction failed: {e}", title="Error", severity="error")
        finally:
            self.app.call_from_thread(self._set_loading, False)

    def _set_loading(self, loading: bool, message: str = "") -> None:
        self.is_loading = loading
        table = self.query_one("#results-table", DataTable)
        hints = self.query_one("#search-hints", Label)
        if loading:
            table.loading = True
            if message:
                hints.update(f"[bold]Status:[/] {message}")
        else:
            table.loading = False
            hints.update("Tips: Paste direct links (YouTube, Twitter, SoundCloud, TikTok, Vimeo, Reddit) or type keywords.")

    def _populate_results_table(self, results: List[SearchResultItem]) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()
        if not results:
            self.notify("No results found.", severity="warning")
            return

        screen_w = max(80, self.size.width)
        max_title_len = max(35, screen_w - 52)
        max_uploader_len = max(18, min(35, screen_w // 5))

        for i, item in enumerate(results):
            table.add_row(
                str(i + 1),
                truncate_str(item.title, max_len=max_title_len),
                truncate_str(item.uploader, max_len=max_uploader_len),
                item.duration_str,
                item.formatted_views or "Video",
                key=item.url,
            )

        if len(results) > 0:
            try:
                table.cursor_coordinate = (0, 0)
            except Exception:
                pass
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        selected_url = str(event.row_key.value) if event.row_key else ""
        if selected_url:
            self.extract_url_formats(selected_url)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        selected_url = str(event.row_key.value) if event.row_key else ""
        if selected_url:
            self.extract_url_formats(selected_url)

    def _handle_extraction_result(self, extraction: ExtractionResult) -> None:
        if extraction.is_playlist:
            if not extraction.playlist_entries:
                self.notify("Playlist is empty or contains no accessible videos.", title="Empty Playlist", severity="warning")
                return
            from screens.playlist_screen import PlaylistScreen

            self.app.push_screen(PlaylistScreen(extraction, config=self.config))
        else:
            from screens.format_screen import FormatScreen

            self.app.push_screen(FormatScreen(extraction, config=self.config))
