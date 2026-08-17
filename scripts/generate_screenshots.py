"""Script to programmatically generate crisp SVG screenshots for README documentation."""

import asyncio
from pathlib import Path
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import AppConfig
from history import HistoryManager
from manager import DownloadManager, DownloadStatus, DownloadTask
from screens.download_screen import DownloadScreen
from screens.format_screen import FormatScreen
from screens.settings_screen import SettingsScreen
from textual.app import App
from ytdlp_engine import ExtractionResult, FormatOption


class ScreenshotApp(App):
    """Container app to host individual screens for screenshot capture."""

    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen {
        background: $background;
        color: $foreground;
        layout: vertical;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, target_screen, **kwargs):
        super().__init__(**kwargs)
        self.target_screen = target_screen

    def on_mount(self) -> None:
        from themes import register_all_themes
        register_all_themes(self)
        self.theme = "shadcn-zinc"
        self.push_screen(self.target_screen)


def create_demo_extraction() -> ExtractionResult:
    """Create realistic extraction data for format matrix screenshot."""
    video_formats = [
        FormatOption(
            format_id="bestvideo",
            format_type="video",
            label="⭐ Best Video (Auto)",
            resolution="Best Available",
            note="Selects the highest quality stream automatically",
            is_special=True,
        ),
        FormatOption(
            format_id="313",
            format_type="video",
            label="2160p 4K UHD",
            resolution="3840x2160 (60fps)",
            ext="webm",
            vcodec="vp9",
            fps=60,
            height=2160,
            tbr=18500.0,
            filesize=1450 * 1024 * 1024,
            filesize_str="1.45 GB",
            note="VP9 / 60fps • Ultra High Definition",
        ),
        FormatOption(
            format_id="271",
            format_type="video",
            label="1440p 2K QHD",
            resolution="2560x1440 (60fps)",
            ext="webm",
            vcodec="vp9",
            fps=60,
            height=1440,
            tbr=9200.0,
            filesize=720 * 1024 * 1024,
            filesize_str="720 MB",
            note="VP9 / 60fps • Quad High Definition",
        ),
        FormatOption(
            format_id="137",
            format_type="video",
            label="1080p FHD",
            resolution="1920x1080 (60fps)",
            ext="mp4",
            vcodec="avc1.64002a",
            fps=60,
            height=1080,
            tbr=4800.0,
            filesize=380 * 1024 * 1024,
            filesize_str="380 MB",
            note="H.264 / 60fps • Crisp Full HD standard",
        ),
        FormatOption(
            format_id="22",
            format_type="video",
            label="720p HD",
            resolution="1280x720 (30fps)",
            ext="mp4",
            vcodec="avc1.4d401f",
            fps=30,
            height=720,
            tbr=2200.0,
            filesize=180 * 1024 * 1024,
            filesize_str="180 MB",
            note="H.264 • Standard High Definition",
        ),
        FormatOption(
            format_id="18",
            format_type="video",
            label="480p SD",
            resolution="854x480 (30fps)",
            ext="mp4",
            vcodec="avc1.42001e",
            fps=30,
            height=480,
            tbr=1100.0,
            filesize=95 * 1024 * 1024,
            filesize_str="95 MB",
            note="H.264 • Storage efficient",
        ),
        FormatOption(
            format_id="none",
            format_type="video",
            label="🚫 [No Video - Audio Only]",
            resolution="Audio Only",
            note="Extract audio track without video stream",
            is_special=True,
        ),
    ]

    audio_formats = [
        FormatOption(
            format_id="bestaudio",
            format_type="audio",
            label="⭐ Best Audio (Auto)",
            resolution="Best Available",
            note="Selects the highest bitrate audio automatically",
            is_special=True,
        ),
        FormatOption(
            format_id="251",
            format_type="audio",
            label="160 kbps [WEBM] (OPUS)",
            resolution="160 kbps",
            ext="webm",
            acodec="opus",
            tbr=160.0,
            filesize=42 * 1024 * 1024,
            filesize_str="42 MB",
            note="High fidelity Opus audio codec",
        ),
        FormatOption(
            format_id="140",
            format_type="audio",
            label="128 kbps [M4A] (AAC)",
            resolution="128 kbps",
            ext="m4a",
            acodec="mp4a.40.2",
            tbr=128.0,
            filesize=34 * 1024 * 1024,
            filesize_str="34 MB",
            note="Standard AAC audio codec • High compatibility",
        ),
        FormatOption(
            format_id="250",
            format_type="audio",
            label="70 kbps [WEBM] (OPUS)",
            resolution="70 kbps",
            ext="webm",
            acodec="opus",
            tbr=70.0,
            filesize=18 * 1024 * 1024,
            filesize_str="18 MB",
            note="Medium fidelity audio",
        ),
        FormatOption(
            format_id="249",
            format_type="audio",
            label="50 kbps [WEBM] (OPUS)",
            resolution="50 kbps",
            ext="webm",
            acodec="opus",
            tbr=50.0,
            filesize=13 * 1024 * 1024,
            filesize_str="13 MB",
            note="Low bandwidth audio",
        ),
        FormatOption(
            format_id="none",
            format_type="audio",
            label="🔇 [No Audio - Video Only]",
            resolution="Muted",
            note="Download video stream without audio",
            is_special=True,
        ),
    ]

    return ExtractionResult(
        url="https://www.youtube.com/watch?v=jfKfPfyJRdk",
        title="Lofi Girl - Synthwave Radio / Chill Beats to Relax / Study to (24/7 Live Stream)",
        uploader="Lofi Girl",
        duration_str="2:00:00",
        thumbnail="",
        video_formats=video_formats,
        audio_formats=audio_formats,
    )


def setup_demo_download_manager(tmp_path: Path) -> DownloadManager:
    """Populate singleton download manager for download queue screenshot."""
    config = AppConfig()
    hist_mgr = HistoryManager(storage_path=tmp_path / "history.json")
    DownloadManager._instance = None
    manager = DownloadManager.get_instance(config=config, history=hist_mgr, queue_path=tmp_path / "queue.json")

    # Active Task 1: 4K Video Downloading
    t1 = DownloadTask(
        id="a1b2c3d4",
        url="https://www.youtube.com/watch?v=jfKfPfyJRdk",
        title="Interstellar - Main Soundtrack & OST Suite (Official 4K HDR)",
        uploader="Warner Records",
        duration_str="08:45",
        video_format="313",
        video_format_label="2160p 4K UHD",
        audio_format="251",
        audio_format_label="160 kbps (OPUS)",
        audio_quality="320",
        container="mkv",
        status=DownloadStatus.DOWNLOADING,
        progress_percent=72.4,
        speed_str="14.8 MB/s",
        eta_str="00:18",
        downloaded_bytes=int(1450 * 1024 * 1024 * 0.724),
        total_bytes=1450 * 1024 * 1024,
    )
    t1.logs = [
        "[download] Destination: downloads\\Interstellar - Main Soundtrack.mkv",
        "[download]  72.4% of 1.42GiB at 14.80MiB/s ETA 00:18",
    ]

    # Active Task 2: Audio Only Extraction
    t2 = DownloadTask(
        id="e5f6g7h8",
        url="https://www.youtube.com/watch?v=5qap5aO4i9A",
        title="Lofi Hip Hop Radio - Beats to Relax / Study to [High-Bitrate MP3]",
        uploader="ChilledCow",
        duration_str="03:25:00",
        video_format="none",
        video_format_label="[No Video]",
        audio_format="251",
        audio_format_label="160 kbps (OPUS)",
        audio_quality="320",
        container="mp3",
        status=DownloadStatus.DOWNLOADING,
        progress_percent=45.8,
        speed_str="8.2 MB/s",
        eta_str="00:24",
        downloaded_bytes=int(112 * 1024 * 1024 * 0.458),
        total_bytes=112 * 1024 * 1024,
    )

    # Completed Task 3
    t3 = DownloadTask(
        id="i9j0k1l2",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Textualize Python - High-Density Terminal TUI Masterclass",
        uploader="Python Developer",
        duration_str="42:10",
        video_format="137",
        video_format_label="1080p FHD",
        audio_format="140",
        audio_format_label="128 kbps (AAC)",
        audio_quality="256",
        container="mp4",
        status=DownloadStatus.COMPLETED,
        progress_percent=100.0,
        downloaded_bytes=380 * 1024 * 1024,
        total_bytes=380 * 1024 * 1024,
        speed_str="0 B/s",
        eta_str="00:00",
    )

    # Queued Task 4
    t4 = DownloadTask(
        id="m3n4o5p6",
        url="https://www.youtube.com/watch?v=3JZ_D3ELwOQ",
        title="Cyberpunk 2077 - Night City Ambient Soundscape & Synthwave",
        uploader="CD PROJEKT RED",
        duration_str="01:15:20",
        video_format="137",
        video_format_label="1080p FHD",
        audio_format="140",
        audio_format_label="128 kbps (AAC)",
        audio_quality="256",
        container="mp4",
        status=DownloadStatus.QUEUED,
        progress_percent=0.0,
        speed_str="--",
        eta_str="--",
    )

    manager.tasks = [t1, t2, t3, t4]
    return manager


async def generate_all_screenshots():
    """Render and capture each screen to SVG format."""
    assets_dir = Path("assets")
    assets_dir.mkdir(exist_ok=True)
    tmp_dir = Path("build/tmp_screenshots")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig.load()

    # 1. Format Matrix Screen
    print("Generating format_screen.svg...")
    extraction = create_demo_extraction()
    format_screen = FormatScreen(extraction=extraction, config=config)
    app1 = ScreenshotApp(format_screen)
    async with app1.run_test(size=(116, 34)) as pilot:
        await pilot.pause(0.5)
        svg_format = app1.export_screenshot()
        (assets_dir / "format_screen.svg").write_text(svg_format, encoding="utf-8")

    # 2. Download Queue Screen
    print("Generating download_screen.svg...")
    setup_demo_download_manager(tmp_dir)
    download_screen = DownloadScreen(config=config)
    app2 = ScreenshotApp(download_screen)
    async with app2.run_test(size=(116, 34)) as pilot:
        await pilot.pause(0.5)
        try:
            table = download_screen.query_one("#queue-table")
            if table.row_count > 0:
                table.cursor_coordinate = (0, 0)
        except Exception:
            pass
        await pilot.pause(0.3)
        svg_download = app2.export_screenshot()
        (assets_dir / "download_screen.svg").write_text(svg_download, encoding="utf-8")

    # 3. Settings Screen
    print("Generating settings_screen.svg...")
    settings_screen = SettingsScreen(config=config)
    app3 = ScreenshotApp(settings_screen)
    async with app3.run_test(size=(116, 34)) as pilot:
        await pilot.pause(0.5)
        svg_settings = app3.export_screenshot()
        (assets_dir / "settings_screen.svg").write_text(svg_settings, encoding="utf-8")

    print("All 3 screenshots generated successfully in assets/!")


if __name__ == "__main__":
    asyncio.run(generate_all_screenshots())
