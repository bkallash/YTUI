"""Compact interactive progress card widget for download queue items with shadcn zinc styling."""

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ListItem, ProgressBar

from manager import DownloadStatus, DownloadTask
from rtl_utils import fix_rtl
from ytdlp_engine import format_bytes


class DownloadTaskCard(ListItem):
    """Custom compact interactive list item displaying a download task with live metrics."""

    def __init__(self, task: DownloadTask, **kwargs):
        super().__init__(**kwargs)
        self.task = task
        self.task_id = task.id

    def compose(self) -> ComposeResult:
        with Vertical(classes="task-card-container"):
            with Horizontal(classes="task-header"):
                yield Label(self._get_status_badge(), classes="task-badge", id=f"badge-{self.task.id}")
                yield Label(f" {fix_rtl(self.task.title)} ({fix_rtl(self.task.uploader)}) - {self.task.video_format}+{self.task.audio_format} [{self.task.container.upper()}]", classes="task-title")

            with Horizontal(classes="task-bar-row"):
                yield ProgressBar(total=100, show_eta=False, id=f"pbar-{self.task.id}", classes="task-pbar")
                yield Label(self._get_stats_line(), classes="task-stats-inline", id=f"stats-{self.task.id}")

    def _get_status_badge(self) -> Text:
        status = self.task.status
        if status == DownloadStatus.QUEUED:
            return Text("[QUEUED]", style="dim")
        elif status == DownloadStatus.DOWNLOADING:
            return Text("[DOWNLOADING]", style="bold cyan")
        elif status == DownloadStatus.MERGING:
            return Text("[MERGING]", style="bold magenta")
        elif status == DownloadStatus.PAUSED:
            return Text("[PAUSED]", style="bold yellow")
        elif status == DownloadStatus.INTERRUPTED:
            return Text("[INTERRUPTED]", style="bold yellow")
        elif status == DownloadStatus.COMPLETED:
            return Text("[COMPLETED]", style="bold green")
        elif status == DownloadStatus.ERROR:
            return Text("[ERROR]", style="bold red")
        elif status == DownloadStatus.CANCELLED:
            return Text("[CANCELLED]", style="dim")
        return Text(f"[{status.value}]", style="dim")

    def _get_stats_line(self) -> str:
        if self.task.status == DownloadStatus.COMPLETED:
            return f"100% ({format_bytes(self.task.total_bytes)}) - Done"
        elif self.task.status == DownloadStatus.INTERRUPTED:
            return "Connection dropped - press 'r' to resume"
        elif self.task.status == DownloadStatus.ERROR:
            return f"Error: {self.task.error_message[:35]}"

        dl = format_bytes(self.task.downloaded_bytes)
        tot = format_bytes(self.task.total_bytes) if self.task.total_bytes > 0 else "--"
        speed = f" | {self.task.speed_str}" if self.task.speed_str and self.task.speed_str != "--" else ""
        eta = f" | ETA {self.task.eta_str}" if self.task.eta_str and self.task.eta_str != "--" else ""
        return f"{self.task.progress_percent:.1f}% ({dl}/{tot}){speed}{eta}"

    def refresh_task_state(self) -> None:
        """Update widget elements dynamically without full rebuild."""
        try:
            pbar = self.query_one(f"#pbar-{self.task.id}", ProgressBar)
            pbar.progress = self.task.progress_percent

            badge = self.query_one(f"#badge-{self.task.id}", Label)
            badge.update(self._get_status_badge())

            stats = self.query_one(f"#stats-{self.task.id}", Label)
            stats.update(self._get_stats_line())
        except Exception:
            pass
