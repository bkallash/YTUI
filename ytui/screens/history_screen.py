"""Download history (library) screen."""

import time
from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key, Resize
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label

from ..history import HistoryItem, HistoryManager
from ..rtl_utils import markup_safe, rtl_truncate
from .common import flexible_width

POLL_INTERVAL = 0.5
FIXED_WIDTHS = {"num": 3, "date": 16, "duration": 8, "size": 9, "format": 16}
CONFIRM_WINDOW = 3.0  # seconds to press Clear again


class HistoryScreen(Screen):
    """Browse, filter, open and re-download completed downloads."""

    DEFAULT_CSS = """
    HistoryScreen {
        background: $background;
    }
    #history-header-container {
        height: auto;
        background: $surface;
        border-bottom: solid $border;
    }
    #history-header-bar {
        height: 1;
        width: 100%;
        text-align: center;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #history-search-container {
        height: auto;
        padding: 0 1 1 1;
    }
    #history-search-input {
        background: $background;
    }
    #history-search-input:focus {
        background: $panel;
    }
    #history-table {
        height: 1fr;
    }
    #history-preview-bar {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0 1;
        border-top: solid $border;
    }
    """

    BINDINGS = [
        Binding("slash,ctrl+f", "focus_search", "Filter", show=True),
        Binding("enter,o", "open_selected_file", "Open", show=True),
        Binding("f", "open_selected_folder", "Folder", show=True),
        Binding("r", "redownload", "Re-download", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
        Binding("c", "clear_all", "Clear", show=True),
        Binding("escape", "handle_escape", "Back", show=True),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history_mgr: Optional[HistoryManager] = None
        self._filtered_items: List[HistoryItem] = []
        self._seen_version = -1
        self._clear_requested_at = 0.0

    @property
    def history_mgr(self) -> HistoryManager:
        return self._history_mgr or self.app.history

    @history_mgr.setter
    def history_mgr(self, manager: HistoryManager) -> None:
        self._history_mgr = manager

    @property
    def selected_item(self) -> Optional[HistoryItem]:
        row = self.query_one("#history-table", DataTable).cursor_row
        return self._filtered_items[row] if 0 <= row < len(self._filtered_items) else None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="history-header-container"):
            yield Label("HISTORY", id="history-header-bar")
            with Vertical(id="history-search-container"):
                yield Input(placeholder="Search history by title, channel, format, or URL... (/ to focus)", id="history-search-input")
        yield DataTable(id="history-table", cursor_type="row")
        yield Label("Selected: (No item selected)", id="history-preview-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        title_w, chan_w = self._text_column_widths()
        widths = {**FIXED_WIDTHS, "title": title_w, "channel": chan_w}
        for key, label in (("num", "#"), ("date", "Date"), ("title", "Title"), ("channel", "Channel"), ("duration", "Duration"), ("size", "Size"), ("format", "Format")):
            table.add_column(label, width=widths[key], key=key)
        self.set_interval(POLL_INTERVAL, self._poll)
        self.populate_history()
        table.focus()

    def _text_column_widths(self) -> tuple:
        remaining = max(26, flexible_width(self.size.width, FIXED_WIDTHS.values(), column_count=7))
        title_w = max(16, int(remaining * 0.60))
        return title_w, max(10, remaining - title_w)

    def on_resize(self, event: Resize) -> None:
        table = self.query_one("#history-table", DataTable)
        if table.columns:
            table.columns["title"].width, table.columns["channel"].width = self._text_column_widths()
            self.populate_history()

    def on_screen_resume(self) -> None:
        self._poll()

    def _poll(self) -> None:
        if self.history_mgr.version != self._seen_version:
            self.populate_history()

    def populate_history(self, filter_query: Optional[str] = None) -> None:
        manager = self.history_mgr
        self._seen_version = manager.version
        query = (filter_query if filter_query is not None else self.query_one("#history-search-input", Input).value).strip()
        total = len(manager.items)
        items = manager.filter(query)
        self._filtered_items = items

        header = f"HISTORY: Showing {len(items)} of {total} downloads (filter: '{markup_safe(query)}')" if query else f"HISTORY: {total} downloads recorded"
        self.query_one("#history-header-bar", Label).update(header)

        table = self.query_one("#history-table", DataTable)
        title_w, chan_w = table.columns["title"].width, table.columns["channel"].width
        table.clear()
        table.add_rows(
            (str(i + 1), item.formatted_time, rtl_truncate(item.title, title_w), rtl_truncate(item.channel, chan_w), item.duration_str, item.formatted_size, item.format_note)
            for i, item in enumerate(items)
        )
        self._update_preview(self.selected_item)

    def _update_preview(self, item: Optional[HistoryItem]) -> None:
        text = f"File: [bold]{markup_safe(item.title)}[/] | [dim]{markup_safe(item.filepath)}[/]" if item else "Selected: (No matching downloads)"
        self.query_one("#history-preview-bar", Label).update(text)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_preview(self.selected_item)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open_selected_file()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.populate_history(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._focus_table()

    def on_key(self, event: Key) -> None:
        if event.key == "down" and self.query_one("#history-search-input", Input).has_focus and self._focus_table():
            event.prevent_default()
            event.stop()

    def _focus_table(self) -> bool:
        table = self.query_one("#history-table", DataTable)
        if table.row_count:
            table.focus()
        return bool(table.row_count)

    def action_focus_search(self) -> None:
        self.query_one("#history-search-input", Input).focus()

    def action_handle_escape(self) -> None:
        inp = self.query_one("#history-search-input", Input)
        if inp.has_focus and inp.value:
            inp.value = ""  # Input.Changed repopulates the table
            self._focus_table()
        else:
            self.app.navigate("search_screen")

    def action_open_selected_file(self) -> None:
        item = self.selected_item
        if not item:
            self.notify("No file selected", severity="warning")
        elif HistoryManager.open_file(item.filepath):
            self.notify(f"Opening: {markup_safe(item.title)}")
        else:
            self.notify("File does not exist or cannot be opened", title="Not Found", severity="error")

    def action_open_selected_folder(self) -> None:
        item = self.selected_item
        if not item:
            self.notify("No file selected", severity="warning")
        elif HistoryManager.open_folder(item.filepath):
            self.notify("Opened containing folder")
        else:
            self.notify("Could not open containing folder", severity="error")

    def action_delete_selected(self) -> None:
        item = self.selected_item
        if item:
            self.history_mgr.remove(item.id)
            self.populate_history()
            self.notify("Removed entry from history")

    def action_clear_all(self) -> None:
        now = time.monotonic()
        if now - self._clear_requested_at > CONFIRM_WINDOW:
            self._clear_requested_at = now
            self.notify("Press C again to clear the entire history (files are kept).", title="Confirm", severity="warning")
            return
        self._clear_requested_at = 0.0
        self.history_mgr.clear()
        self.populate_history()
        self.notify("History cleared")

    def action_redownload(self) -> None:
        item = self.selected_item
        if item and item.url:
            self.app.navigate("search_screen")
            self.app.get_screen("search_screen").extract_url_formats(item.url)
