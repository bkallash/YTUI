"""Shared base for screens that pick a video stream, an audio stream, a container and a quality."""

from typing import List, Optional

from textual.binding import Binding
from textual.screen import Screen

from ..formats import (
    AUDIO_CONTAINERS,
    AUDIO_QUALITIES,
    LOSSLESS_CONTAINERS,
    VIDEO_CONTAINERS,
    ExtractionResult,
    FormatOption,
    estimate_stream_sizes,
    extract_audio_container_from_option,
    extract_audio_quality_from_option,
    extract_video_container_from_option,
)
from ..manager import DownloadTask
from ..widgets.format_column import FormatColumnView

BEST_IDX = 1  # index of the "[Best ...] (Auto)" entry in parsed format lists


def default_video_index(formats: List[FormatOption]) -> int:
    """Smallest 1080p option (by size, else bitrate); otherwise Best (index 1) or 0."""
    candidates = [
        (fmt.filesize or fmt.tbr or float("inf"), i)
        for i, fmt in enumerate(formats)
        if fmt.height == 1080 and not fmt.is_special
    ]
    if candidates:
        return min(candidates)[1]
    return BEST_IDX if len(formats) > BEST_IDX else 0


def default_audio_index(formats: List[FormatOption]) -> int:
    return BEST_IDX if len(formats) > BEST_IDX else 0


class FormatSelectionScreen(Screen):
    """Holds the stream/container/quality selection and the keys shared by format pickers.

    Subclasses compose FormatColumnViews with ids col-video / col-audio, set FOCUS_ORDER,
    and implement _refresh_selection_ui() and _queue(switch_to_downloads).
    """

    BINDINGS = [
        Binding("1", "preset('best')", "Best", show=False),
        Binding("2", "preset('1080p')", "1080p", show=False),
        Binding("3", "preset('small')", "Small", show=False),
        Binding("4", "preset('audio')", "Audio", show=False),
        Binding("enter", "start_download", "Download", show=False),
        Binding("d", "start_download", "Download", show=False),
        Binding("a", "add_to_queue", "Queue", show=False),
        Binding("c", "cycle_container", "Container", show=False),
        Binding("q", "cycle_audio_quality", "Quality", show=False),
        # priority: tables would otherwise consume left/right for horizontal scrolling
        Binding("left,h", "focus_step(-1)", "Prev Panel", show=False, priority=True),
        Binding("right,l", "focus_step(1)", "Next Panel", show=False, priority=True),
        Binding("escape", "go_back", "Back", show=True),
    ]

    FOCUS_ORDER: tuple = ("#list-video", "#list-audio")

    def __init__(self, extraction: ExtractionResult, **kwargs):
        super().__init__(**kwargs)
        self.extraction = extraction
        self.default_video_idx = default_video_index(extraction.video_formats)
        self.default_audio_idx = default_audio_index(extraction.audio_formats)
        self.selected_video: FormatOption = (
            extraction.video_formats[self.default_video_idx]
            if extraction.video_formats
            else FormatOption("bestvideo", "video", "Best Video", "Best")
        )
        self.selected_audio: FormatOption = (
            extraction.audio_formats[self.default_audio_idx]
            if extraction.audio_formats
            else FormatOption("bestaudio", "audio", "Best Audio", "Best")
        )
        self.selected_container = "mp4"
        self.audio_quality = "256"
        self._derive_defaults(video_changed=True)

    # ------------------------------------------------------------------ state rules

    @property
    def is_audio_only(self) -> bool:
        return self.selected_video.is_none

    def valid_containers(self) -> List[str]:
        return AUDIO_CONTAINERS if self.is_audio_only else VIDEO_CONTAINERS

    def _derive_defaults(self, video_changed: bool) -> None:
        """Pick container/quality that match the newly selected streams."""
        self.audio_quality = extract_audio_quality_from_option(self.selected_audio)
        if self.is_audio_only:
            self.selected_container = extract_audio_container_from_option(self.selected_audio)
        elif video_changed:
            self.selected_container = extract_video_container_from_option(self.selected_video)
        if self.selected_container not in self.valid_containers():
            self.selected_container = "mkv" if not self.is_audio_only else AUDIO_CONTAINERS[0]

    def container_markup(self) -> str:
        """Toolbar markup for the container (and quality, when exporting audio only)."""
        markup = f"[bold green]C[/] Container: [bold cyan].{self.selected_container.upper()}[/]"
        if self.is_audio_only:
            if self.selected_container in LOSSLESS_CONTAINERS:
                quality = "Lossless"
            else:
                quality = "V0 (VBR)" if self.audio_quality == "V0" else f"{self.audio_quality}k"
            markup += f"  [bold green]Q[/] Quality: [bold cyan]{quality}[/]"
        return markup

    def _refresh_selection_ui(self) -> None:
        raise NotImplementedError

    def _queue(self, switch_to_downloads: bool) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------ events & actions

    def on_format_column_view_selected_changed(self, event: FormatColumnView.SelectedChanged) -> None:
        if event.column_type == "video":
            self.selected_video = event.option
        else:
            self.selected_audio = event.option
        self._derive_defaults(video_changed=event.column_type == "video")
        self._refresh_selection_ui()
        if event.is_double_enter:  # clicking the already-selected format downloads it
            self.action_start_download()

    def action_focus_step(self, step: int) -> None:
        widgets = [w for selector in self.FOCUS_ORDER for w in self.query(selector)]
        if not widgets:
            return
        current = next((i for i, w in enumerate(widgets) if w.has_focus), 0)
        widgets[max(0, min(len(widgets) - 1, current + step))].focus()

    def action_preset(self, name: str) -> None:
        video_count = len(self.extraction.video_formats)
        video_idx = {
            "best": BEST_IDX if video_count > BEST_IDX else None,
            "1080p": self.default_video_idx,
            "small": video_count - 1 if video_count > 2 else None,
            "audio": 0,
        }[name]
        audio_idx = None if name == "small" else self.default_audio_idx
        if video_idx is not None:
            option = self.query_one("#col-video", FormatColumnView).set_selected_index(video_idx)
            self.selected_video = option or self.selected_video
        if audio_idx is not None:
            option = self.query_one("#col-audio", FormatColumnView).set_selected_index(audio_idx)
            self.selected_audio = option or self.selected_audio
        self._derive_defaults(video_changed=True)
        self._refresh_selection_ui()
        labels = {"best": "Best (Auto)", "1080p": "1080p FHD", "small": "Smallest", "audio": f"Audio ({self.selected_container.upper()})"}
        self.notify(f"Preset: {labels[name]} selected. Press Enter to download.", title="Preset Applied")

    def action_cycle_container(self) -> None:
        valid = self.valid_containers()
        idx = valid.index(self.selected_container) if self.selected_container in valid else -1
        self.selected_container = valid[(idx + 1) % len(valid)]
        self._refresh_selection_ui()
        self.notify(f"Output container set to: .{self.selected_container.upper()}", title="Container Changed")

    def action_cycle_audio_quality(self) -> None:
        if self.selected_container in LOSSLESS_CONTAINERS:
            self.notify("FLAC and WAV containers are lossless / uncompressed.", title="Audio Quality")
            return
        if self.audio_quality in AUDIO_QUALITIES:
            self.audio_quality = AUDIO_QUALITIES[(AUDIO_QUALITIES.index(self.audio_quality) + 1) % len(AUDIO_QUALITIES)]
        else:
            self.audio_quality = "192" if self.audio_quality.isdigit() and int(self.audio_quality) < 192 else "256"
        self._refresh_selection_ui()
        desc = "V0 (High Quality VBR)" if self.audio_quality == "V0" else f"{self.audio_quality} kbps"
        self.notify(f"Audio quality set to: {desc}", title="Quality Changed")

    def action_start_download(self) -> None:
        self._queue(switch_to_downloads=True)

    def action_add_to_queue(self) -> None:
        self._queue(switch_to_downloads=False)

    def action_go_back(self) -> None:
        self.app.navigate("search_screen")

    # ------------------------------------------------------------------ task building

    def selection_is_valid(self) -> bool:
        if self.selected_video.is_none and self.selected_audio.is_none:
            self.notify("Select a video or an audio stream (both are set to 'No ...').", title="Nothing to Download", severity="error")
            return False
        return True

    def selection_fields(self, duration: Optional[int]) -> dict:
        """DownloadTask fields describing the current selection."""
        v_size, a_size = estimate_stream_sizes(self.selected_video, self.selected_audio, duration, self.audio_quality)
        return dict(
            video_format=self.selected_video.format_id,
            video_format_label=self.selected_video.label,
            audio_format=self.selected_audio.format_id,
            audio_format_label=self.selected_audio.label,
            audio_quality=self.audio_quality,
            container=self.selected_container,
            video_ext=self.selected_video.ext,
            video_codec=self.selected_video.vcodec,
            audio_ext=self.selected_audio.ext,
            audio_codec=self.selected_audio.acodec,
            video_filesize=v_size,
            audio_filesize=a_size,
            estimated_total_bytes=v_size + a_size,
        )

    def build_task(self, url: str, title: str, uploader: str, duration_str: str, duration: Optional[int]) -> DownloadTask:
        return DownloadTask(url=url, title=title, uploader=uploader, duration_str=duration_str, **self.selection_fields(duration))
