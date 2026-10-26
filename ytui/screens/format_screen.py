"""Side-by-side video and audio stream picker for a single video."""

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label

from ..formats import ExtractionResult
from ..rtl_utils import markup_safe
from ..widgets.format_column import FormatColumnView
from .selection import FormatSelectionScreen


class FormatScreen(FormatSelectionScreen):
    """Pick a video stream, an audio stream, a container and a quality, then download."""

    DEFAULT_CSS = """
    FormatScreen {
        background: $background;
    }
    #format-header-container {
        height: auto;
        background: $surface;
    }
    #format-meta-bar {
        height: 1;
        width: 100%;
        text-align: center;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #format-keys-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $panel;
        color: $foreground;
        padding: 0 1;
    }
    #columns-container {
        height: 1fr;
    }
    .format-column {
        width: 1fr;
        height: 100%;
        background: $background;
        border: solid $border;
    }
    .format-column:focus-within {
        border: solid $primary;
    }
    .column-header {
        width: 100%;
        text-align: center;
        background: $surface;
        color: $foreground;
        text-style: bold;
        height: 1;
        padding: 0 1;
    }
    .format-column:focus-within .column-header {
        background: $panel;
        color: $primary;
    }
    .format-list-view {
        height: 1fr;
        background: transparent;
    }
    .format-item-line {
        padding: 0 1;
    }
    """

    def __init__(self, extraction: ExtractionResult, editing_task_id: Optional[str] = None, **kwargs):
        super().__init__(extraction, **kwargs)
        self.editing_task_id = editing_task_id

    def _keys_bar_markup(self) -> str:
        return (
            "[dim]Presets:[/] [bold green]1[/] Best  [bold]2[/] 1080p  [bold]3[/] Small  [bold yellow]4[/] Audio  "
            "│  [bold cyan]Enter / D[/] Download  [bold]A[/] Queue  "
            f"│  {self.container_markup()}  "
            "│  [bold]←/→[/] Navigate"
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="format-header-container"):
            yield Label(
                f"[bold]{markup_safe(self.extraction.title, 65)}[/] | [dim]{markup_safe(self.extraction.uploader)}[/] | [dim]{self.extraction.duration_str}[/]",
                id="format-meta-bar",
            )
            yield Label(self._keys_bar_markup(), id="format-keys-bar")
        with Horizontal(id="columns-container"):
            yield FormatColumnView(
                title="VIDEO STREAM (Left ←)",
                column_type="video",
                options=self.extraction.video_formats,
                default_idx=self.default_video_idx,
                classes="format-column",
                id="col-video",
            )
            yield FormatColumnView(
                title="AUDIO STREAM (Right →)",
                column_type="audio",
                options=self.extraction.audio_formats,
                default_idx=self.default_audio_idx,
                classes="format-column",
                id="col-audio",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#list-video").focus()

    def _refresh_selection_ui(self) -> None:
        self.query_one("#format-keys-bar", Label).update(self._keys_bar_markup(), layout=False)

    def _queue(self, switch_to_downloads: bool) -> None:
        if not self.selection_is_valid():
            return
        manager = self.app.manager
        title = markup_safe(self.extraction.title, 30)

        if self.editing_task_id:
            if manager.requeue_with(self.editing_task_id, **self.selection_fields(self.extraction.duration)):
                self.notify(f"Updated format for '{title}'", title="Format Updated")
            else:
                self.notify("This download is still running. Pause it first, then change its format.", title="Not Updated", severity="warning")
            self.app.navigate("download_screen")
            return

        task = self.build_task(self.extraction.url, self.extraction.title, self.extraction.uploader, self.extraction.duration_str, self.extraction.duration)
        manager.enqueue(task)
        self.notify(f"Queued '{title}' for download", title="Queued")
        self.app.navigate("download_screen" if switch_to_downloads else "search_screen")

    def action_go_back(self) -> None:
        self.app.navigate("download_screen" if self.editing_task_id else "search_screen")
