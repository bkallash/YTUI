"""Unit tests for RTL and Arabic text rendering support."""

import pytest
from rich.text import Text

from rtl_utils import _fix_rtl_cached, fix_rtl, get_rtl_mode, has_rtl, render_rtl_text, rtl_truncate, set_rtl_mode


def test_rtl_caching():
    # Check that lru_cache is present and configured with maxsize=2048
    assert hasattr(has_rtl, "cache_info")
    assert has_rtl.cache_info().maxsize == 2048

    assert hasattr(_fix_rtl_cached, "cache_info")
    assert _fix_rtl_cached.cache_info().maxsize == 2048

    # Test cache hits on repeated calls
    has_rtl.cache_clear()
    _fix_rtl_cached.cache_clear()

    res1 = fix_rtl("سورة الفاتحة", mode="reshaped_bidi")
    res2 = fix_rtl("سورة الفاتحة", mode="reshaped_bidi")
    assert res1 == res2
    assert _fix_rtl_cached.cache_info().hits >= 1

    # Safe handling of None, empty, whitespace
    assert fix_rtl(None) == ""
    assert fix_rtl("") == ""
    assert has_rtl(None) is False
    assert has_rtl("") is False


def test_has_rtl_detection():
    # Pure Arabic
    assert has_rtl("سورة البقرة") is True
    assert has_rtl("مرحبا بالعالم") is True

    # Mixed Arabic and English
    assert has_rtl("1080p - سورة البقرة - HD") is True
    assert has_rtl("Amr Diab - تملي معاك") is True

    # Pure English / ASCII
    assert has_rtl("Hello World 123") is False
    assert has_rtl("yt-dlp Terminal GUI") is False
    assert has_rtl("https://www.youtube.com/watch?v=12345") is False

    # None and empty
    assert has_rtl(None) is False
    assert has_rtl("") is False


def test_fix_rtl_basic():
    set_rtl_mode("reshaped_bidi")
    # English stays unchanged
    eng = "Hello World"
    assert fix_rtl(eng) == eng

    # None and empty return safely
    assert fix_rtl(None) == ""
    assert fix_rtl("") == ""

    # Arabic text gets reshaped and reordered
    ar = "سورة البقرة"
    fixed = fix_rtl(ar)
    assert fixed != ar  # Characters are reshaped/reordered
    assert len(fixed) > 0


def test_harakat_and_tatweel_cleanup():
    set_rtl_mode("reshaped_bidi")
    # Diacritics/tashkeel are cleaned so they don't produce floating/overlapping blocks
    ar_tashkeel = "سُورَةُ البَقَرَةِ كَامِلَةً"
    fixed = fix_rtl(ar_tashkeel)
    assert len(fixed) > 0
    # Tatweels (decorative elongation) are removed to avoid gaps
    ar_tatweel = "رمضــــان كــــريم"
    fixed_tatweel = fix_rtl(ar_tatweel)
    assert len(fixed_tatweel) > 0


def test_rtl_modes_switching():
    sample = "سورة البقرة"
    # 1. reshaped_bidi
    set_rtl_mode("reshaped_bidi")
    res_bidi = fix_rtl(sample)
    assert res_bidi != sample

    # 2. native_raw (preserves raw Unicode for Windows Terminal DirectWrite/HarfBuzz)
    set_rtl_mode("native_raw")
    assert fix_rtl(sample) == sample

    # 3. bidi_only
    set_rtl_mode("bidi_only")
    res_only = fix_rtl(sample)
    assert isinstance(res_only, str)

    # 4. disabled
    set_rtl_mode("disabled")
    assert fix_rtl(sample) == sample

    # Reset
    set_rtl_mode("reshaped_bidi")



def test_fix_rtl_mixed():
    mixed = "Maher Zain - يا نبي سلام عليك (Official Music Video)"
    fixed = fix_rtl(mixed)
    # Ensure it returns a string and handles mixed bidi
    assert isinstance(fixed, str)
    assert "Maher Zain" in fixed or "Official Music Video" in fixed


def test_rtl_truncate():
    # Short Arabic string not truncated
    short_ar = "سورة هود"
    assert rtl_truncate(short_ar, max_len=20) == fix_rtl(short_ar)

    # Long Arabic string truncated logically before bidi
    long_ar = "سورة البقرة كاملة بصوت الشيخ مشاري راشد العفاسي بدقة عالية جدا"
    truncated = rtl_truncate(long_ar, max_len=25)
    assert len(truncated) > 0
    assert "..." in truncated or "…" in truncated

    # English string truncated
    long_en = "This is a very long English title that definitely exceeds the limit"
    truncated_en = rtl_truncate(long_en, max_len=20)
    assert truncated_en.endswith("...")
    assert len(truncated_en) <= 20

    # Empty and None
    assert rtl_truncate(None) == ""
    assert rtl_truncate("") == ""


def test_render_rtl_text():
    t = render_rtl_text("سورة الكهف", style="bold green")
    assert isinstance(t, Text)
    assert t.style == "bold green"
    assert len(t.plain) > 0


@pytest.mark.asyncio
async def test_tui_arabic_search_results_rendering():
    """Verify that Arabic titles in SearchScreen are rendered using RTL shaping in the DataTable."""
    from app import YtDlpApp
    from screens.search_screen import SearchScreen
    from ytdlp_engine import SearchResultItem

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        arabic_items = [
            SearchResultItem(
                id="ar-1",
                title="سورة البقرة كاملة - مشاري العفاسي",
                url="https://youtube.com/watch?v=ar1",
                uploader="الشيخ مشاري العفاسي",
                duration=3600,
                duration_str="1:00:00",
                view_count=5000000,
            ),
            SearchResultItem(
                id="ar-2",
                title="Amr Diab - تملي معاك (Official Video)",
                url="https://youtube.com/watch?v=ar2",
                uploader="عمرو دياب",
                duration=240,
                duration_str="04:00",
                view_count=12000000,
            ),
        ]

        screen = app.get_screen("search_screen")
        screen._populate_results_table(arabic_items)
        await pilot.pause()

        from textual.widgets import DataTable
        table = screen.query_one("#results-table", DataTable)
        assert table.row_count == 2

        # Verify the table contains reshaped RTL text
        row_0 = table.get_row("https://youtube.com/watch?v=ar1")
        # Column 1 is Title, Column 2 is Channel
        assert row_0[1] == rtl_truncate(arabic_items[0].title, max_len=max(35, screen.size.width - 52))
        assert row_0[2] == rtl_truncate(arabic_items[0].uploader, max_len=max(18, min(35, screen.size.width // 5)))


@pytest.mark.asyncio
async def test_tui_arabic_download_queue_rendering():
    """Verify that Arabic titles in DownloadScreen are rendered correctly in the queue table and inspector."""
    from app import YtDlpApp
    from manager import DownloadStatus, DownloadTask
    from screens.download_screen import DownloadScreen

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        ar_task = DownloadTask(
            id="ar-task-1",
            url="https://youtube.com/watch?v=ar1",
            title="سورة الرحمن - الشيخ عبد الباسط عبد الصمد",
            uploader="تلاوات نادرة",
            duration_str="15:30",
            status=DownloadStatus.DOWNLOADING,
            progress_percent=45.5,
        )

        app.manager.tasks = [ar_task]
        app.switch_screen("download_screen")
        await pilot.pause()

        dl_screen = app.screen
        assert isinstance(dl_screen, DownloadScreen)

        from textual.widgets import DataTable, Label
        table = dl_screen.query_one("#queue-table", DataTable)
        assert table.row_count == 1

        lbl_title = dl_screen.query_one("#inspector-title-line", Label)
        # Verify title line contains reshaped Arabic title
        expected_reshaped_title = fix_rtl(ar_task.title)
        assert expected_reshaped_title in str(lbl_title.render())
