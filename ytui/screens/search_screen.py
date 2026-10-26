"""Search / URL entry screen."""

from typing import List

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key, Resize
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label
from textual.worker import get_current_worker

from ..formats import ExtractionResult, SearchResultItem, is_url
from ..rtl_utils import markup_safe, rtl_truncate
from ..ytdlp_engine import YtDlpEngine
from .format_screen import FormatScreen
from .common import flexible_width
from .playlist_screen import PlaylistScreen

HINT = "Tips: Paste direct links (YouTube, Twitter, SoundCloud, TikTok, Vimeo, Reddit) or type keywords."
FIXED_WIDTHS = (3, 8, 11)  # '#', Duration, Views


class SearchScreen(Screen):
    """Enter a URL to fetch formats, or keywords to search YouTube."""

    DEFAULT_CSS = """
    SearchScreen {
        background: $background;
    }
    #search-box-container {
        height: auto;
        background: $surface;
        padding: 0 1;
        border-bottom: solid $border;
    }
    #search-input-row {
        height: 1;
        align: left middle;
    }
    .search-label {
        color: $primary;
        text-style: bold;
        margin-right: 1;
    }
    #input-query {
        width: 1fr;
        margin-right: 1;
        background: $background;
    }
    #input-query:focus {
        background: $panel;
    }
    #btn-search {
        min-width: 12;
        color: $primary;
    }
    #search-hints {
        color: $text-muted;
        height: 1;
        width: 100%;
    }
    #results-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "focus_search", "Search", show=True),
        Binding("slash", "focus_search", "Focus Search", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.search_results: List[SearchResultItem] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="search-box-container"):
            with Horizontal(id="search-input-row"):
                yield Label("Search / URL:", classes="search-label")
                yield Input(placeholder="Paste video URL or type keywords (e.g. 'lofi beats')...", id="input-query")
                yield Button("Search / Fetch", id="btn-search")
            yield Label(HINT, id="search-hints")
        yield DataTable(id="results-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        title_w, chan_w = self._text_column_widths()
        table.add_column("#", width=3, key="num")
        table.add_column("Title", width=title_w, key="title")
        table.add_column("Channel", width=chan_w, key="channel")
        table.add_column("Duration", width=8, key="duration")
        table.add_column("Views", width=11, key="views")
        self.action_focus_search()

    def _text_column_widths(self) -> tuple:
        remaining = max(35, flexible_width(self.size.width, FIXED_WIDTHS, column_count=5))
        title_w = max(20, int(remaining * 0.60))
        return title_w, max(12, remaining - title_w)

    def on_resize(self, event: Resize) -> None:
        table = self.query_one("#results-table", DataTable)
        if table.columns:
            title_w, chan_w = self._text_column_widths()
            table.columns["title"].width = title_w
            table.columns["channel"].width = chan_w
            self._populate_results_table(self.search_results, quiet=True)

    def action_focus_search(self) -> None:
        self.query_one("#input-query", Input).focus()

    def on_key(self, event: Key) -> None:
        if event.key == "down" and self.query_one("#input-query", Input).has_focus:
            table = self.query_one("#results-table", DataTable)
            if table.row_count:
                table.focus()
                event.prevent_default()
                event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.process_query()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-search":
            self.process_query()

    def process_query(self) -> None:
        query = self.query_one("#input-query", Input).value.strip()
        if not query:
            self.notify("Please enter a URL or search keywords.", severity="warning")
        elif is_url(query):
            self.extract_url_formats(query)
        else:
            self.perform_search(query)

    def _run_job(self, status: str, error_title: str, fn, *args, **kwargs):
        """Run fn on the current worker thread behind a loading state.

        Returns None on failure, or when a newer request superseded this one (exclusive workers).
        """
        worker = get_current_worker()
        self.app.call_from_thread(self._set_loading, True, status)
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            result = None
            if not worker.is_cancelled:
                self.app.call_from_thread(self.notify, f"{error_title}: {markup_safe(str(e))}", title="Error", severity="error")
        if worker.is_cancelled:
            return None
        self.app.call_from_thread(self._set_loading, False)
        return result

    @work(exclusive=True, thread=True)
    def perform_search(self, query: str) -> None:
        results = self._run_job(f"Searching YouTube for '{markup_safe(query)}'...", "Search failed", YtDlpEngine.search, query, max_results=25, config=self.app.config)
        if results is not None:
            self.app.call_from_thread(self._populate_results_table, results)

    @work(exclusive=True, thread=True)
    def extract_url_formats(self, url: str) -> None:
        extraction = self._run_job(f"Extracting formats for {markup_safe(url)}...", "Extraction failed", YtDlpEngine.extract_info, url, config=self.app.config)
        if extraction is not None:
            self.app.call_from_thread(self._handle_extraction_result, extraction)

    def _set_loading(self, loading: bool, message: str = "") -> None:
        self.query_one("#results-table", DataTable).loading = loading
        self.query_one("#search-hints", Label).update(f"[bold]Status:[/] {message}" if loading and message else HINT)

    def _populate_results_table(self, results: List[SearchResultItem], quiet: bool = False) -> None:
        self.search_results = results
        table = self.query_one("#results-table", DataTable)
        table.clear()
        if not results:
            if not quiet:
                self.notify("No results found.", severity="warning")
            return
        title_w = table.columns["title"].width
        chan_w = table.columns["channel"].width
        table.add_rows(
            (str(i + 1), rtl_truncate(item.title, title_w), rtl_truncate(item.uploader, chan_w), item.duration_str, item.formatted_views or "Video")
            for i, item in enumerate(results)
        )
        if not quiet:
            table.move_cursor(row=0)
            table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if 0 <= event.cursor_row < len(self.search_results):
            self.extract_url_formats(self.search_results[event.cursor_row].url)

    def _handle_extraction_result(self, extraction: ExtractionResult) -> None:
        if extraction.is_playlist:
            if not extraction.playlist_entries:
                self.notify("Playlist is empty or contains no accessible videos.", title="Empty Playlist", severity="warning")
                return
            self.app.push_screen(PlaylistScreen(extraction))
        else:
            self.app.push_screen(FormatScreen(extraction))
