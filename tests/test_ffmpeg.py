"""Unit and async UI tests for FFmpeg detection, path management, and setup modal."""

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Button, Checkbox, Label, ProgressBar

from app import YtDlpApp
from config import AppConfig
import ffmpeg_utils
from screens.ffmpeg_modal import FfmpegSetupModal


def test_get_ffmpeg_bin_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("ffmpeg_utils.get_config_dir", lambda: tmp_path)
    bin_dir = ffmpeg_utils.get_ffmpeg_bin_dir()
    assert bin_dir.exists()
    assert bin_dir == tmp_path / "bin"


def test_find_binary_custom_dir(tmp_path):
    target_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    dummy_bin = tmp_path / target_name
    dummy_bin.write_bytes(b"dummy")

    found = ffmpeg_utils.find_binary("ffmpeg", custom_dir=str(tmp_path))
    assert found == str(dummy_bin.resolve())


def test_find_binary_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    monkeypatch.setattr("ffmpeg_utils.get_ffmpeg_bin_dir", lambda: tmp_path / "nonexistent")
    assert ffmpeg_utils.find_binary("nonexistent_tool_12345") is None


def test_ensure_ffmpeg_in_path(tmp_path, monkeypatch):
    target_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    dummy_bin = tmp_path / target_name
    dummy_bin.write_bytes(b"dummy")

    monkeypatch.setattr(ffmpeg_utils, "find_ffmpeg", lambda *args: str(dummy_bin))
    res = ffmpeg_utils.ensure_ffmpeg_in_path()
    assert res == str(dummy_bin)


def test_download_and_install_ffmpeg_mocked(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg_bin_dir", lambda: bin_dir)

    # Create a dummy zip archive in memory with ffmpeg.exe / ffmpeg
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        if sys.platform == "win32":
            zf.writestr("ffmpeg-master/bin/ffmpeg.exe", b"ffmpeg binary content")
            zf.writestr("ffmpeg-master/bin/ffprobe.exe", b"ffprobe binary content")
        else:
            zf.writestr("ffmpeg-master/bin/ffmpeg", b"ffmpeg binary content")
            zf.writestr("ffmpeg-master/bin/ffprobe", b"ffprobe binary content")

    zip_bytes = zip_buffer.getvalue()

    class MockResponse:
        def __init__(self, data):
            self.data = io.BytesIO(data)
            self.headers = {"content-length": str(len(data))}

        def read(self, size=-1):
            return self.data.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: MockResponse(zip_bytes))

    progress_records = []

    def on_progress(d, t, p, msg):
        progress_records.append((d, t, p, msg))

    success, msg = ffmpeg_utils.download_and_install_ffmpeg(progress_callback=on_progress)
    assert success is True
    assert len(progress_records) > 0

    target_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    assert (bin_dir / target_name).exists()
    assert (bin_dir / target_name).read_bytes() == b"ffmpeg binary content"


@pytest.mark.asyncio
async def test_ffmpeg_modal_skip(monkeypatch, tmp_path):
    monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
    app = YtDlpApp()
    async with app.run_test() as pilot:
        modal = FfmpegSetupModal(is_first_launch=True)
        await app.push_screen(modal)
        await pilot.pause()

        chk = modal.query_one("#chk-dont-ask", Checkbox)
        chk.value = True

        btn_skip = modal.query_one("#btn-skip-ffmpeg", Button)
        btn_skip.press()
        await pilot.pause()

        config = AppConfig.load()
        assert config.skip_ffmpeg_check is True


@pytest.mark.asyncio
async def test_ffmpeg_modal_download_success(monkeypatch, tmp_path):
    monkeypatch.setattr("config.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr(ffmpeg_utils, "download_and_install_ffmpeg", lambda progress_callback=None: (True, "Installed!"))
    monkeypatch.setattr(ffmpeg_utils, "get_ffmpeg_bin_dir", lambda: tmp_path / "bin")

    app = YtDlpApp()
    async with app.run_test() as pilot:
        modal = FfmpegSetupModal(is_first_launch=True)
        await app.push_screen(modal)
        await pilot.pause()

        btn_dl = modal.query_one("#btn-download-ffmpeg", Button)
        btn_dl.press()
        await pilot.pause(0.5)

        # Wait for callback execution
        assert modal._is_downloading is True
