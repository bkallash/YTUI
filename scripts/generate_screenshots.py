"""Generate the SVG screenshots used in README.md (run from the repository root)."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import List

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point config/history/queue at a throwaway home so screenshots never touch real settings.
_TMP_HOME = tempfile.mkdtemp(prefix="ytui-screens-")
for _var in ("HOME", "USERPROFILE", "APPDATA"):
    os.environ[_var] = _TMP_HOME

from ytui.app import YtDlpApp  # noqa: E402
from ytui.formats import ExtractionResult, FormatOption  # noqa: E402
from ytui.manager import DownloadManager, DownloadStatus, DownloadTask  # noqa: E402
from ytui.screens.format_screen import FormatScreen  # noqa: E402

SIZE = (116, 34)


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


def demo_tasks() -> List[DownloadTask]:
    """Representative queue entries for the download queue screenshot."""
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

    return [t1, t2, t3, t4]


async def generate_all_screenshots() -> None:
    """Render each screen of the real app and save it as SVG."""
    assets_dir = Path("assets")
    assets_dir.mkdir(exist_ok=True)
    DownloadManager._execute_download = lambda self, task: None  # never download while capturing

    app = YtDlpApp()
    async with app.run_test(size=SIZE) as pilot:
        app.config.skip_ffmpeg_check = True
        await pilot.pause(0.5)

        print("Generating format_screen.svg...")
        app.push_screen(FormatScreen(create_demo_extraction()))
        await pilot.pause(0.5)
        (assets_dir / "format_screen.svg").write_text(app.export_screenshot(), encoding="utf-8")

        print("Generating download_screen.svg...")
        app.manager.tasks = demo_tasks()
        await pilot.press("ctrl+j")
        await pilot.pause(0.5)
        (assets_dir / "download_screen.svg").write_text(app.export_screenshot(), encoding="utf-8")

        print("Generating settings_screen.svg...")
        await pilot.press("ctrl+o")
        await pilot.pause(0.5)
        (assets_dir / "settings_screen.svg").write_text(app.export_screenshot(), encoding="utf-8")

    print("All 3 screenshots generated successfully in assets/!")


if __name__ == "__main__":
    asyncio.run(generate_all_screenshots())
