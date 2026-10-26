"""Download queue screen: live table, task inspector, logs, and queue controls."""

from typing import Dict, Optional

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar, RichLog

from ..formats import format_bytes
from ..history import HistoryManager
from ..manager import MAX_TASK_LOGS, DownloadStatus, DownloadTask
from ..rtl_utils import markup_safe, rtl_truncate
from ..ytdlp_engine import YtDlpEngine
from .common import flexible_width
from .format_screen import FormatScreen

POLL_INTERVAL = 0.25  # seconds between checks of the manager's version counter

# status -> (table text, style, inspector banner markup)
STATUS_DISPLAY: Dict[DownloadStatus, tuple] = {
    DownloadStatus.QUEUED: ("Queued", "dim", "[dim]⏳ Queued in download queue. Waiting for worker slot...[/]"),
    DownloadStatus.DOWNLOADING: ("Downloading", "bold cyan", "[bold cyan]⚡ Downloading:[/] Actively receiving media stream. Press [bold]P[/] to pause."),
    DownloadStatus.MERGING: ("Merging", "bold magenta", "[bold magenta]🔄 Post-Processing:[/] Merging video and audio streams into container..."),
    DownloadStatus.PAUSED: ("Paused", "bold yellow", "[bold yellow]⏸️ Paused:[/] Download suspended. [bold cyan]Press 'R' to resume, 'E' to change format.[/]"),
    DownloadStatus.INTERRUPTED: ("Interrupted", "bold yellow", "[bold yellow]⚠️ Interrupted:[/] Partial download saved from previous session. [bold cyan]Press 'R' to resume from byte offset.[/]"),
    DownloadStatus.COMPLETED: ("Done", "bold green", ""),
    DownloadStatus.ERROR: ("Error", "bold red", ""),
    DownloadStatus.CANCELLED: ("Cancelled", "dim", "[dim]🚫 Download cancelled by user. Press [bold cyan]R[/] to restart or [bold red]D[/] to delete.[/]"),
}

FIXED_WIDTHS = {"num": 4, "status": 12, "prog": 7, "speed": 10, "eta": 8, "size": 9}


class DownloadScreen(Screen):
    """Manage active downloads: pause/resume, inspect, view logs, open results."""

    DEFAULT_CSS = """
    DownloadScreen {
        background: $background;
    }
    #download-header-container {
        height: auto;
        background: $surface;
        border-bottom: solid $border;
    }
    #queue-stats-bar, #queue-keys-bar {
        height: 1;
        width: 100%;
        text-align: center;
        padding: 0 1;
    }
    #queue-stats-bar {
        text-style: bold;
    }
    #queue-keys-bar {
        background: $panel;
    }
    #queue-table {
        height: 1fr;
    }
    #task-inspector-card {
        height: auto;
        min-height: 5;
        max-height: 8;
        background: $surface;
        border-top: solid $border;
        padding: 0 1;
    }
    #inspector-title-line, #inspector-meta-row {
        width: 100%;
        height: 1;
    }
    #inspector-title-line {
        color: $primary;
        text-style: bold;
    }
    #inspector-meta-row, #inspector-status-banner {
        color: $text-muted;
    }
    #inspector-progress-row {
        height: 1;
    }
    #inspector-pbar {
        width: 38;
        margin-right: 1;
    }
    #inspector-stats-label {
        width: 1fr;
        height: 1;
    }
    #log-panel-container {
        height: 9;
        background: $surface;
        border-top: solid $border;
        display: none;
    }
    #log-panel-header {
        height: 1;
        width: 100%;
        background: $panel;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #task-rich-log {
        height: 1fr;
        background: $background;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("p", "pause_selected", "Pause", show=False),
        Binding("r", "resume_selected", "Resume", show=False),
        Binding("e", "edit_format_selected", "Format", show=False),
        Binding("c", "cancel_selected", "Cancel", show=False),
        Binding("d,delete", "delete_selected", "Delete", show=False),
        Binding("l", "toggle_logs", "Logs", show=False),
        Binding("o", "open_file", "Open File", show=False),
        Binding("f", "open_folder", "Folder", show=False),
        Binding("x", "clear_completed", "Clear Done", show=False),
        Binding("escape", "app.switch_to_search", "Back", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_task_id: Optional[str] = None
        self.is_log_visible = False
        self._seen_version = -1
        self._row_cache: Dict[str, tuple] = {}
        self._label_cache: Dict[str, str] = {}
        self._log_task_id: Optional[str] = None
        self._shown_log_total = 0

    @property
    def manager(self):
        return self.app.manager

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="download-header-container"):
            yield Label("QUEUE: Loading downloads...", id="queue-stats-bar")
            yield Label(
                "[bold cyan]P[/] Pause  [bold green]R[/] Resume  [bold cyan]E[/] Format  [bold red]C[/] Cancel  [bold]D[/] Delete  "
                "[bold magenta]L[/] Logs  [bold]O[/] Open  [bold]F[/] Folder  [bold]X[/] Clear Done  [dim]Esc[/] Back",
                id="queue-keys-bar",
            )
        yield DataTable(id="queue-table", cursor_type="row")
        with Vertical(id="task-inspector-card"):
            yield Label("No download selected", id="inspector-title-line")
            yield Label("Select a task from the queue above to inspect live details.", id="inspector-meta-row")
            with Horizontal(id="inspector-progress-row"):
                yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="inspector-pbar")
                yield Label("0.0% (-- / --)", id="inspector-stats-label")
            yield Label("Status: IDLE", id="inspector-status-banner")
        with Vertical(id="log-panel-container"):
            yield Label("Real-Time yt-dlp Output Log (Press 'L' to close)", id="log-panel-header")
            yield RichLog(id="task-rich-log", highlight=True, markup=False, max_lines=MAX_TASK_LOGS)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        widths = self._column_widths()
        for key, label in (("num", "#"), ("status", "Status"), ("title", "Title"), ("format", "Format"), ("prog", "Prog"), ("speed", "Speed"), ("eta", "ETA"), ("size", "Size")):
            table.add_column(label, width=widths[key], key=key)
        self.set_interval(POLL_INTERVAL, self._poll)
        self.refresh_table()

    def on_screen_resume(self) -> None:
        self.refresh_table()

    def _poll(self) -> None:
        if self.manager.version != self._seen_version:
            self.refresh_table()

    def _column_widths(self) -> Dict[str, int]:
        """Fixed columns keep their width; Title and Format share the rest of the terminal."""
        remaining = flexible_width(self.size.width, FIXED_WIDTHS.values(), column_count=8)
        fmt_w = max(10, min(16, remaining // 4))
        return {**FIXED_WIDTHS, "format": fmt_w, "title": max(12, remaining - fmt_w)}

    def on_resize(self, event: Resize) -> None:
        table = self.query_one("#queue-table", DataTable)
        if table.columns:
            for key, width in self._column_widths().items():
                table.columns[key].width = width
            self._row_cache.clear()  # titles are truncated to the column width
            self.refresh_table()

    # ------------------------------------------------------------------ rendering

    @staticmethod
    def _format_short_res(task: DownloadTask) -> str:
        """Compact resolution & container, e.g. '1080p60 (.mp4)'."""
        if task.is_audio_only or "no video" in (task.video_format_label or "").lower():
            return f"Audio (.{task.container.lower()})"
        label = task.video_format_label or task.video_format or "Best"
        if "best" in label.lower():
            res = "Best"
        else:
            parts = label.split()
            fps = next(("".join(c for c in p if c.isdigit()) for p in parts[1:] if "fps" in p.lower()), "")
            res = (parts[0] if parts else label) + fps
            res = res.strip("[](),")
        return f"{res} (.{task.container.lower()})"

    def _row_values(self, task: DownloadTask, title_width: int) -> tuple:
        text, style, _ = STATUS_DISPLAY[task.status]
        size = task.total_bytes or task.downloaded_bytes
        return (
            Text(text, style=style),
            rtl_truncate(task.title, title_width),
            self._format_short_res(task),
            f"{task.progress_percent:.1f}%",
            task.speed_str or "--",
            task.eta_str or "--",
            format_bytes(size) if size > 0 else "--",
        )

    def refresh_table(self) -> None:
        self._seen_version = self.manager.version
        tasks = list(self.manager.tasks)
        counts = {status: 0 for status in DownloadStatus}
        for t in tasks:
            counts[t.status] += 1
        self._set_label(
            "#queue-stats-bar",
            f"QUEUE: [bold $success]{counts[DownloadStatus.DOWNLOADING] + counts[DownloadStatus.MERGING]}[/] active / {self.app.config.max_concurrent_downloads} max | "
            f"[bold]{counts[DownloadStatus.QUEUED]}[/] queued | "
            f"[bold $warning]{counts[DownloadStatus.PAUSED] + counts[DownloadStatus.INTERRUPTED]}[/] paused/interrupted | "
            f"[bold $success]{counts[DownloadStatus.COMPLETED]}[/] done"
            + (f" | [bold $error]{counts[DownloadStatus.ERROR]} error[/]" if counts[DownloadStatus.ERROR] else ""),
        )

        table = self.query_one("#queue-table", DataTable)
        title_width = table.columns["title"].width
        columns = ("status", "title", "format", "prog", "speed", "eta", "size")
        if [str(k.value) for k in table.rows] != [t.id for t in tasks]:
            cursor = table.cursor_row
            table.clear()
            self._row_cache = {t.id: self._row_values(t, title_width) for t in tasks}
            for i, t in enumerate(tasks):
                table.add_row(str(i + 1), *self._row_cache[t.id], key=t.id)
            if tasks:
                table.move_cursor(row=min(max(cursor, 0), len(tasks) - 1))
        else:
            for t in tasks:
                new = self._row_values(t, title_width)
                old = self._row_cache.get(t.id)
                if new != old:
                    self._row_cache[t.id] = new
                    for column, value, previous in zip(columns, new, old or (None,) * len(new)):
                        if value != previous:
                            table.update_cell(t.id, column, value)

        if tasks and not any(t.id == self.selected_task_id for t in tasks):
            self.selected_task_id = tasks[min(max(table.cursor_row, 0), len(tasks) - 1)].id
        self._update_selected_details()

    def _set_label(self, selector: str, markup: str, layout: bool = False) -> None:
        """Update a label only when its text changed. Fixed-size labels skip the layout pass."""
        if self._label_cache.get(selector) != markup:
            self._label_cache[selector] = markup
            self.query_one(selector, Label).update(markup, layout=layout)

    def _update_selected_details(self) -> None:
        task = self.manager.get_task(self.selected_task_id) if self.selected_task_id else None
        if not task:
            return
        self._set_label("#inspector-title-line", f"[bold]{markup_safe(task.title)}[/]  [dim]• {markup_safe(task.uploader)} • {task.duration_str}[/]")
        _, style, banner = STATUS_DISPLAY[task.status]
        self._set_label(
            "#inspector-meta-row",
            f"Video: [bold]{markup_safe(task.video_format_label or task.video_format)}[/] | "
            f"Audio: [bold]{markup_safe(task.audio_format_label or task.audio_format)}[/] | "
            f"Container: [bold green].{task.container.upper()}[/] | Status: [{style}]{task.status.value}[/]",
        )
        self.query_one("#inspector-pbar", ProgressBar).progress = task.progress_percent
        speed = f" | [bold cyan]{task.speed_str}[/]" if task.speed_str not in ("", "--") else ""
        eta = f" | ETA: [bold]{task.eta_str}[/]" if task.eta_str not in ("", "--") else ""
        total = format_bytes(task.total_bytes) if task.total_bytes > 0 else "--"
        self._set_label("#inspector-stats-label", f"[bold green]{task.progress_percent:.1f}%[/] ({format_bytes(task.downloaded_bytes)} / {total}){speed}{eta}")

        if task.status == DownloadStatus.ERROR:
            banner = f"[bold red]❌ Error:[/] {markup_safe((task.error_message or 'Unknown error')[:75])}  [dim](Press [bold cyan]R[/] to retry, [bold cyan]E[/] to change format)[/]"
        elif task.status == DownloadStatus.COMPLETED:
            banner = f"[bold green]✅ Saved:[/] [dim]{markup_safe(task.output_filepath or 'Saved')}[/]  [dim](Press [bold]O[/] to open, [bold]F[/] for folder)[/]"
        self._set_label("#inspector-status-banner", banner, layout=True)  # may wrap to two lines

        if self.is_log_visible:
            self._update_logs(task)

    def _update_logs(self, task: DownloadTask) -> None:
        """Append only lines logged since the last update; rewrite when switching tasks."""
        rich_log = self.query_one("#task-rich-log", RichLog)
        new_count = task.log_total - self._shown_log_total
        if task.id != self._log_task_id or new_count < 0 or new_count > len(task.logs):
            rich_log.clear()
            self._log_task_id = task.id
            lines = list(task.logs)
            if not lines:
                rich_log.write(Text("No log output recorded yet for this task.", style="dim"))
        elif new_count:
            lines = list(task.logs)[-new_count:]
        else:
            return
        for line in lines:
            rich_log.write(line)
        self._shown_log_total = task.log_total

    # ------------------------------------------------------------------ actions

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value != self.selected_task_id:
            self.selected_task_id = str(event.row_key.value)
            self._update_selected_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_open_file()

    def _selected(self) -> Optional[DownloadTask]:
        return self.manager.get_task(self.selected_task_id) if self.selected_task_id else None

    def action_pause_selected(self) -> None:
        if self.selected_task_id and self.manager.pause_task(self.selected_task_id):
            self.notify("Download paused", severity="warning")
        self.refresh_table()

    def action_resume_selected(self) -> None:
        if self.selected_task_id and self.manager.resume_task(self.selected_task_id):
            self.notify("Resuming download with partial byte offset...", title="Resuming")
        self.refresh_table()

    def action_cancel_selected(self) -> None:
        if self.selected_task_id and self.manager.cancel_task(self.selected_task_id):
            self.notify("Download cancelled", severity="error")
        self.refresh_table()

    def action_delete_selected(self) -> None:
        task = self._selected()
        if task:
            self.manager.delete_task(task.id)
            self.notify(f"Removed '{markup_safe(task.title, 25)}' from queue")
            self.refresh_table()

    def action_clear_completed(self) -> None:
        self.manager.clear_completed()
        self.refresh_table()
        self.notify("Cleared finished tasks from queue")

    def action_edit_format_selected(self) -> None:
        task = self._selected()
        if not task:
            return
        if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.MERGING) or self.manager.is_running(task.id):
            self.notify("Pause the download before changing its format.", severity="warning")
            return
        self.notify(f"Fetching formats for '{markup_safe(task.title, 25)}'...")
        self._load_formats_for_edit(task.id, task.url)

    @work(exclusive=True, thread=True, group="edit-format")
    def _load_formats_for_edit(self, task_id: str, url: str) -> None:
        try:
            extraction = YtDlpEngine.extract_info(url, config=self.app.config)
        except Exception as err:
            self.app.call_from_thread(self.notify, f"Could not load formats: {markup_safe(str(err))}", severity="error")
            return
        self.app.call_from_thread(lambda: self.app.push_screen(FormatScreen(extraction, editing_task_id=task_id)))

    def action_toggle_logs(self) -> None:
        self.is_log_visible = not self.is_log_visible
        self.query_one("#log-panel-container").display = self.is_log_visible
        self._log_task_id = None  # force a full redraw for the current task
        self._update_selected_details()

    def action_open_file(self) -> None:
        task = self._selected()
        if not task or not task.output_filepath:
            self.notify("No output file path recorded yet", severity="warning")
        elif HistoryManager.open_file(task.output_filepath):
            self.notify(f"Opening: {markup_safe(task.output_filepath)}")
        else:
            self.notify("File does not exist yet or still downloading", severity="error")

    def action_open_folder(self) -> None:
        task = self._selected()
        target = (task.output_filepath if task else "") or self.app.config.download_dir
        if HistoryManager.open_folder(target):
            self.notify("Opened containing folder")
        else:
            self.notify("Could not open destination folder", severity="error")
