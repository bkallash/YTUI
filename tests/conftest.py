"""Global pytest configuration and safety mocks to prevent real video downloads during tests."""

from typing import Any, Dict, Optional
import pytest
import yt_dlp

from manager import DownloadManager, DownloadStatus, DownloadTask


ORIGINAL_EXECUTE_DOWNLOAD = DownloadManager._execute_download


@pytest.fixture(autouse=True)
def prevent_real_downloads(monkeypatch):
    """Safety fixture to guarantee no real video download or network extraction happens in tests."""

    # 1. Mock DownloadManager._execute_download so worker threads never download videos
    def mock_execute_download(self, task: DownloadTask) -> None:
        pass

    monkeypatch.setattr(DownloadManager, "_execute_download", mock_execute_download)

    # 2. Mock yt_dlp.YoutubeDL.download
    def mock_ytdlp_download(self, url_list: Any) -> int:
        return 0

    monkeypatch.setattr(yt_dlp.YoutubeDL, "download", mock_ytdlp_download)

    # 3. Mock ffmpeg availability to True by default so tests start directly in SearchScreen
    import ffmpeg_utils
    monkeypatch.setattr(ffmpeg_utils, "is_ffmpeg_available", lambda *args, **kwargs: True)

    yield

    # Teardown: ensure DownloadManager singleton is cleanly shutdown
    if DownloadManager._instance is not None:
        try:
            DownloadManager._instance.shutdown()
        except Exception:
            pass
        DownloadManager._instance = None
