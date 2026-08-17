"""Unit tests for config module."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from config import AppConfig


def test_config_defaults():
    config = AppConfig()
    assert config.max_concurrent_downloads == 3
    assert config.retries == 10
    assert config.fragment_retries == 10
    assert config.continuedl is True
    assert config.browser_cookies == "none"
    assert config.embed_metadata is True
    assert config.download_subtitles is False
    assert config.subtitle_mode == "embed"
    assert config.remove_sponsor_segments is False
    assert config.sponsorblock_categories == "sponsor,selfpromo"


def test_config_save_and_load(monkeypatch):
    with TemporaryDirectory() as tmpdir:
        fake_cfg_file = Path(tmpdir) / "config.json"
        monkeypatch.setattr(AppConfig, "config_file_path", classmethod(lambda cls: fake_cfg_file))

        config = AppConfig(
            max_concurrent_downloads=5,
            rate_limit="2M",
            download_subtitles=True,
            browser_cookies="chrome",
        )
        config.save()

        assert fake_cfg_file.exists()

        loaded = AppConfig.load()
        assert loaded.max_concurrent_downloads == 5
        assert loaded.rate_limit == "2M"
        assert loaded.download_subtitles is True
        assert loaded.browser_cookies == "chrome"


def test_config_update(monkeypatch):
    with TemporaryDirectory() as tmpdir:
        fake_cfg_file = Path(tmpdir) / "config.json"
        monkeypatch.setattr(AppConfig, "config_file_path", classmethod(lambda cls: fake_cfg_file))

        config = AppConfig()
        config.update(max_concurrent_downloads=8, rate_limit="500K")

        assert config.max_concurrent_downloads == 8
        assert config.rate_limit == "500K"

        reloaded = AppConfig.load()
        assert reloaded.max_concurrent_downloads == 8
        assert reloaded.rate_limit == "500K"


def test_sanitize_path():
    from config import sanitize_path

    assert sanitize_path(None) == ""
    assert sanitize_path("") == ""
    assert sanitize_path('"C:\\path\\to\\file.txt"') == "C:\\path\\to\\file.txt"
    assert sanitize_path("'C:/path/to/file.txt'") == "C:/path/to/file.txt"
    assert sanitize_path('  "C:\\My Folder\\cookies.txt"  ') == "C:\\My Folder\\cookies.txt"


def test_config_quoted_paths_sanitized():
    cfg = AppConfig(
        download_dir='"C:\\Downloads"',
        cookies_file='"C:\\Users\\test\\cookies.txt"',
    )
    assert cfg.download_dir == "C:\\Downloads"
    assert cfg.cookies_file == "C:\\Users\\test\\cookies.txt"


def test_sponsorblock_categories_are_normalized():
    from config import sanitize_sponsorblock_categories

    assert sanitize_sponsorblock_categories(" sponsor, selfpromo, sponsor,invalid ") == "sponsor,selfpromo"
    assert sanitize_sponsorblock_categories("intro,outro") == "intro,outro"
    assert sanitize_sponsorblock_categories("chapter,poi_highlight") == "sponsor,selfpromo"


def test_atomic_json_save():
    from config import atomic_json_save

    with TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "test_out.json"
        data = {"hello": "world", "num": 42}
        atomic_json_save(target, data)

        assert target.exists()
        tmp_target = Path(tmpdir) / "test_out.json.tmp"
        assert not tmp_target.exists()

        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data


def test_sanitize_filename_template():
    from config import DEFAULT_FILENAME_TEMPLATE, sanitize_filename_template

    # Valid templates
    assert sanitize_filename_template("%(title)s [%(id)s].%(ext)s") == "%(title)s [%(id)s].%(ext)s"
    assert sanitize_filename_template("%(uploader)s/%(title)s.%(ext)s") == "%(uploader)s/%(title)s.%(ext)s"

    # None and empty fallback
    assert sanitize_filename_template(None) == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("   ") == DEFAULT_FILENAME_TEMPLATE

    # Path traversal prevention
    assert sanitize_filename_template("../%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("..\\%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("sub/../../etc/passwd") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("/var/downloads/%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("\\Windows\\System32\\%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("C:\\Windows\\%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE
    assert sanitize_filename_template("D:/downloads/%(title)s.%(ext)s") == DEFAULT_FILENAME_TEMPLATE


def test_app_config_filename_template_traversal_protection():
    from config import DEFAULT_FILENAME_TEMPLATE

    cfg = AppConfig(filename_template="../hacked.mp4")
    assert cfg.filename_template == DEFAULT_FILENAME_TEMPLATE

    cfg.update(filename_template="C:\\Windows\\hacked.mp4")
    assert cfg.filename_template == DEFAULT_FILENAME_TEMPLATE
