"""Interactive playlist configuration screen with track picker, format selectors, and dynamic size estimation."""

from typing import List, Optional, Set, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Label, ListView

from config import AppConfig
from manager import DownloadManager, DownloadTask
from rtl_utils import fix_rtl, rtl_truncate
from widgets.format_column import FormatColumnView
from ytdlp_engine import (
    ExtractionResult,
    FormatOption,
    SearchResultItem,
    YtDlpEngine,
    compatible_audio_containers,
    compatible_video_containers,
    extract_audio_container_from_option,
    extract_audio_quality_from_option,
    extract_video_container_from_option,
    format_bytes,
    format_duration,
)

CONTAINERS = ["mp4", "mkv", "webm", "mp3", "m4a", "flac", "opus", "wav"]
VIDEO_CONTAINERS = ["mp4", "mkv", "webm"]
AUDIO_ONLY_CONTAINERS = ["mp3", "m4a", "flac", "opus", "wav"]
AUDIO_QUALITIES = ["256", "320", "192", "128", "V0"]


def truncate_str(s: str, max_len: int = 40) -> str:
    """Truncate string with ellipsis if longer than max_len and format RTL correctly."""
    return rtl_truncate(s, max_len=max_len)



class PlaylistScreen(Screen):
    """Full-featured playlist download configurator with track selection and live size estimation."""

    DEFAULT_CSS = """
    PlaylistScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #playlist-header-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0;
        margin: 0;
        border-bottom: solid $border;
    }
    #playlist-meta-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $surface;
        color: $primary;
        text-style: bold;
        padding: 0 1;
    }
    #playlist-stats-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $surface;
        color: $foreground;
        padding: 0 1;
    }
    #playlist-keys-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $panel;
        color: $foreground;
        padding: 0 1;
    }
    #playlist-body-container {
        height: 1fr;
        width: 100%;
        margin: 0;
        padding: 0;
    }
    #tracks-panel {
        width: 60%;
        height: 100%;
        background: $background;
        border-right: solid $border;
        margin: 0;
        padding: 0;
    }
    #formats-panel {
        width: 40%;
        height: 100%;
        background: $background;
        margin: 0;
        padding: 0;
    }
    .panel-header {
        text-align: center;
        background: $surface;
        color: $primary;
        text-style: bold;
        height: 1;
        padding: 0 1;
        border-bottom: solid $border;
    }
    #tracks-table {
        height: 1fr;
        width: 100%;
        background: $background;
    }
    .format-column-box {
        height: 1fr;
        width: 100%;
        border-bottom: solid $border;
    }
    """

    BINDINGS = [
        # Screen Actions (hidden from bottom footer, highlighted in top action bar)
        Binding("space", "toggle_current_track", "Toggle", show=False),
        Binding("ctrl+a", "select_all_tracks", "Select All", show=False),
        Binding("ctrl+d", "deselect_all_tracks", "Deselect All", show=False),
        Binding("i", "invert_tracks_selection", "Invert", show=False),
        Binding("1", "preset_1", "Best", show=False),
        Binding("2", "preset_2", "1080p", show=False),
        Binding("3", "preset_3", "Small", show=False),
        Binding("4", "preset_4", "Audio", show=False),
        Binding("enter", "start_download", "Download", show=False),
        Binding("d", "start_download", "Download", show=False),
        Binding("a", "add_to_queue", "Queue", show=False),
        Binding("c", "cycle_container", "Container", show=False),
        Binding("q", "cycle_audio_quality", "Quality", show=False),
        Binding("left", "focus_tracks", "Tracks", show=False),
        Binding("right", "focus_video", "Formats", show=False),
        Binding("h", "focus_tracks", "Tracks", show=False),
        Binding("l", "focus_video", "Formats", show=False),

        # Global navigation bindings (shown in bottom footer)
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+s", "app.switch_to_search", "Search", show=True),
        Binding("ctrl+j", "app.switch_to_downloads", "Queue", show=True),
        Binding("ctrl+y", "app.switch_to_history", "History", show=True),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=True),
        Binding("ctrl+q", "app.quit_app", "Quit", show=True),
    ]

    @staticmethod
    def _find_default_video_idx(formats: List[FormatOption]) -> int:
        """Find index for 1080p or fall back to Best Video (index 1) or 0."""
        for i, fmt in enumerate(formats):
            if fmt.height == 1080 and not fmt.is_special:
                return i
        return 1 if len(formats) > 1 else 0

    @staticmethod
    def _find_default_audio_idx(formats: List[FormatOption]) -> int:
        """Default to Best Audio at index 1."""
        return 1 if len(formats) > 1 else 0

    def __init__(self, extraction: ExtractionResult, config: Optional[AppConfig] = None, **kwargs):
        super().__init__(**kwargs)
        self.extraction = extraction
        self.config = config or AppConfig.load()
        self.entries: List[SearchResultItem] = list(extraction.playlist_entries)

        # Track selection state: all selected by default (storing 0-indexed positions)
        self.selected_indices: Set[int] = set(range(len(self.entries)))

        self._default_video_idx = self._find_default_video_idx(extraction.video_formats)
        self._default_audio_idx = self._find_default_audio_idx(extraction.audio_formats)

        self.selected_video: FormatOption = (
            extraction.video_formats[self._default_video_idx]
            if extraction.video_formats
            else FormatOption(format_id="bestvideo", format_type="video", label="Best Video", resolution="Best")
        )
        self.selected_audio: FormatOption = (
            extraction.audio_formats[self._default_audio_idx]
            if extraction.audio_formats
            else FormatOption(format_id="bestaudio", format_type="audio", label="Best Audio", resolution="Best")
        )

        if self.selected_video and self.selected_video.format_id == "none":
            self.selected_container = extract_audio_container_from_option(self.selected_audio)
        else:
            self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self.cols_initialized = False
        self._ensure_compatible_container()

    def _ensure_compatible_container(self, notify: bool = False) -> bool:
        """Keep the container valid for audio-only versus video output."""
        valid = self._get_valid_containers()
        if self.selected_container not in valid:
            self.selected_container = "mkv" if "mkv" in valid else valid[0]
            if notify:
                self.notify(
                    f"That container is not valid for this media type. Using {self.selected_container.upper()} instead.",
                    title="Container Adjusted",
                    severity="warning",
                )
            return True
        return False

    def _build_keys_bar_text(self) -> str:
        is_audio_only = self.selected_video and self.selected_video.format_id == "none"
        if is_audio_only:
            if self.selected_container.lower() in ("flac", "wav"):
                qual_str = "Lossless"
            else:
                qual_str = f"{self.audio_quality}k" if self.audio_quality != "V0" else "V0"
            container_display = f"[bold green]C[/] Container: [bold cyan].{self.selected_container.upper()}[/]  [bold green]Q[/] Quality: [bold cyan]{qual_str}[/]"
        else:
            container_display = f"[bold green]C[/] Container: [bold cyan].{self.selected_container.upper()}[/]"

        return (
            f"[dim]Select:[/] [bold]Space[/] Toggle  [bold]Ctrl+A[/] All  [bold]Ctrl+D[/] None  [bold]I[/] Invert  "
            f"│  [dim]Presets:[/] [bold]1[/] Best  [bold]2[/] 1080p  [bold]3[/] Small  [bold yellow]4[/] Audio  "
            f"│  {container_display}  "
            f"│  [bold cyan]Enter / D[/] Download  [bold]A[/] Queue"
        )

    def _build_stats_bar_text(self) -> str:
        selected_items = [self.entries[i] for i in sorted(self.selected_indices)]
        total_bytes, total_secs = YtDlpEngine.estimate_playlist_size(
            selected_items,
            self.selected_video,
            self.selected_audio,
            audio_quality=self.audio_quality,
        )

        count_str = f"[bold green]{len(self.selected_indices)}[/] of [bold]{len(self.entries)}[/] tracks"
        dur_str = f"[bold cyan]{format_duration(total_secs)}[/]"
        size_str = f"[bold yellow]~{format_bytes(total_bytes)}[/]"

        return f"Selected: {count_str} ({dur_str})  │  Estimated Total Size: {size_str} (Sequential Order Guaranteed)"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="playlist-header-container"):
            yield Label(
                f"Playlist: [bold]{truncate_str(self.extraction.title, 55)}[/] │ Channel: [dim]{fix_rtl(self.extraction.uploader)}[/] │ Total: [dim]{len(self.entries)} videos ({self.extraction.duration_str})[/]",
                id="playlist-meta-bar",
            )
            yield Label(self._build_stats_bar_text(), id="playlist-stats-bar")
            yield Label(self._build_keys_bar_text(), id="playlist-keys-bar")

        with Horizontal(id="playlist-body-container"):
            with Vertical(id="tracks-panel"):
                yield Label("PLAYLIST TRACKS (Space to Toggle, Enter to Download)", classes="panel-header")
                yield DataTable(id="tracks-table", cursor_type="row")

            with Vertical(id="formats-panel"):
                yield FormatColumnView(
                    title="VIDEO STREAM (Left ←)",
                    column_type="video",
                    options=self.extraction.video_formats,
                    default_idx=self._default_video_idx,
                    classes="format-column-box",
                    id="col-video",
                )
                yield FormatColumnView(
                    title="AUDIO STREAM (Right →)",
                    column_type="audio",
                    options=self.extraction.audio_formats,
                    default_idx=self._default_audio_idx,
                    classes="format-column-box",
                    id="col-audio",
                )

        yield Footer()

    def on_mount(self) -> None:
        self._init_tracks_table()
        self._refresh_tracks_table()
        self.action_focus_tracks()

    def action_focus_tracks(self) -> None:
        try:
            self.query_one("#tracks-table", DataTable).focus()
        except Exception:
            pass

    def action_focus_video(self) -> None:
        try:
            col = self.query_one("#col-video", FormatColumnView)
            col.query_one("#list-video").focus()
        except Exception:
            pass

    def action_focus_audio(self) -> None:
        try:
            col = self.query_one("#col-audio", FormatColumnView)
            col.query_one("#list-audio").focus()
        except Exception:
            pass

    def _init_tracks_table(self) -> None:
        table = self.query_one("#tracks-table", DataTable)
        if not self.cols_initialized:
            table.add_column("Sel", width=5)
            table.add_column("#", width=4)
            table.add_column("Title", width=36)
            table.add_column("Duration", width=8)
            table.add_column("Est. Size", width=11)
            self.cols_initialized = True

    def _refresh_tracks_table(self) -> None:
        table = self.query_one("#tracks-table", DataTable)
        table.clear()

        screen_w = max(70, self.size.width)
        # Allocate title width dynamically based on panel size (approx 60% of screen)
        panel_w = int(screen_w * 0.60)
        title_w = max(20, panel_w - 32)

        for i, item in enumerate(self.entries):
            is_selected = i in self.selected_indices
            check_text = Text("[✓]", style="bold green") if is_selected else Text("[ ]", style="dim")
            num_text = Text(str(i + 1), style="bold" if is_selected else "dim")
            title_text = Text(truncate_str(item.title, max_len=title_w), style="none" if is_selected else "dim")
            dur_text = Text(item.duration_str, style="dim")

            item_bytes = YtDlpEngine.estimate_item_size(
                item.duration,
                self.selected_video,
                self.selected_audio,
                audio_quality=self.audio_quality,
            )
            size_style = "bold cyan" if is_selected else "dim"
            size_text = Text(f"~{format_bytes(item_bytes)}", style=size_style)

            table.add_row(
                check_text,
                num_text,
                title_text,
                dur_text,
                size_text,
                key=str(i),
            )

        self._update_headers()

    def _update_headers(self) -> None:
        try:
            lbl_stats = self.query_one("#playlist-stats-bar", Label)
            lbl_stats.update(self._build_stats_bar_text())
            lbl_keys = self.query_one("#playlist-keys-bar", Label)
            lbl_keys.update(self._build_keys_bar_text())
        except Exception:
            pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_start_download()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        self.action_start_download()

    def action_toggle_current_track(self) -> None:
        table = self.query_one("#tracks-table", DataTable)
        if table.row_count == 0:
            return
        row_idx = table.cursor_row
        if 0 <= row_idx < len(self.entries):
            if row_idx in self.selected_indices:
                self.selected_indices.remove(row_idx)
            else:
                self.selected_indices.add(row_idx)
            self._refresh_tracks_table()
            try:
                table.cursor_coordinate = (row_idx, 0)
            except Exception:
                pass

    def action_select_all_tracks(self) -> None:
        self.selected_indices = set(range(len(self.entries)))
        self._refresh_tracks_table()
        self.notify(f"Selected all {len(self.entries)} tracks.", severity="information")

    def action_deselect_all_tracks(self) -> None:
        self.selected_indices = set()
        self._refresh_tracks_table()
        self.notify("Deselected all tracks.", severity="information")

    def action_invert_tracks_selection(self) -> None:
        all_set = set(range(len(self.entries)))
        self.selected_indices = all_set - self.selected_indices
        self._refresh_tracks_table()
        self.notify(f"Inverted selection: {len(self.selected_indices)} tracks selected.", severity="information")

    def on_format_column_view_selected_changed(self, event: FormatColumnView.SelectedChanged) -> None:
        if event.column_type == "video":
            self.selected_video = event.option
            if self.selected_video.format_id == "none":
                self.selected_container = extract_audio_container_from_option(self.selected_audio)
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
            else:
                self.selected_container = extract_video_container_from_option(self.selected_video)
        elif event.column_type == "audio":
            self.selected_audio = event.option
            if self.selected_video and self.selected_video.format_id == "none":
                self.selected_container = extract_audio_container_from_option(self.selected_audio)
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
            else:
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)

        self._ensure_compatible_container(notify=False)
        self._refresh_tracks_table()

    def _get_valid_containers(self) -> list:
        is_audio_only = self.selected_video and self.selected_video.format_id == "none"
        if is_audio_only:
            return compatible_audio_containers(self.config)
        return compatible_video_containers(self.config, self.selected_video, self.selected_audio)

    def action_cycle_container(self) -> None:
        valid = self._get_valid_containers()
        if self.selected_container in valid:
            idx = valid.index(self.selected_container)
            next_idx = (idx + 1) % len(valid)
        else:
            next_idx = 0
        self.selected_container = valid[next_idx]
        self._update_headers()
        self.notify(f"Output container set to: .{self.selected_container.upper()}", title="Container Changed", severity="information")

    def action_cycle_audio_quality(self) -> None:
        if self.selected_container.lower() in ("flac", "wav"):
            self.notify("FLAC and WAV containers are lossless / uncompressed.", title="Audio Quality", severity="information")
            return

        if self.audio_quality in AUDIO_QUALITIES:
            idx = AUDIO_QUALITIES.index(self.audio_quality)
            next_idx = (idx + 1) % len(AUDIO_QUALITIES)
            self.audio_quality = AUDIO_QUALITIES[next_idx]
        else:
            self.audio_quality = "192" if (self.audio_quality.isdigit() and int(self.audio_quality) < 192) else "256"
        self._refresh_tracks_table()
        qual_desc = f"{self.audio_quality} kbps" if self.audio_quality != "V0" else "V0 (High Quality VBR)"
        self.notify(f"Audio quality set to: {qual_desc}", title="Quality Changed", severity="information")

    def action_preset_1(self) -> None:
        """Select Best Video + Audio presets."""
        col_v = self.query_one("#col-video", FormatColumnView)
        col_a = self.query_one("#col-audio", FormatColumnView)
        if len(self.extraction.video_formats) > 1:
            opt = col_v.set_selected_index(1)
            if opt:
                self.selected_video = opt
        if len(self.extraction.audio_formats) > 1:
            opt = col_a.set_selected_index(1)
            if opt:
                self.selected_audio = opt
        self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._ensure_compatible_container(notify=False)
        self._refresh_tracks_table()
        self.notify("Preset [1]: Best (Auto) selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_2(self) -> None:
        """Select 1080p FHD + Best Audio presets."""
        col_v = self.query_one("#col-video", FormatColumnView)
        col_a = self.query_one("#col-audio", FormatColumnView)
        idx = self._find_default_video_idx(self.extraction.video_formats)
        opt = col_v.set_selected_index(idx)
        if opt:
            self.selected_video = opt
        if len(self.extraction.audio_formats) > 1:
            opt_a = col_a.set_selected_index(1)
            if opt_a:
                self.selected_audio = opt_a
        self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._ensure_compatible_container(notify=False)
        self._refresh_tracks_table()
        self.notify("Preset [2]: 1080p FHD selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_3(self) -> None:
        """Select Smallest size format presets."""
        col_v = self.query_one("#col-video", FormatColumnView)
        if len(self.extraction.video_formats) > 2:
            last_idx = len(self.extraction.video_formats) - 1
            opt = col_v.set_selected_index(last_idx)
            if opt:
                self.selected_video = opt
        self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._refresh_tracks_table()
        self.notify("Preset [3]: Smallest format selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_4(self) -> None:
        """Select Audio Only presets."""
        col_v = self.query_one("#col-video", FormatColumnView)
        col_a = self.query_one("#col-audio", FormatColumnView)
        opt_v = col_v.set_selected_index(0)
        if opt_v:
            self.selected_video = opt_v
        if len(self.extraction.audio_formats) > 1:
            opt_a = col_a.set_selected_index(1)
            if opt_a:
                self.selected_audio = opt_a
        self.selected_container = extract_audio_container_from_option(self.selected_audio)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._refresh_tracks_table()
        qual_str = f"{self.audio_quality}k" if self.audio_quality != "V0" else "V0"
        self.notify(f"Preset [4]: Audio ({self.selected_container.upper()} {qual_str}) selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_start_download(self) -> None:
        self._queue_selected_tasks(switch_to_downloads=True)

    def action_add_to_queue(self) -> None:
        self._queue_selected_tasks(switch_to_downloads=False)

    def _queue_selected_tasks(self, switch_to_downloads: bool = True) -> None:
        if not self.selected_indices:
            self.notify("No tracks selected. Select at least 1 track to download.", severity="warning")
            return

        self._ensure_compatible_container(notify=True)

        manager = DownloadManager.get_instance(config=self.config)

        # STRICT SEQUENTIAL ORDER GUARANTEE: sort indices from 0 to N-1
        sorted_indices = sorted(self.selected_indices)
        tasks_to_queue: List[DownloadTask] = []

        for idx in sorted_indices:
            item = self.entries[idx]
            # Compute estimated stream sizes for combined progress tracking
            item_duration = item.duration or 0
            v_size = 0
            a_size = 0
            v_fmt = self.selected_video
            a_fmt = self.selected_audio
            if v_fmt and v_fmt.format_id != "none":
                if v_fmt.filesize and v_fmt.filesize > 0:
                    v_size = v_fmt.filesize
                elif item_duration > 0:
                    v_kbps, _, _ = YtDlpEngine.estimate_format_bitrates(v_fmt, None, self.audio_quality)
                    v_size = int(v_kbps * 125.0 * item_duration) if v_kbps > 0 else 0
            if a_fmt and a_fmt.format_id != "none":
                if a_fmt.filesize and a_fmt.filesize > 0:
                    a_size = a_fmt.filesize
                elif item_duration > 0:
                    _, a_kbps, _ = YtDlpEngine.estimate_format_bitrates(None, a_fmt, self.audio_quality)
                    a_size = int(a_kbps * 125.0 * item_duration) if a_kbps > 0 else 0

            task = DownloadTask(
                url=item.url,
                title=item.title,
                uploader=item.uploader,
                duration_str=item.duration_str,
                video_format=self.selected_video.format_id if self.selected_video else "bestvideo",
                video_format_label=self.selected_video.label if self.selected_video else "Best Video",
                audio_format=self.selected_audio.format_id if self.selected_audio else "bestaudio",
                audio_format_label=self.selected_audio.label if self.selected_audio else "Best Audio",
                audio_quality=self.audio_quality,
                container=self.selected_container,
                video_ext=self.selected_video.ext if self.selected_video else "",
                video_codec=self.selected_video.vcodec if self.selected_video else "",
                audio_ext=self.selected_audio.ext if self.selected_audio else "",
                audio_codec=self.selected_audio.acodec if self.selected_audio else "",
                video_filesize=v_size,
                audio_filesize=a_size,
                estimated_total_bytes=v_size + a_size,
            )
            tasks_to_queue.append(task)

        manager.enqueue_many(tasks_to_queue)

        total_bytes, _ = YtDlpEngine.estimate_playlist_size(
            [self.entries[i] for i in sorted_indices],
            self.selected_video,
            self.selected_audio,
            audio_quality=self.audio_quality,
        )

        self.notify(
            f"Queued {len(tasks_to_queue)} playlist tracks (~{format_bytes(total_bytes)}) in strict sequential order",
            title="Playlist Queued",
            severity="information",
        )

        if switch_to_downloads:
            self.app.switch_screen("download_screen")
        else:
            self.action_go_back()

    def action_go_back(self) -> None:
        self.app.switch_screen("search_screen")
