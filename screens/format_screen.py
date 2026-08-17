"""Two-column side-by-side video and audio format selector screen styled with shadcn zinc."""

from typing import List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListView

from config import AppConfig
from manager import DownloadManager, DownloadStatus, DownloadTask
from rtl_utils import fix_rtl, rtl_truncate
from widgets.format_column import FormatColumnView
from ytdlp_engine import (
    ExtractionResult,
    FormatOption,
    YtDlpEngine,
    compatible_audio_containers,
    compatible_video_containers,
    extract_audio_container_from_option,
    extract_audio_quality_from_option,
    extract_video_container_from_option,
)


CONTAINERS = ["mp4", "mkv", "webm", "mp3", "m4a", "flac", "opus", "wav"]
VIDEO_CONTAINERS = ["mp4", "mkv", "webm"]
AUDIO_ONLY_CONTAINERS = ["mp3", "m4a", "flac", "opus", "wav"]
AUDIO_QUALITIES = ["256", "320", "192", "128", "V0"]


class FormatScreen(Screen):
    """Authentic terminal side-by-side video and audio stream selection with shadcn zinc theme."""

    DEFAULT_CSS = """
    FormatScreen {
        background: $background;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    #format-header-container {
        height: auto;
        width: 100%;
        background: $surface;
        padding: 0;
        margin: 0;
    }
    #format-meta-bar {
        height: 1;
        width: 100%;
        text-align: center;
        background: $surface;
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
        width: 100%;
        margin: 0;
        padding: 0;
    }
    .format-column {
        width: 1fr;
        height: 100%;
        background: $background;
        border: solid $border;
        padding: 0;
        margin: 0;
    }
    .format-column:focus-within {
        border: solid $primary;
    }
    .column-header {
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
        width: 100%;
        background: transparent;
    }
    .format-item-line {
        padding: 0 1;
    }
    """

    BINDINGS = [
        # Selected items actions (shown in top action bar, hidden from bottom footer)
        Binding("1", "preset_1", "Best", show=False),
        Binding("2", "preset_2", "1080p", show=False),
        Binding("3", "preset_3", "Small", show=False),
        Binding("4", "preset_4", "Audio", show=False),
        Binding("enter", "start_download", "Download", show=False),
        Binding("d", "start_download", "Download", show=False),
        Binding("a", "add_to_queue", "Queue", show=False),
        Binding("c", "cycle_container", "Container", show=False),
        Binding("q", "cycle_audio_quality", "Quality", show=False),
        Binding("left", "focus_video", "Video", show=False),
        Binding("right", "focus_audio", "Audio", show=False),
        Binding("h", "focus_video", "Video", show=False),
        Binding("l", "focus_audio", "Audio", show=False),

        # Screen / Global navigation bindings (shown in bottom footer for entire screen)
        Binding("escape", "go_back", "Back", show=True),
        Binding("ctrl+s", "app.switch_to_search", "Search", show=True),
        Binding("ctrl+j", "app.switch_to_downloads", "Queue", show=True),
        Binding("ctrl+y", "app.switch_to_history", "History", show=True),
        Binding("ctrl+o", "app.switch_to_settings", "Config", show=True),
        Binding("ctrl+q", "app.quit_app", "Quit", show=True),
    ]

    @staticmethod
    def _find_default_video_idx(formats: List[FormatOption]) -> int:
        """Find the smallest 1080p video format index; fall back to 'Best Video' (idx 1) or 0."""
        candidates = []
        for i, fmt in enumerate(formats):
            if fmt.height == 1080 and not fmt.is_special:
                # Use filesize if available, otherwise tbr as proxy for size
                size_key = fmt.filesize if fmt.filesize else (fmt.tbr or float('inf'))
                candidates.append((size_key, i))
        if candidates:
            # Smallest filesize / lowest bitrate among 1080p options
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        # No 1080p found — fall back to "Best Video (Auto)" at index 1
        return 1 if len(formats) > 1 else 0

    @staticmethod
    def _find_default_audio_idx(formats: List[FormatOption]) -> int:
        """Default to 'Best Audio (Auto)' at index 1."""
        return 1 if len(formats) > 1 else 0

    def __init__(
        self,
        extraction: ExtractionResult,
        config: Optional[AppConfig] = None,
        editing_task_id: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.extraction = extraction
        self.config = config or AppConfig.load()
        self.editing_task_id = editing_task_id
        self._default_video_idx = self._find_default_video_idx(extraction.video_formats)
        self._default_audio_idx = self._find_default_audio_idx(extraction.audio_formats)
        self.selected_video: FormatOption = extraction.video_formats[self._default_video_idx] if extraction.video_formats else FormatOption(format_id="bestvideo", format_type="video", label="Best Video", resolution="Best")
        self.selected_audio: FormatOption = extraction.audio_formats[self._default_audio_idx] if extraction.audio_formats else FormatOption(format_id="bestaudio", format_type="audio", label="Best Audio", resolution="Best")
        if self.selected_video and self.selected_video.format_id == "none":
            self.selected_container = extract_audio_container_from_option(self.selected_audio)
        else:
            self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
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

    def _build_actions_bar_text(self) -> str:
        """Generate markup for the top toolbar featuring selected items actions, container, and audio quality."""
        is_audio_only = (self.selected_video and self.selected_video.format_id == "none")
        if is_audio_only:
            if self.selected_container.lower() in ("flac", "wav"):
                quality_str = "Lossless"
            else:
                quality_str = f"{self.audio_quality}k" if self.audio_quality != "V0" else "V0 (VBR)"
            container_display = f"[bold green]C[/] Container: [bold cyan].{self.selected_container.upper()}[/]  [bold green]Q[/] Quality: [bold cyan]{quality_str}[/]"
        else:
            container_display = f"[bold green]C[/] Container: [bold cyan].{self.selected_container.upper()}[/]"

        return (
            f"[dim]Presets:[/] [bold green]1[/] Best  [bold]2[/] 1080p  [bold]3[/] Small  [bold yellow]4[/] Audio  "
            f"│  [bold cyan]Enter / D[/] Download  [bold]A[/] Queue  "
            f"│  {container_display}  "
            f"│  [bold]←/→[/] Navigate"
        )

    def _update_top_actions_bar(self) -> None:
        try:
            lbl = self.query_one("#format-keys-bar", Label)
            lbl.update(self._build_actions_bar_text())
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="format-header-container"):
            yield Label(
                f"[bold]{rtl_truncate(self.extraction.title, 65)}[/] | [dim]{fix_rtl(self.extraction.uploader)}[/] | [dim]{self.extraction.duration_str}[/]",
                id="format-meta-bar",
            )
            yield Label(
                self._build_actions_bar_text(),
                id="format-keys-bar",
            )

        with Horizontal(id="columns-container"):
            yield FormatColumnView(
                title="VIDEO STREAM (Left ←)",
                column_type="video",
                options=self.extraction.video_formats,
                default_idx=self._default_video_idx,
                classes="format-column",
                id="col-video",
            )
            yield FormatColumnView(
                title="AUDIO STREAM (Right →)",
                column_type="audio",
                options=self.extraction.audio_formats,
                default_idx=self._default_audio_idx,
                classes="format-column",
                id="col-audio",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._update_top_actions_bar()
        self.action_focus_video()

    def action_focus_video(self) -> None:
        try:
            col = self.query_one("#col-video", FormatColumnView)
            list_v = col.query_one("#list-video")
            list_v.focus()
        except Exception:
            pass

    def action_focus_audio(self) -> None:
        try:
            col = self.query_one("#col-audio", FormatColumnView)
            list_a = col.query_one("#list-audio")
            list_a.focus()
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.action_start_download()

    def on_format_column_view_selected_changed(self, event: FormatColumnView.SelectedChanged) -> None:
        if event.column_type == "video":
            self.selected_video = event.option
            if self.selected_video.format_id == "none":
                # Switched to audio-only: auto-switch container and quality to match selected audio
                self.selected_container = extract_audio_container_from_option(self.selected_audio)
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
            else:
                # Video selected: container defaults to selected video format container
                self.selected_container = extract_video_container_from_option(self.selected_video)
        elif event.column_type == "audio":
            self.selected_audio = event.option
            # If in audio-only mode, container and quality update to match the selected audio format
            if self.selected_video and self.selected_video.format_id == "none":
                self.selected_container = extract_audio_container_from_option(self.selected_audio)
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
            else:
                self.audio_quality = extract_audio_quality_from_option(self.selected_audio)

        self._ensure_compatible_container(notify=False)
        self._update_top_actions_bar()

    def _get_valid_containers(self) -> list:
        """Return containers valid for the current format selection."""
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
        self._update_top_actions_bar()
        self.notify(f"Output container set to: .{self.selected_container.upper()}", title="Container Changed", severity="information")

    def action_cycle_audio_quality(self) -> None:
        """Cycle audio bitrate/quality presets (320k, 256k, 192k, 128k, V0 VBR)."""
        if self.selected_container.lower() in ("flac", "wav"):
            self.notify("FLAC and WAV containers are lossless / uncompressed.", title="Audio Quality", severity="information")
            return

        if self.audio_quality in AUDIO_QUALITIES:
            idx = AUDIO_QUALITIES.index(self.audio_quality)
            next_idx = (idx + 1) % len(AUDIO_QUALITIES)
            self.audio_quality = AUDIO_QUALITIES[next_idx]
        else:
            self.audio_quality = "192" if (self.audio_quality.isdigit() and int(self.audio_quality) < 192) else "256"
        self._update_top_actions_bar()
        qual_desc = f"{self.audio_quality} kbps" if self.audio_quality != "V0" else "V0 (High Quality VBR)"
        self.notify(f"Audio quality set to: {qual_desc}", title="Quality Changed", severity="information")

    def action_preset_1(self) -> None:
        """Select Best Video + Audio format options visually."""
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
        self._update_top_actions_bar()
        self.notify("Preset [1]: Best (Auto) selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_2(self) -> None:
        """Select lowest 1080p video + best audio format options visually."""
        col_v = self.query_one("#col-video", FormatColumnView)
        col_a = self.query_one("#col-audio", FormatColumnView)
        best_idx = self._find_default_video_idx(self.extraction.video_formats)
        opt = col_v.set_selected_index(best_idx)
        if opt:
            self.selected_video = opt
        if len(self.extraction.audio_formats) > 1:
            opt_a = col_a.set_selected_index(1)
            if opt_a:
                self.selected_audio = opt_a
        self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._ensure_compatible_container(notify=False)
        self._update_top_actions_bar()
        self.notify("Preset [2]: 1080p FHD selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_3(self) -> None:
        """Select Smallest size format options visually."""
        col_v = self.query_one("#col-video", FormatColumnView)
        if len(self.extraction.video_formats) > 2:
            last_idx = len(self.extraction.video_formats) - 1
            opt = col_v.set_selected_index(last_idx)
            if opt:
                self.selected_video = opt
        self.selected_container = extract_video_container_from_option(self.selected_video)
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        self._ensure_compatible_container(notify=False)
        self._update_top_actions_bar()
        self.notify("Preset [3]: Smallest selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_preset_4(self) -> None:
        """Select Audio Only format options visually."""
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
        self._ensure_compatible_container(notify=False)
        self._update_top_actions_bar()
        qual_str = f"{self.audio_quality}k" if self.audio_quality != "V0" else "V0"
        self.notify(f"Preset [4]: Audio ({self.selected_container.upper()} {qual_str}) selected. Press Enter to Download.", title="Preset Applied", severity="information")

    def action_start_download(self) -> None:
        self._queue_task(switch_to_downloads=True)

    def action_add_to_queue(self) -> None:
        self._queue_task(switch_to_downloads=False)

    def _compute_stream_sizes(self) -> tuple:
        """Compute estimated byte sizes for the selected video and audio streams.

        Uses actual filesize from format metadata when available, otherwise
        falls back to bitrate-based estimation from YtDlpEngine.
        """
        v_fmt = self.selected_video
        a_fmt = self.selected_audio
        duration = self.extraction.raw_info.get("duration") or 0

        v_size = 0
        a_size = 0

        # Video stream size
        if v_fmt and v_fmt.format_id != "none":
            if v_fmt.filesize and v_fmt.filesize > 0:
                v_size = v_fmt.filesize
            elif duration and duration > 0:
                # Estimate from bitrate
                v_kbps, _, _ = YtDlpEngine.estimate_format_bitrates(v_fmt, None, self.audio_quality)
                v_size = int(v_kbps * 125.0 * duration) if v_kbps > 0 else 0

        # Audio stream size
        if a_fmt and a_fmt.format_id != "none":
            if a_fmt.filesize and a_fmt.filesize > 0:
                a_size = a_fmt.filesize
            elif duration and duration > 0:
                _, a_kbps, _ = YtDlpEngine.estimate_format_bitrates(None, a_fmt, self.audio_quality)
                a_size = int(a_kbps * 125.0 * duration) if a_kbps > 0 else 0

        return v_size, a_size

    def _queue_task(self, switch_to_downloads: bool = True) -> None:
        self._ensure_compatible_container(notify=True)
        manager = DownloadManager.get_instance(config=self.config)

        # Compute estimated stream sizes for combined progress tracking
        v_size, a_size = self._compute_stream_sizes()
        estimated_total = v_size + a_size

        if self.editing_task_id:
            task = manager.get_task(self.editing_task_id)
            if task:
                task.video_format = self.selected_video.format_id if self.selected_video else "bestvideo"
                task.video_format_label = self.selected_video.label if self.selected_video else "Best Video"
                task.audio_format = self.selected_audio.format_id if self.selected_audio else "bestaudio"
                task.audio_format_label = self.selected_audio.label if self.selected_audio else "Best Audio"
                task.audio_quality = self.audio_quality
                task.container = self.selected_container
                task.video_ext = self.selected_video.ext if self.selected_video else ""
                task.video_codec = self.selected_video.vcodec if self.selected_video else ""
                task.audio_ext = self.selected_audio.ext if self.selected_audio else ""
                task.audio_codec = self.selected_audio.acodec if self.selected_audio else ""
                task.video_filesize = v_size
                task.audio_filesize = a_size
                task.estimated_total_bytes = estimated_total
                task.is_paused = False
                task.is_cancelled = False
                task.status = DownloadStatus.QUEUED
                task.error_message = ""
                task.add_log(f"Format updated to {task.video_format}+{task.audio_format} ({task.container}). Re-queued.")
                manager._save_tasks()
                manager._notify()
                self.notify(f"Updated format for '{rtl_truncate(task.title, 30)}'", title="Format Updated", severity="information")
                self.app.switch_screen("download_screen")
                return

        task = DownloadTask(
            url=self.extraction.url,
            title=self.extraction.title,
            uploader=self.extraction.uploader,
            duration_str=self.extraction.duration_str,
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
            estimated_total_bytes=estimated_total,
        )
        manager.enqueue(task)
        self.notify(f"Queued '{rtl_truncate(task.title, 30)}' for download", title="Queued", severity="information")

        if switch_to_downloads:
            self.app.switch_screen("download_screen")
        else:
            self.action_go_back()

    def action_go_back(self) -> None:
        if self.editing_task_id:
            self.app.switch_screen("download_screen")
        else:
            self.app.switch_screen("search_screen")
