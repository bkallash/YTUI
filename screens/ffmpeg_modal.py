"""Interactive setup modal for downloading and configuring FFmpeg on first launch or missing binary."""

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, Horizontal, Middle, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, ProgressBar, Static

from config import AppConfig
from ffmpeg_utils import (
    download_and_install_ffmpeg,
    ensure_ffmpeg_in_path,
    find_ffmpeg,
    get_ffmpeg_bin_dir,
    is_ffmpeg_available,
)


class FfmpegSetupModal(ModalScreen[bool]):
    """Clean, high-contrast modal dialog to guide users through FFmpeg installation."""

    BINDINGS = [
        Binding("escape", "action_skip", "Skip / Dismiss", show=True),
    ]

    DEFAULT_CSS = """
    FfmpegSetupModal {
        align: center middle;
        background: rgba(0, 0, 0, 0.8);
    }

    #ffmpeg-dialog {
        width: 76;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: solid $border;
        padding: 1 2;
    }

    #ffmpeg-title-bar {
        width: 100%;
        height: auto;
        border-bottom: solid $border;
        padding-bottom: 1;
        margin-bottom: 1;
    }

    #ffmpeg-title {
        text-style: bold;
        color: $primary;
    }

    #ffmpeg-subtitle {
        color: $text-muted;
    }

    #ffmpeg-description {
        width: 100%;
        color: $foreground;
        margin-bottom: 1;
    }

    #ffmpeg-features-box {
        background: $panel;
        border: solid $border;
        padding: 1 2;
        margin-bottom: 1;
    }

    .feature-item {
        color: $foreground;
        margin-bottom: 0;
    }

    #ffmpeg-status-container {
        width: 100%;
        background: $panel;
        border: solid $border;
        padding: 1 2;
        margin-bottom: 1;
    }

    #ffmpeg-status-label {
        color: $warning;
        text-style: bold;
        margin-bottom: 0;
    }

    #ffmpeg-progress {
        width: 100%;
        margin-top: 1;
        display: none;
    }

    #ffmpeg-progress.visible {
        display: block;
    }

    #ffmpeg-checkbox-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        background: transparent;
    }

    #chk-dont-ask {
        background: transparent;
        color: $text-muted;
        border: none;
        padding: 0;
        height: auto;
    }

    #chk-dont-ask:focus {
        background: transparent;
        color: $primary;
        text-style: bold;
    }

    #chk-dont-ask:hover {
        color: $foreground;
    }

    #chk-dont-ask > .toggle--label {
        color: $text-muted;
        background: transparent;
    }

    #chk-dont-ask:hover > .toggle--label {
        color: $foreground;
    }

    #chk-dont-ask:focus > .toggle--label {
        color: $primary;
        text-style: bold;
    }

    #chk-dont-ask > .toggle--button {
        color: $surface;
        background: $boost;
    }

    #chk-dont-ask:focus > .toggle--button {
        color: $background;
        background: $primary;
    }

    #chk-dont-ask.-on > .toggle--button {
        color: $background;
        background: $primary;
    }

    #ffmpeg-actions {
        width: 100%;
        height: auto;
        align-horizontal: right;
    }

    #btn-download-ffmpeg {
        margin-right: 1;
    }
    """


    def __init__(self, is_first_launch: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.is_first_launch = is_first_launch
        self._is_downloading = False

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="ffmpeg-dialog"):
                    with Vertical(id="ffmpeg-title-bar"):
                        yield Label("🎬  FFmpeg Media Engine Setup", id="ffmpeg-title")
                        yield Label("High-Definition Video Muxing & Audio Encoding", id="ffmpeg-subtitle")

                    yield Static(
                        "FFmpeg is essential for high-performance media processing. Without FFmpeg, downloads are limited to basic 720p/360p pre-merged streams.",
                        id="ffmpeg-description",
                    )

                    with Vertical(id="ffmpeg-features-box"):
                        yield Label("• 🚀 Full 1080p, 2K, 4K & 8K Video Stream Multiplexing", classes="feature-item")
                        yield Label("• 🎵 High-Quality Audio Extraction (MP3, FLAC, M4A, WAV)", classes="feature-item")
                        yield Label("• 🏷️ High-Res Cover Art & Subtitle Stream Embedding", classes="feature-item")
                        yield Label("• ✂️ Automatic SponsorBlock Segment Removal & Cutting", classes="feature-item")

                    with Vertical(id="ffmpeg-status-container"):
                        yield Label("⚠️ Status: FFmpeg is currently not detected on your system.", id="ffmpeg-status-label")
                        yield ProgressBar(id="ffmpeg-progress", total=100, show_eta=True)

                    with Horizontal(id="ffmpeg-checkbox-container"):
                        yield Checkbox("Don't show this setup prompt on startup again", value=False, id="chk-dont-ask")

                    with Horizontal(id="ffmpeg-actions"):
                        yield Button("📥 Download & Install Automatically", variant="primary", id="btn-download-ffmpeg")
                        yield Button("⏭️ Skip For Now", variant="default", id="btn-skip-ffmpeg")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-download-ffmpeg":
            self.start_download()
        elif btn_id == "btn-skip-ffmpeg":
            self.action_skip()

    def action_skip(self) -> None:
        if self._is_downloading:
            return
        try:
            chk = self.query_one("#chk-dont-ask", Checkbox)
            if chk.value:
                config = AppConfig.load()
                config.skip_ffmpeg_check = True
                config.save()
        except Exception:
            pass
        self.dismiss(False)

    def start_download(self) -> None:
        if self._is_downloading:
            return
        self._is_downloading = True

        # Update UI states
        try:
            btn_dl = self.query_one("#btn-download-ffmpeg", Button)
            btn_dl.disabled = True
            btn_skip = self.query_one("#btn-skip-ffmpeg", Button)
            btn_skip.disabled = True
            progress_bar = self.query_one("#ffmpeg-progress", ProgressBar)
            progress_bar.add_class("visible")
            progress_bar.update(progress=0)
        except Exception:
            pass

        self._run_ffmpeg_installer()

    @work(exclusive=True, thread=True)
    def _run_ffmpeg_installer(self) -> None:
        def on_progress(downloaded: int, total: int, percent: float, msg: str) -> None:
            self.app.call_from_thread(self._update_progress_ui, percent, msg)

        success, message = download_and_install_ffmpeg(progress_callback=on_progress)

        if success:
            bin_dir = str(get_ffmpeg_bin_dir())
            ensure_ffmpeg_in_path()
            config = AppConfig.load()
            config.ffmpeg_location = bin_dir
            config.skip_ffmpeg_check = False
            config.save()

            self.app.call_from_thread(self._on_install_success, message)
        else:
            self.app.call_from_thread(self._on_install_failure, message)

    def _update_progress_ui(self, percent: float, msg: str) -> None:
        try:
            lbl = self.query_one("#ffmpeg-status-label", Label)
            lbl.update(f"⏳ {msg}")
            lbl.styles.color = "#38bdf8"
            progress_bar = self.query_one("#ffmpeg-progress", ProgressBar)
            progress_bar.update(progress=min(100.0, max(0.0, percent)))
        except Exception:
            pass

    def _on_install_success(self, message: str) -> None:
        try:
            lbl = self.query_one("#ffmpeg-status-label", Label)
            lbl.update("✅ FFmpeg downloaded & installed successfully!")
            lbl.styles.color = "#22c55e"
            progress_bar = self.query_one("#ffmpeg-progress", ProgressBar)
            progress_bar.update(progress=100.0)
        except Exception:
            pass

        self.app.notify("FFmpeg is configured and ready for 4K / MP3 downloads!", title="FFmpeg Ready", severity="information")
        self.set_timer(1.2, lambda: self.dismiss(True))

    def _on_install_failure(self, error_message: str) -> None:
        self._is_downloading = False
        try:
            lbl = self.query_one("#ffmpeg-status-label", Label)
            lbl.update(f"❌ Installation Failed: {error_message[:60]}")
            lbl.styles.color = "#f43f5e"
            btn_dl = self.query_one("#btn-download-ffmpeg", Button)
            btn_dl.disabled = False
            btn_dl.label = "🔄 Retry Download"
            btn_skip = self.query_one("#btn-skip-ffmpeg", Button)
            btn_skip.disabled = False
        except Exception:
            pass
        self.app.notify(f"Could not download FFmpeg: {error_message}", title="Install Failed", severity="error")
