"""Test isolation: no real downloads, no network extraction, and no writes to the user's config dir."""

from typing import Any

import pytest
import yt_dlp

from ytui import config as config_module
from ytui import ffmpeg_utils
from ytui.manager import DownloadManager, DownloadTask

ORIGINAL_EXECUTE_DOWNLOAD = DownloadManager._execute_download
# Kept by reference: tests may monkeypatch the module attribute with a plain function.
GET_CONFIG_DIR = config_module.get_config_dir


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    # Config, history and queue files go to a per-test home directory.
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(home))
    GET_CONFIG_DIR.cache_clear()
    ffmpeg_utils.clear_ffmpeg_cache()

    def mock_execute_download(self, task: DownloadTask) -> None:
        pass

    monkeypatch.setattr(DownloadManager, "_execute_download", mock_execute_download)

    def mock_ytdlp_download(self, url_list: Any) -> int:
        return 0

    monkeypatch.setattr(yt_dlp.YoutubeDL, "download", mock_ytdlp_download)

    # Pretend FFmpeg exists so the app starts directly on the search screen.
    import ytui.app

    monkeypatch.setattr(ytui.app, "is_ffmpeg_available", lambda *args, **kwargs: True)

    yield

    GET_CONFIG_DIR.cache_clear()
    ffmpeg_utils.clear_ffmpeg_cache()
