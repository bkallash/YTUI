"""Download history and library management screen styled with shadcn zinc."""

from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label

from config import AppConfig
from history import HistoryItem, HistoryManager
from rtl_utils import fix_rtl, rtl_truncate


def truncate_str(s: str, max_len: int = 40) -> str:
    """Truncate string with ellipsis if longer than max_len and format RTL correctly."""
    return rtl_truncate(s, max_len=max_len)



class HistoryScreen(Screen):
    """Screen for viewing completed downloads, filtering history, and opening files."""

    DEFAULT_CSS = """
    HistoryScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #history-header-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0;
        margin: 0;
        border-bottom: solid $border;
    }
    #history-header-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: transparent;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #history-search-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0 1 1 1;
    }
    #history-search-input {
        width: 100%;
        border: tall $border;
        background: $background;
        color: $foreground;
    }
    #history-search-input:focus {
        border: tall $primary;
    }
    #history-table-container {
        height: 1fr;
        width: 100%;
        background: $background;
        margin: 0;
        padding: 0;
    }
    #history-table {
        height: 100%;
        width: 100%;
        background: $background;
    }
    #history-preview-bar {
        height: auto;
        width: 100%;
        background: $surface;
        color: $foreground;
        padding: 0 1;
        border-top: solid $border;
    }
    """

    BINDINGS = [
        Binding("slash", "focus_search", "Filter", show=True),
        Binding("ctrl+f", "focus_search", "Filter", show=False),
        Binding("enter", "open_selected_file", "Open", show=True),
        Binding("o", "open_selected_file", "Open", show=False),
        Binding("f", "open_selected_folder", "Folder", show=True),
        Binding("r", "redownload", "Re-download", show=True),
        Binding("d", "delete_selected", "Delete", show=True),
        Binding("c", "clear_all", "Clear", show=True),
        Binding("escape", "handle_escape", "Back", show=True),
        Binding("ctrl+s", "app.switch_to_search", "Search", show=False),
        Binding("ctrl+j", "app.switch_to_downloads", "Queue", show=False),
        Binding("ctrl+y", "refresh_table", "History", show=False),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=False),
        Binding("ctrl+q", "app.quit_app", "Quit", show=True),
    ]

    def __init__(self, config: Optional[AppConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or AppConfig.load()
        self.history_mgr = HistoryManager()
        self.selected_item: Optional[HistoryItem] = None
        self._last_item_count: int = -1  # Force first load
        self._current_search_query: str = ""
        self._filtered_items: List[HistoryItem] = []
        self.cols_initialized = False
        self.col_keys = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="history-header-container"):
            yield Label(f"HISTORY: {len(self.history_mgr.items)} downloads saved", id="history-header-bar")
            with Vertical(id="history-search-container"):
                yield Input(
                    placeholder="Search history by title, channel, format, or URL... (/ to focus)",
                    id="history-search-input",
                )

        with Vertical(id="history-table-container"):
            yield DataTable(id="history-table", cursor_type="row")

        yield Label("Selected: (No item selected)", id="history-preview-bar")

        yield Footer()

    def on_mount(self) -> None:
        self._update_table_columns()
        self.populate_history()
        try:
            from manager import DownloadManager
            self.manager = DownloadManager.get_instance(config=self.config)
            if hasattr(self.manager, "history") and self.manager.history and self.history_mgr.storage_path == self.manager.history.storage_path:
                self.history_mgr = self.manager.history
            self.manager.add_listener(self._on_manager_updated)
        except Exception:
            pass
        try:
            self.query_one("#history-table", DataTable).focus()
        except Exception:
            pass

    def _on_manager_updated(self) -> None:
        self.app.call_from_thread(self._check_history_updates)

    def _check_history_updates(self) -> None:
        mgr = getattr(self, "manager", None)
        active_items = mgr.history.items if (mgr and hasattr(mgr, "history") and mgr.history) else self.history_mgr.items
        if len(active_items) != self._last_item_count:
            if mgr and hasattr(mgr, "history") and mgr.history and self.history_mgr.storage_path == mgr.history.storage_path:
                self.history_mgr = mgr.history
            self.populate_history()

    def on_unmount(self) -> None:
        try:
            if hasattr(self, "manager"):
                self.manager.remove_listener(self._on_manager_updated)
        except Exception:
            pass

    def _update_table_columns(self) -> None:
        table = self.query_one("#history-table", DataTable)
        screen_w = max(72, self.size.width)
        # Fixed cols: # (3) + Date (12) + Duration (8) + Size (8) + Format (14) = 45 (+4 padding = 49)
        rem = max(25, screen_w - 49)
        title_w = max(16, int(rem * 0.60))
        chan_w = max(10, rem - title_w)

        if not self.cols_initialized:
            c0 = table.add_column("#", width=3)
            c1 = table.add_column("Date", width=12)
            c2 = table.add_column("Title", width=title_w)
            c3 = table.add_column("Channel", width=chan_w)
            c4 = table.add_column("Duration", width=8)
            c5 = table.add_column("Size", width=8)
            c6 = table.add_column("Format", width=14)
            self.col_keys = [c0, c1, c2, c3, c4, c5, c6]
            self.cols_initialized = True
        else:
            table.columns[self.col_keys[2]].width = title_w
            table.columns[self.col_keys[3]].width = chan_w
            table.refresh()

    def on_screen_resume(self) -> None:
        items = self.history_mgr.load()
        if len(items) != self._last_item_count:
            self.populate_history()

    def on_resize(self, event) -> None:
        self._update_table_columns()
        self.populate_history()

    def action_focus_search(self) -> None:
        inp = self.query_one("#history-search-input", Input)
        inp.focus()

    def action_handle_escape(self) -> None:
        inp = self.query_one("#history-search-input", Input)
        if inp.has_focus and inp.value:
            inp.value = ""
            self.populate_history("")
            table = self.query_one("#history-table", DataTable)
            if table.row_count > 0:
                table.focus()
        else:
            self.app.switch_screen("search_screen")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "history-search-input":
            self.populate_history(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "history-search-input":
            table = self.query_one("#history-table", DataTable)
            if table.row_count > 0:
                table.focus()

    def on_key(self, event: Key) -> None:
        if event.key == "down":
            inp = self.query_one("#history-search-input", Input)
            if inp.has_focus:
                table = self.query_one("#history-table", DataTable)
                if table.row_count > 0:
                    table.focus()
                    event.prevent_default()
                    event.stop()

    def populate_history(self, filter_query: Optional[str] = None) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        all_items = self.history_mgr.load()

        query_raw = (filter_query if filter_query is not None else self._current_search_query).strip()
        self._current_search_query = query_raw

        items = self.history_mgr.filter(query_raw)
        self._filtered_items = items
        self._last_item_count = len(all_items)

        try:
            lbl = self.query_one("#history-header-bar", Label)
            if query_raw:
                lbl.update(f"HISTORY: Showing {len(items)} of {len(all_items)} downloads (filter: '{query_raw}')")
            else:
                lbl.update(f"HISTORY: {len(all_items)} downloads recorded")
        except Exception:
            pass

        if not items:
            self.selected_item = None
            self._update_preview_for_item(None)
            return

        screen_w = max(72, self.size.width)
        rem = max(25, screen_w - 49)
        title_w = max(16, int(rem * 0.60))
        chan_w = max(10, rem - title_w)

        for i, item in enumerate(items):
            table.add_row(
                str(i + 1),
                item.formatted_time,
                truncate_str(item.title, max_len=title_w),
                truncate_str(item.channel, max_len=chan_w),
                item.duration_str,
                item.formatted_size,
                item.format_note,
                key=f"{item.id}_{i}",
            )

        if items:
            self.selected_item = items[0]
            try:
                table.cursor_coordinate = (0, 0)
            except Exception:
                pass
            try:
                inp = self.query_one("#history-search-input", Input)
                if not inp.has_focus:
                    table.focus()
            except Exception:
                table.focus()
            self._update_preview_for_item(items[0])

    def _update_preview_for_item(self, item: Optional[HistoryItem]) -> None:
        try:
            bar = self.query_one("#history-preview-bar", Label)
            if item:
                bar.update(f"File: [bold]{fix_rtl(item.title)}[/] | [dim]{item.filepath}[/]")
            else:
                bar.update("Selected: (No matching downloads)")
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_id = str(event.row_key.value)
        item_id = row_id.rsplit("_", 1)[0] if "_" in row_id else row_id
        for item in self._filtered_items:
            if item.id == item_id:
                self.selected_item = item
                self._update_preview_for_item(item)
                break
        self.action_open_selected_file()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            row_id = str(event.row_key.value)
            item_id = row_id.rsplit("_", 1)[0] if "_" in row_id else row_id
            for item in self._filtered_items:
                if item.id == item_id:
                    self.selected_item = item
                    self._update_preview_for_item(item)
                    break

    def action_open_selected_file(self) -> None:
        if self.selected_item:
            success = HistoryManager.open_file(self.selected_item.filepath)
            if success:
                self.notify(f"Opening: {fix_rtl(self.selected_item.title)}", severity="information")
            else:
                self.notify("File does not exist or cannot be opened", title="Not Found", severity="error")
        else:
            self.notify("No file selected", severity="warning")

    def action_open_selected_folder(self) -> None:
        if self.selected_item:
            success = HistoryManager.open_folder(self.selected_item.filepath)
            if success:
                self.notify("Opened containing folder", severity="information")
            else:
                self.notify("Could not open containing folder", severity="error")
        else:
            self.notify("No file selected", severity="warning")

    def action_delete_selected(self) -> None:
        if self.selected_item:
            self.history_mgr.remove(self.selected_item.id)
            self.populate_history()
            self.notify("Removed entry from history", severity="information")

    def action_clear_all(self) -> None:
        self.history_mgr.clear()
        self.populate_history()
        self.notify("History cleared", severity="information")

    def action_redownload(self) -> None:
        if self.selected_item and self.selected_item.url:
            search_screen = self.app.get_screen("search_screen")
            self.app.switch_screen("search_screen")
            search_screen.extract_url_formats(self.selected_item.url)

    def action_refresh_table(self) -> None:
        self.populate_history()
