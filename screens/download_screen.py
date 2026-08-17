"""Downloads and queue management screen with live logs, rich task inspector, and key-bindings toolbar."""

from typing import Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar, RichLog

from config import AppConfig
from history import HistoryManager
from manager import DownloadManager, DownloadStatus, DownloadTask
from rtl_utils import fix_rtl, rtl_truncate
from ytdlp_engine import format_bytes



class DownloadScreen(Screen):
    """Screen for managing active downloads, queue, pause/resume, task inspection, and live logs."""

    DEFAULT_CSS = """
    DownloadScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #download-header-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0;
        margin: 0;
        border-bottom: solid $border;
    }
    #queue-stats-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: transparent;
        color: $foreground;
        text-style: bold;
        padding: 0 1;
    }
    #queue-keys-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $panel;
        color: $foreground;
        padding: 0 1;
    }
    #queue-table-container {
        height: 1fr;
        width: 100%;
        background: $background;
        margin: 0;
        padding: 0;
    }
    #queue-table {
        height: 100%;
        width: 100%;
        background: $background;
    }
    #task-inspector-card {
        height: auto;
        width: 100%;
        min-height: 5;
        max-height: 8;
        background: $surface;
        border-top: solid $border;
        padding: 0 1;
        margin: 0;
    }
    #inspector-title-line {
        height: 1;
        width: 100%;
        color: $primary;
        text-style: bold;
    }
    #inspector-meta-row {
        height: 1;
        width: 100%;
        color: $text-muted;
    }
    #inspector-progress-row {
        height: 1;
        width: 100%;
        align: left middle;
        margin-top: 0;
    }
    #inspector-pbar {
        width: 38;
        height: 1;
        margin-right: 1;
    }
    #inspector-stats-label {
        color: $foreground;
        width: 1fr;
    }
    #inspector-status-banner {
        height: 1;
        width: 100%;
        color: $text-muted;
    }
    #log-panel-container {
        height: 9;
        width: 100%;
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
        width: 100%;
        background: $background;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("p", "pause_selected", "Pause", show=False),
        Binding("r", "resume_selected", "Resume", show=False),
        Binding("e", "edit_format_selected", "Format", show=False),
        Binding("c", "cancel_selected", "Cancel", show=False),
        Binding("d", "delete_selected", "Delete", show=False),
        Binding("delete", "delete_selected", "Delete", show=False),
        Binding("l", "toggle_logs", "Logs", show=False),
        Binding("o", "open_file", "Open File", show=False),
        Binding("f", "open_folder", "Folder", show=False),
        Binding("x", "clear_completed", "Clear Done", show=False),
        Binding("escape", "app.switch_to_search", "Back", show=False),
        Binding("ctrl+s", "app.switch_to_search", "Search", show=False),
        Binding("ctrl+j", "refresh_table", "Queue", show=False),
        Binding("ctrl+y", "app.switch_to_history", "History", show=False),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=False),
        Binding("ctrl+q", "app.quit_app", "Quit", show=False),
    ]

    def __init__(self, config: Optional[AppConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or AppConfig.load()
        self.manager = DownloadManager.get_instance(config=self.config)
        self.selected_task_id: Optional[str] = None
        self.cols_initialized = False
        self.col_keys = []
        self.is_log_visible = False
        self._last_tasks_snapshot: str = ""
        self._last_log_count: int = -1
        self._last_log_task_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="download-header-container"):
            yield Label("QUEUE: Loading downloads...", id="queue-stats-bar")
            yield Label(
                "[bold cyan]P[/] Pause  [bold green]R[/] Resume  [bold cyan]E[/] Format  [bold red]C[/] Cancel  [bold]D[/] Delete  [bold magenta]L[/] Logs  [bold]O[/] Open  [bold]F[/] Folder  [bold]X[/] Clear Done  [dim]Esc[/] Back",
                id="queue-keys-bar",
            )

        with Vertical(id="queue-table-container"):
            yield DataTable(id="queue-table", cursor_type="row")

        with Vertical(id="task-inspector-card"):
            yield Label("No download selected", id="inspector-title-line")
            yield Label("Select a task from the queue above to inspect live details.", id="inspector-meta-row")
            with Horizontal(id="inspector-progress-row"):
                yield ProgressBar(total=100, show_eta=False, id="inspector-pbar")
                yield Label("0.0% (-- / --)", id="inspector-stats-label")
            yield Label("Status: IDLE", id="inspector-status-banner")

        with Vertical(id="log-panel-container"):
            yield Label("Real-Time yt-dlp Output Log (Press 'L' to close)", id="log-panel-header")
            yield RichLog(id="task-rich-log", highlight=True, markup=True)

        yield Footer()

    def on_mount(self) -> None:
        self._init_columns()
        self.manager.add_listener(self._on_manager_updated)
        self.set_interval(0.5, self._update_ui_state)
        self.refresh_table()

    def _compute_col_widths(self) -> Dict[str, int]:
        """Compute column widths that span the full terminal width.

        Fixed columns get minimum widths; remaining space goes to Title,
        with Format getting a modest share for readability.
        """
        screen_w = max(60, self.size.width)

        # Fixed-width columns (minimum sensible sizes)
        w_idx = 4       # "#"
        w_status = 12   # "Status"
        w_prog = 7      # "Prog"
        w_speed = 10    # "Speed"
        w_eta = 7       # "ETA"
        w_size = 9      # "Size"

        fixed_total = w_idx + w_status + w_prog + w_speed + w_eta + w_size
        # DataTable adds 1-char padding per column (8 columns) + ~2 for border/scrollbar
        overhead = 10
        remaining = screen_w - fixed_total - overhead

        # Split remaining between Format and Title
        w_format = max(10, min(16, remaining // 4))
        w_title = max(12, remaining - w_format)

        return {
            "idx": w_idx,
            "status": w_status,
            "title": w_title,
            "format": w_format,
            "prog": w_prog,
            "speed": w_speed,
            "eta": w_eta,
            "size": w_size,
        }

    def _init_columns(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        widths = self._compute_col_widths()
        if not self.cols_initialized:
            c0 = table.add_column("#", width=widths["idx"])
            c1 = table.add_column("Status", width=widths["status"])
            c2 = table.add_column("Title", width=widths["title"])
            c3 = table.add_column("Format", width=widths["format"])
            c4 = table.add_column("Prog", width=widths["prog"])
            c5 = table.add_column("Speed", width=widths["speed"])
            c6 = table.add_column("ETA", width=widths["eta"])
            c7 = table.add_column("Size", width=widths["size"])
            self.col_keys = [c0, c1, c2, c3, c4, c5, c6, c7]
            self.cols_initialized = True
        else:
            table.columns[self.col_keys[0]].width = widths["idx"]
            table.columns[self.col_keys[1]].width = widths["status"]
            table.columns[self.col_keys[2]].width = widths["title"]
            table.columns[self.col_keys[3]].width = widths["format"]
            table.columns[self.col_keys[4]].width = widths["prog"]
            table.columns[self.col_keys[5]].width = widths["speed"]
            table.columns[self.col_keys[6]].width = widths["eta"]
            table.columns[self.col_keys[7]].width = widths["size"]
            table.refresh()

    def on_screen_resume(self) -> None:
        self.refresh_table()

    def _on_manager_updated(self) -> None:
        self.app.call_from_thread(self.refresh_table)

    def _update_ui_state(self) -> None:
        # Debounce: build a snapshot of task states and skip if nothing changed
        tasks = self.manager.tasks
        snapshot = "|".join(
            f"{t.id}:{t.status.value}:{t.progress_percent:.0f}:{t.speed_str}:{t.eta_str}"
            for t in tasks
        )
        if snapshot == self._last_tasks_snapshot:
            return
        self._last_tasks_snapshot = snapshot
        self.refresh_table()

    def _format_short_res(self, task: DownloadTask) -> str:
        """Return a compact, human-friendly resolution & container string (e.g. '1080p (.mp4)')."""
        is_audio_only = (
            task.video_format == "none"
            or "no video" in (task.video_format_label or "").lower()
        )
        if is_audio_only:
            return f"Audio (.{task.container.lower()})"

        v_label = task.video_format_label or task.video_format or "Best"
        v_lower = v_label.lower()

        if "best" in v_lower:
            res = "Best"
        elif "none" in v_lower:
            res = "Audio"
        else:
            parts = v_label.split()
            first = parts[0] if parts else v_label
            fps_part = ""
            for p in parts[1:]:
                if "fps" in p.lower():
                    fps_part = "".join(c for c in p if c.isdigit())
                    break
            res = f"{first}{fps_part}" if fps_part and not first.endswith(fps_part) else first
            res = res.strip("[](),")

        return f"{res} (.{task.container.lower()})"

    def on_resize(self, event) -> None:
        self._init_columns()
        self.refresh_table()

    def refresh_table(self) -> None:
        tasks = self.manager.tasks
        active_count = sum(1 for t in tasks if t.status == DownloadStatus.DOWNLOADING)
        queued_count = sum(1 for t in tasks if t.status == DownloadStatus.QUEUED)
        interrupted_count = sum(1 for t in tasks if t.status in [DownloadStatus.INTERRUPTED, DownloadStatus.PAUSED])
        completed_count = sum(1 for t in tasks if t.status == DownloadStatus.COMPLETED)
        error_count = sum(1 for t in tasks if t.status == DownloadStatus.ERROR)

        try:
            lbl_stats = self.query_one("#queue-stats-bar", Label)
            lbl_stats.update(
                f"QUEUE: [bold #22c55e]{active_count}[/] active / {self.config.max_concurrent_downloads} max | "
                f"[bold #fafafa]{queued_count}[/] queued | "
                f"[bold #f59e0b]{interrupted_count}[/] paused/interrupted | "
                f"[bold #22c55e]{completed_count}[/] done"
                + (f" | [bold #ef4444]{error_count} error[/]" if error_count > 0 else "")
            )
        except Exception:
            pass

        try:
            table = self.query_one("#queue-table", DataTable)
            current_row_keys = [str(k.value) for k in table.rows.keys()]
            task_ids = [t.id for t in tasks]
            widths = self._compute_col_widths()
            title_max_len = widths["title"]
            if self.cols_initialized and len(self.col_keys) > 2:
                table.columns[self.col_keys[2]].width = title_max_len

            # Rebuild table rows if tasks were added/removed/reordered
            if current_row_keys != task_ids:
                table.clear()
                for i, task in enumerate(tasks):
                    t_title = rtl_truncate(task.title, max_len=title_max_len)
                    table.add_row(
                        str(i + 1),
                        self._render_status(task.status),
                        t_title,
                        self._format_short_res(task),
                        f"{task.progress_percent:.1f}%",
                        task.speed_str or "--",
                        task.eta_str or "--",
                        format_bytes(task.total_bytes) if task.total_bytes > 0 else (format_bytes(task.downloaded_bytes) if task.downloaded_bytes > 0 else "--"),
                        key=task.id,
                    )
            else:
                # Update cells in place
                for task in tasks:
                    t_title = rtl_truncate(task.title, max_len=title_max_len)
                    table.update_cell(task.id, self.col_keys[1], self._render_status(task.status))
                    table.update_cell(task.id, self.col_keys[2], t_title)
                    table.update_cell(task.id, self.col_keys[3], self._format_short_res(task))
                    table.update_cell(task.id, self.col_keys[4], f"{task.progress_percent:.1f}%")
                    table.update_cell(task.id, self.col_keys[5], task.speed_str or "--")
                    table.update_cell(task.id, self.col_keys[6], task.eta_str or "--")
                    size_str = format_bytes(task.total_bytes) if task.total_bytes > 0 else (format_bytes(task.downloaded_bytes) if task.downloaded_bytes > 0 else "--")
                    table.update_cell(task.id, self.col_keys[7], size_str)

            if not self.selected_task_id and tasks:
                self.selected_task_id = tasks[0].id

            self._update_selected_details()
        except Exception:
            pass

    def _render_status(self, status: DownloadStatus) -> Text:
        if status == DownloadStatus.QUEUED:
            return Text("Queued     ", style="dim")
        elif status == DownloadStatus.DOWNLOADING:
            return Text("Downloading", style="bold cyan")
        elif status == DownloadStatus.MERGING:
            return Text("Merging    ", style="bold magenta")
        elif status == DownloadStatus.PAUSED:
            return Text("Paused     ", style="bold yellow")
        elif status == DownloadStatus.INTERRUPTED:
            return Text("Paused     ", style="bold yellow")
        elif status == DownloadStatus.COMPLETED:
            return Text("Done       ", style="bold green")
        elif status == DownloadStatus.ERROR:
            return Text("Error      ", style="bold red")
        elif status == DownloadStatus.CANCELLED:
            return Text("Cancelled  ", style="dim")
        return Text(f"{status.value.capitalize():11}", style="dim")

    def _update_selected_details(self) -> None:
        if not self.selected_task_id:
            return
        task = self.manager.get_task(self.selected_task_id)
        if not task:
            return

        try:
            # 1. Title line
            lbl_title = self.query_one("#inspector-title-line", Label)
            lbl_title.update(f"[bold]{fix_rtl(task.title)}[/]  [dim]• {fix_rtl(task.uploader)} • {task.duration_str}[/]")

            # 2. Meta row (streams + container + status)
            lbl_meta = self.query_one("#inspector-meta-row", Label)
            status_badge = f"[{self._get_status_color(task.status)}]{task.status.value}[/]"
            v_label = task.video_format_label or task.video_format
            a_label = task.audio_format_label or task.audio_format
            lbl_meta.update(
                f"Video: [bold]{v_label}[/] | "
                f"Audio: [bold]{a_label}[/] | "
                f"Container: [bold green].{task.container.upper()}[/] | "
                f"Status: {status_badge}"
            )

            # 3. Progress bar & stats
            pbar = self.query_one("#inspector-pbar", ProgressBar)
            pbar.progress = task.progress_percent

            lbl_stats = self.query_one("#inspector-stats-label", Label)
            dl = format_bytes(task.downloaded_bytes)
            tot = format_bytes(task.total_bytes) if task.total_bytes > 0 else "--"
            speed = f" | [bold cyan]{task.speed_str}[/]" if task.speed_str and task.speed_str != "--" else ""
            eta = f" | ETA: [bold]{task.eta_str}[/]" if task.eta_str and task.eta_str != "--" else ""
            lbl_stats.update(f"[bold green]{task.progress_percent:.1f}%[/] ({dl} / {tot}){speed}{eta}")

            # 4. Status banner / file path / recovery hints
            lbl_banner = self.query_one("#inspector-status-banner", Label)
            if task.status == DownloadStatus.ERROR:
                err_clean = (task.error_message or "Unknown error").replace("[", "(").replace("]", ")")
                lbl_banner.update(f"[bold red]❌ Error:[/] {err_clean[:75]}  [dim](Press [bold cyan]R[/] to retry, [bold cyan]E[/] to change format)[/]")
            elif task.status == DownloadStatus.INTERRUPTED:
                lbl_banner.update(
                    "[bold yellow]⚠️ Interrupted:[/] Partial download saved from previous session. "
                    "[bold cyan]Press 'R' to resume from byte offset.[/]"
                )
            elif task.status == DownloadStatus.PAUSED:
                lbl_banner.update("[bold yellow]⏸️ Paused:[/] Download suspended. [bold cyan]Press 'R' to resume, 'E' to change format.[/]")
            elif task.status == DownloadStatus.COMPLETED:
                dest = task.output_filepath or "Saved"
                lbl_banner.update(f"[bold green]✅ Saved:[/] [dim]{dest}[/]  [dim](Press [bold]O[/] to open, [bold]F[/] for folder)[/]")
            elif task.status == DownloadStatus.MERGING:
                lbl_banner.update("[bold magenta]🔄 Post-Processing:[/] Merging video and audio streams into container...")
            elif task.status == DownloadStatus.DOWNLOADING:
                lbl_banner.update("[bold cyan]⚡ Downloading:[/] Actively receiving media stream. Press [bold]P[/] to pause.")
            elif task.status == DownloadStatus.QUEUED:
                lbl_banner.update("[dim]⏳ Queued in download queue. Waiting for worker slot...[/]")
            elif task.status == DownloadStatus.CANCELLED:
                lbl_banner.update("[dim]🚫 Download cancelled by user. Press [bold cyan]R[/] to restart or [bold red]D[/] to delete.[/]")

            # 5. Live logs panel
            if self.is_log_visible:
                rich_log = self.query_one("#task-rich-log", RichLog)
                log_count = len(task.logs)
                if log_count != self._last_log_count or self.selected_task_id != self._last_log_task_id:
                    self._last_log_count = log_count
                    self._last_log_task_id = self.selected_task_id
                    rich_log.clear()
                    if task.logs:
                        for line in task.logs:
                            rich_log.write(line)
                    else:
                        rich_log.write("[dim]No log output recorded yet for this task.[/]")
        except Exception:
            pass

    def _get_status_color(self, status: DownloadStatus) -> str:
        if status == DownloadStatus.COMPLETED:
            return "bold green"
        elif status == DownloadStatus.DOWNLOADING:
            return "bold cyan"
        elif status == DownloadStatus.MERGING:
            return "bold magenta"
        elif status == DownloadStatus.PAUSED:
            return "bold yellow"
        elif status == DownloadStatus.INTERRUPTED:
            return "bold yellow"
        elif status == DownloadStatus.ERROR:
            return "bold red"
        return "dim"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key:
            self.selected_task_id = str(event.row_key.value)
            self._update_selected_details()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            self.selected_task_id = str(event.row_key.value)
            self._update_selected_details()

    def action_pause_selected(self) -> None:
        if self.selected_task_id:
            self.manager.pause_task(self.selected_task_id)
            self.notify("Download paused", severity="warning")
            self.refresh_table()

    def action_resume_selected(self) -> None:
        if self.selected_task_id:
            self.manager.resume_task(self.selected_task_id)
            self.notify("Resuming download with partial byte offset...", title="Resuming", severity="information")
            self.refresh_table()

    def action_edit_format_selected(self) -> None:
        if not self.selected_task_id:
            return
        task = self.manager.get_task(self.selected_task_id)
        if not task:
            return

        self.notify(f"Fetching formats for '{rtl_truncate(task.title, 25)}'...", severity="information")

        def extract_worker():
            try:
                from ytdlp_engine import YtDlpEngine
                extraction = YtDlpEngine.extract_info(task.url, config=self.config)
                def on_done():
                    from screens.format_screen import FormatScreen
                    self.app.push_screen(FormatScreen(extraction, config=self.config, editing_task_id=task.id))
                self.app.call_from_thread(on_done)
            except Exception as err:
                self.app.call_from_thread(lambda: self.notify(f"Could not load formats: {err}", severity="error"))

        import threading
        threading.Thread(target=extract_worker, daemon=True).start()

    def action_cancel_selected(self) -> None:
        if self.selected_task_id:
            self.manager.cancel_task(self.selected_task_id)
            self.notify("Download cancelled", severity="error")
            self.refresh_table()

    def action_delete_selected(self) -> None:
        if self.selected_task_id:
            task = self.manager.get_task(self.selected_task_id)
            title = rtl_truncate(task.title, 25) if task else "task"
            self.manager.delete_task(self.selected_task_id)
            self.selected_task_id = self.manager.tasks[0].id if self.manager.tasks else None
            self.notify(f"Removed '{title}' from queue", severity="information")
            self.refresh_table()

    def action_clear_completed(self) -> None:
        self.manager.clear_completed()
        self.selected_task_id = self.manager.tasks[0].id if self.manager.tasks else None
        self.refresh_table()
        self.notify("Cleared finished tasks from queue", severity="information")

    def action_toggle_logs(self) -> None:
        self.is_log_visible = not self.is_log_visible
        log_panel = self.query_one("#log-panel-container", Vertical)
        log_panel.display = self.is_log_visible
        # Reset tracking so logs update immediately upon toggle
        self._last_log_count = -1
        self._last_log_task_id = None
        self._update_selected_details()

    def action_open_file(self) -> None:
        if self.selected_task_id:
            task = self.manager.get_task(self.selected_task_id)
            if task and task.output_filepath:
                success = HistoryManager.open_file(task.output_filepath)
                if success:
                    self.notify(f"Opening: {task.output_filepath}")
                else:
                    self.notify("File does not exist yet or still downloading", severity="error")
            else:
                self.notify("No output file path recorded yet", severity="warning")

    def action_open_folder(self) -> None:
        target = None
        if self.selected_task_id:
            task = self.manager.get_task(self.selected_task_id)
            if task and task.output_filepath:
                target = task.output_filepath
        if not target:
            cfg = getattr(self.manager, "config", None) or getattr(self.app, "config", None) or self.config
            target = getattr(cfg, "download_dir", None) or self.config.download_dir

        success = HistoryManager.open_folder(target)
        if success:
            self.notify("Opened containing folder in Explorer", severity="information")
        else:
            self.notify("Could not open destination folder", severity="error")

    def action_refresh_table(self) -> None:
        self.refresh_table()

