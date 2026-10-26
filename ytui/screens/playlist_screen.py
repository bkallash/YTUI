"""Playlist download configurator: track picker, shared format selection, and size estimates."""

from typing import Iterable, List, Set

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Label

from ..formats import (
    DEFAULT_ITEM_DURATION,
    ExtractionResult,
    SearchResultItem,
    estimate_format_bitrates,
    estimate_playlist_size,
    format_bytes,
    format_duration,
)
from ..rtl_utils import markup_safe, rtl_truncate
from ..widgets.format_column import FormatColumnView
from .common import flexible_width
from .selection import FormatSelectionScreen


class PlaylistScreen(FormatSelectionScreen):
    """Select playlist tracks and one format for all of them; tracks queue in playlist order."""

    DEFAULT_CSS = """
    PlaylistScreen {
        background: $background;
    }
    #playlist-header-container {
        height: auto;
        background: $surface;
        border-bottom: solid $border;
    }
    #playlist-meta-bar, #playlist-stats-bar, #playlist-keys-bar {
        height: 1;
        width: 100%;
        text-align: center;
        padding: 0 1;
    }
    #playlist-meta-bar {
        color: $primary;
        text-style: bold;
    }
    #playlist-keys-bar {
        background: $panel;
    }
    #playlist-body-container {
        height: 1fr;
    }
    #tracks-panel {
        width: 60%;
        height: 100%;
        border-right: solid $border;
    }
    #formats-panel {
        width: 40%;
        height: 100%;
    }
    .panel-header, .column-header {
        width: 100%;
        text-align: center;
        background: $surface;
        color: $primary;
        text-style: bold;
        height: 1;
        padding: 0 1;
    }
    #tracks-table {
        height: 1fr;
    }
    .format-column-box {
        height: 1fr;
        border-bottom: solid $border;
    }
    .format-list-view {
        height: 1fr;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_current_track", "Toggle", show=False),
        Binding("ctrl+a", "select_all_tracks", "Select All", show=False),
        Binding("ctrl+d", "deselect_all_tracks", "Deselect All", show=False),
        Binding("i", "invert_tracks_selection", "Invert", show=False),
    ]

    FOCUS_ORDER = ("#tracks-table", "#list-video", "#list-audio")
    _COLUMNS = ("sel", "num", "title", "duration", "size")

    def __init__(self, extraction: ExtractionResult, **kwargs):
        super().__init__(extraction, **kwargs)
        self.entries: List[SearchResultItem] = list(extraction.playlist_entries)
        self.selected_indices: Set[int] = set(range(len(self.entries)))
        known = [e.duration for e in self.entries if e.duration and e.duration > 0]
        self._avg_duration = int(sum(known) / len(known)) if known else DEFAULT_ITEM_DURATION
        self._row_keys: list = []
        self._sizes: List[str] = []

    # ------------------------------------------------------------------ rendering

    def _keys_bar_markup(self) -> str:
        return (
            "[bold]Space[/] Toggle  [bold]^A[/] All  [bold]^D[/] None  [bold]I[/] Invert  "
            "│  [bold]1[/] Best  [bold]2[/] 1080p  [bold]3[/] Small  [bold yellow]4[/] Audio  "
            f"│  {self.container_markup()}  "
            "│  [bold cyan]Enter[/] Download  [bold]A[/] Queue"
        )

    def _stats_bar_markup(self) -> str:
        total_bytes, total_secs = estimate_playlist_size(self._selected_entries(), self.selected_video, self.selected_audio, self.audio_quality)
        return (
            f"Selected: [bold green]{len(self.selected_indices)}[/] of [bold]{len(self.entries)}[/] tracks "
            f"([bold cyan]{format_duration(total_secs)}[/])  │  "
            f"Estimated Total Size: [bold yellow]~{format_bytes(total_bytes)}[/] (Sequential Order Guaranteed)"
        )

    def _item_sizes(self) -> List[str]:
        """Estimated size label per entry (same math as formats.estimate_item_size, bitrate computed once)."""
        bytes_per_sec = estimate_format_bitrates(self.selected_video, self.selected_audio, self.audio_quality)[2] * 125.0
        return [
            f"~{format_bytes(max(1024, int(bytes_per_sec * (e.duration if e.duration and e.duration > 0 else self._avg_duration))))}"
            for e in self.entries
        ]

    def _row(self, i: int) -> tuple:
        item, on = self.entries[i], i in self.selected_indices
        return (
            Text("[✓]", style="bold green") if on else Text("[ ]", style="dim"),
            Text(str(i + 1), style="bold" if on else "dim"),
            Text(rtl_truncate(item.title, self._title_width), style="" if on else "dim"),
            Text(item.duration_str, style="dim"),
            self._size_cell(i),
        )

    def _size_cell(self, i: int) -> Text:
        return Text(self._sizes[i], style="bold cyan" if i in self.selected_indices else "dim")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="playlist-header-container"):
            yield Label(
                f"Playlist: [bold]{markup_safe(self.extraction.title, 55)}[/] │ Channel: [dim]{markup_safe(self.extraction.uploader)}[/] │ "
                f"Total: [dim]{len(self.entries)} videos ({self.extraction.duration_str})[/]",
                id="playlist-meta-bar",
            )
            yield Label(self._stats_bar_markup(), id="playlist-stats-bar")
            yield Label(self._keys_bar_markup(), id="playlist-keys-bar")
        with Horizontal(id="playlist-body-container"):
            with Vertical(id="tracks-panel"):
                yield Label("PLAYLIST TRACKS (Space to Toggle, Enter to Download)", classes="panel-header")
                yield DataTable(id="tracks-table", cursor_type="row")
            with Vertical(id="formats-panel"):
                yield FormatColumnView("VIDEO STREAM", "video", self.extraction.video_formats, self.default_video_idx, classes="format-column-box", id="col-video")
                yield FormatColumnView("AUDIO STREAM", "audio", self.extraction.audio_formats, self.default_audio_idx, classes="format-column-box", id="col-audio")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tracks-table", DataTable)
        panel_width = int(self.size.width * 0.6)  # #tracks-panel is 60% wide; not laid out yet at mount
        self._title_width = max(16, flexible_width(panel_width, (5, 5, 8, 11), column_count=5, extra=1))  # 1: panel border
        for key, width in zip(self._COLUMNS, (5, 5, self._title_width, 8, 11)):
            table.add_column({"sel": "Sel", "num": "#", "title": "Title", "duration": "Duration", "size": "Est. Size"}[key], width=width, key=key)
        self._sizes = self._item_sizes()
        self._row_keys = table.add_rows(self._row(i) for i in range(len(self.entries)))
        table.focus()

    def _update_rows(self, indices: Iterable[int]) -> None:
        table = self.query_one("#tracks-table", DataTable)
        for i in indices:
            for column, value in zip(self._COLUMNS, self._row(i)):
                if column != "duration":
                    table.update_cell(self._row_keys[i], column, value)
        # Fixed-size bars: skip the full layout pass a Label update does by default.
        self.query_one("#playlist-stats-bar", Label).update(self._stats_bar_markup(), layout=False)

    def _refresh_selection_ui(self) -> None:
        sizes = self._item_sizes()
        table = self.query_one("#tracks-table", DataTable)
        for i, size in enumerate(sizes):
            if size != self._sizes[i]:
                self._sizes[i] = size
                table.update_cell(self._row_keys[i], "size", self._size_cell(i))
        self.query_one("#playlist-stats-bar", Label).update(self._stats_bar_markup(), layout=False)
        self.query_one("#playlist-keys-bar", Label).update(self._keys_bar_markup(), layout=False)

    # ------------------------------------------------------------------ track selection

    def _selected_entries(self) -> List[SearchResultItem]:
        return [self.entries[i] for i in sorted(self.selected_indices)]

    def _set_selection(self, new: Set[int]) -> None:
        changed = self.selected_indices ^ new
        self.selected_indices = new
        self._update_rows(changed)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_start_download()

    def action_toggle_current_track(self) -> None:
        row = self.query_one("#tracks-table", DataTable).cursor_row
        if 0 <= row < len(self.entries):
            self._set_selection(self.selected_indices ^ {row})

    def action_select_all_tracks(self) -> None:
        self._set_selection(set(range(len(self.entries))))
        self.notify(f"Selected all {len(self.entries)} tracks.")

    def action_deselect_all_tracks(self) -> None:
        self._set_selection(set())
        self.notify("Deselected all tracks.")

    def action_invert_tracks_selection(self) -> None:
        self._set_selection(set(range(len(self.entries))) - self.selected_indices)
        self.notify(f"Inverted selection: {len(self.selected_indices)} tracks selected.")

    # ------------------------------------------------------------------ queueing

    def _queue(self, switch_to_downloads: bool) -> None:
        if not self.selected_indices:
            self.notify("No tracks selected. Select at least 1 track to download.", severity="warning")
            return
        if not self.selection_is_valid():
            return
        items = self._selected_entries()  # ascending playlist order
        tasks = [self.build_task(item.url, item.title, item.uploader, item.duration_str, item.duration) for item in items]
        self.app.manager.enqueue_many(tasks)
        total_bytes, _ = estimate_playlist_size(items, self.selected_video, self.selected_audio, self.audio_quality)
        self.notify(f"Queued {len(tasks)} playlist tracks (~{format_bytes(total_bytes)}) in playlist order", title="Playlist Queued")
        self.app.navigate("download_screen" if switch_to_downloads else "search_screen")
