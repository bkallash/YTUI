"""Unit tests for download history module."""

from pathlib import Path
from tempfile import TemporaryDirectory

from history import HistoryItem, HistoryManager


def test_history_item_properties():
    item = HistoryItem(
        id="test1",
        title="Test Song",
        url="https://youtube.com/watch?v=12345",
        channel="Artist",
        duration_str="03:45",
        filepath="C:/Downloads/test.mp3",
        filesize_bytes=10 * 1024 * 1024,
        format_note="bestaudio (mp3)",
        timestamp=1700000000.0,
    )
    assert item.formatted_size == "10.00 MB"
    assert "2023" in item.formatted_time or "2024" in item.formatted_time


def test_history_manager_add_and_remove():
    with TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "history.json"
        mgr = HistoryManager(storage_path=storage)
        assert len(mgr.items) == 0

        item1 = HistoryItem(
            id="1",
            title="Video 1",
            url="http://v1",
            channel="Chan 1",
            duration_str="10:00",
            filepath="/tmp/v1.mp4",
            filesize_bytes=5000000,
            format_note="1080p+mp3",
        )
        mgr.add(item1)
        assert len(mgr.items) == 1

        # Check persistence
        mgr2 = HistoryManager(storage_path=storage)
        assert len(mgr2.items) == 1
        assert mgr2.items[0].title == "Video 1"

        # Remove
        mgr2.remove("1")
        assert len(mgr2.items) == 0


def test_history_case_insensitive_filter():
    with TemporaryDirectory() as tmpdir:
        storage = Path(tmpdir) / "history.json"
        mgr = HistoryManager(storage_path=storage)

        item1 = HistoryItem(
            id="1",
            title="Lofi Hip Hop Beats - Chill Study Music",
            url="https://youtube.com/watch?v=lofi123",
            channel="Lofi Girl",
            duration_str="10:00",
            filepath="C:/Downloads/Lofi Hip Hop.mp4",
            filesize_bytes=50000000,
            format_note="1080p FHD (mp4)",
        )
        item2 = HistoryItem(
            id="2",
            title="TAYLOR SWIFT - CRUEL SUMMER (LIVE CONCERT)",
            url="https://youtube.com/watch?v=taylor123",
            channel="TaylorSwiftVEVO",
            duration_str="03:58",
            filepath="C:/Downloads/Taylor Swift Cruel Summer.mp3",
            filesize_bytes=10000000,
            format_note="320 kbps (mp3)",
        )
        mgr.add(item1)
        mgr.add(item2)

        # 1. Lowercase search matches uppercase title
        res_lower = mgr.filter("taylor swift")
        assert len(res_lower) == 1
        assert res_lower[0].id == "2"

        # 2. Uppercase search matches lowercase title
        res_upper = mgr.filter("LOFI BEATS")
        assert len(res_upper) == 1
        assert res_upper[0].id == "1"

        # 3. Mixed case search
        res_mixed = mgr.filter("CrUeL sUmMeR")
        assert len(res_mixed) == 1
        assert res_mixed[0].id == "2"

        # 4. Search by format note case-insensitively
        res_fmt = mgr.filter("fhd")
        assert len(res_fmt) == 1
        assert res_fmt[0].id == "1"

        res_fmt2 = mgr.filter("320 KBPS")
        assert len(res_fmt2) == 1
        assert res_fmt2[0].id == "2"

        # 5. Empty query returns all
        assert len(mgr.filter("")) == 2
        assert len(mgr.filter("   ")) == 2

        # 6. Non-matching query returns empty
        assert len(mgr.filter("nonexistent 999")) == 0


def test_history_open_folder_windows(monkeypatch, tmp_path):
    import subprocess
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    recorded_calls = []

    def mock_popen(args, **kwargs):
        recorded_calls.append(args)
        return None

    monkeypatch.setattr(subprocess, "Popen", mock_popen)

    # Test file that exists
    test_file = tmp_path / "video.mp4"
    test_file.write_text("dummy")

    assert HistoryManager.open_folder(str(test_file)) is True
    assert len(recorded_calls) == 1
    assert recorded_calls[0] == ["explorer", f"/select,{test_file.resolve()}"]

    # Test non-existing file (opens target_dir)
    non_existent = tmp_path / "not_there.mp4"
    assert HistoryManager.open_folder(str(non_existent)) is True
    assert len(recorded_calls) == 2
    assert recorded_calls[1] == ["explorer", str(tmp_path.resolve())]


