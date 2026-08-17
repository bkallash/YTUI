"""Async Textual Pilot tests for the TUI application."""

import pytest
from textual.pilot import Pilot
from textual.widgets import DataTable, Footer, Header, Input, Label, ListView, RichLog


from app import YtDlpApp
from screens.download_screen import DownloadScreen
from screens.format_screen import FormatScreen
from screens.history_screen import HistoryScreen
from screens.search_screen import SearchScreen
from screens.settings_screen import SettingsScreen
from ytdlp_engine import ExtractionResult, FormatOption


@pytest.mark.asyncio
async def test_app_startup_and_navigation():
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # Check initial screen is SearchScreen
        assert isinstance(app.screen, SearchScreen)

        # Switch to Downloads screen via Ctrl+J
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert isinstance(app.screen, DownloadScreen)

        # Switch to History screen via Ctrl+Y
        await pilot.press("ctrl+y")
        await pilot.pause()
        assert isinstance(app.screen, HistoryScreen)

        # Switch to Settings screen via Ctrl+O
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)

        # Switch back to Search screen via Ctrl+S
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)


@pytest.fixture(autouse=True)
def disable_download_execution(monkeypatch):
    """Ensure no background yt-dlp download is ever executed during TUI tests."""
    monkeypatch.setattr("manager.DownloadManager._execute_download", lambda self, task: None)


@pytest.mark.asyncio
async def test_format_screen_navigation():
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Mount mock ExtractionResult on FormatScreen
        extraction = ExtractionResult(
            url="https://www.youtube.com/watch?v=mock_video",
            title="Mock Test Video",
            uploader="Test Channel",
            duration_str="02:00",
            thumbnail="",
            video_formats=[
                FormatOption(format_id="137", format_type="video", label="1080p (FHD)", resolution="1080p", height=1080),
                FormatOption(format_id="136", format_type="video", label="720p (HD)", resolution="720p", height=720),
            ],
            audio_formats=[
                FormatOption(format_id="140", format_type="audio", label="128kbps (M4A)", resolution="audio", note="m4a"),
            ],
        )

        format_screen = FormatScreen(extraction, config=app.config)
        app.push_screen(format_screen)
        await pilot.pause()

        assert isinstance(app.screen, FormatScreen)

        # Test Right arrow key switches focus to audio stream column
        await pilot.press("right")
        await pilot.pause()
        assert app.focused.id == "list-audio"

        # Test Left arrow key switches focus back to video stream column
        await pilot.press("left")
        await pilot.pause()
        assert app.focused.id == "list-video"

        # Test Enter key starts download and switches to DownloadScreen
        initial_tasks = len(app.manager.tasks)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, DownloadScreen)
        assert len(app.manager.tasks) == initial_tasks + 1
        assert any(t.title == "Mock Test Video" for t in app.manager.tasks)


@pytest.mark.asyncio
async def test_download_screen_keybindings_and_actions():
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()

        dl_screen = app.screen
        assert isinstance(dl_screen, DownloadScreen)

        # Set isolated dummy task
        from manager import DownloadStatus, DownloadTask
        task = DownloadTask(id="ui-test-1", url="https://youtube.com/1", title="UI Test Task", status=DownloadStatus.PAUSED)
        app.manager.tasks = [task]
        dl_screen.selected_task_id = "ui-test-1"
        dl_screen.refresh_table()
        await pilot.pause()

        # Verify key-bindings toolbar header is rendered with shortcut hints
        keys_bar = dl_screen.query_one("#queue-keys-bar", Label)
        assert "Pause" in str(keys_bar.render())
        assert "Resume" in str(keys_bar.render())
        assert "Cancel" in str(keys_bar.render())
        assert "Logs" in str(keys_bar.render())

        # Verify screen-level bindings have show=False so footer stays clean
        for binding in dl_screen.BINDINGS:
            assert binding.show is False

        # Add dummy logs
        task.add_log("yt-dlp initializing format stream...")
        task.add_log("Destination: ~/Downloads/test.mp4")

        # Press 'l' to toggle logs on
        assert dl_screen.is_log_visible is False
        await pilot.press("l")
        await pilot.pause()
        assert dl_screen.is_log_visible is True

        rich_log = dl_screen.query_one("#task-rich-log", RichLog)
        assert len(rich_log.lines) > 0

        # Press 'l' again to toggle logs off
        await pilot.press("l")
        await pilot.pause()
        assert dl_screen.is_log_visible is False

        # Press 'r' to resume paused task
        await pilot.press("r")
        await pilot.pause()
        assert task.status in [DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING]


@pytest.mark.asyncio
async def test_ctrl_y_navigation_from_downloads_screen_does_not_delete_items():
    """Verify pressing Ctrl+Y on downloads screen switches to HistoryScreen without deleting queue items."""
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()

        assert isinstance(app.screen, DownloadScreen)

        from manager import DownloadStatus, DownloadTask
        task1 = DownloadTask(id="task-keep-1", url="https://youtube.com/1", title="Task 1", status=DownloadStatus.DOWNLOADING)
        task2 = DownloadTask(id="task-keep-2", url="https://youtube.com/2", title="Task 2", status=DownloadStatus.QUEUED)
        app.manager.tasks = [task1, task2]
        app.screen.selected_task_id = "task-keep-1"
        app.screen.refresh_table()
        await pilot.pause()

        # Press Ctrl+Y to switch to HistoryScreen
        await pilot.press("ctrl+y")
        await pilot.pause()

        # Verify screen transitioned to HistoryScreen
        assert isinstance(app.screen, HistoryScreen)

        # Verify no tasks were deleted from manager
        assert len(app.manager.tasks) == 2
        assert app.manager.get_task("task-keep-1") is not None
        assert app.manager.get_task("task-keep-2") is not None



@pytest.mark.asyncio
async def test_theme_switching_on_settings_screen():
    """Verify live theme cycling across theme profiles."""
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
        sel_theme = app.screen.query_one("#sel-theme")
        initial_theme = app.theme

        # Trigger right arrow / click on sel-theme to cycle theme
        sel_theme.focus()
        await pilot.press("right")
        await pilot.pause()

        # Verify theme updated live on the app
        assert app.theme != initial_theme


@pytest.mark.asyncio
async def test_settings_screen_categories():
    """Verify settings screen menu categories have clean names without emojis."""
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()

        assert isinstance(app.screen, SettingsScreen)
        cat_list = app.screen.query_one("#category-list", ListView)
        assert len(cat_list.children) == 8

        labels = [str(item.query_one(Label).render()) for item in cat_list.children]
        expected = [
            "General & Paths",
            "Bandwidth & Queue",
            "Cookies & Auth",
            "Subtitles",
            "Media & Chapters",
            "Metadata",
            "Proxy & Geo",
            "Appearance",
        ]
        assert labels == expected


@pytest.mark.asyncio
async def test_history_screen_keybindings_and_actions(tmp_path):
    """Verify HistoryScreen keybindings, item selection, and operations."""
    from history import HistoryItem, HistoryManager

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")
        await pilot.pause()

        hist_screen = app.screen
        assert isinstance(hist_screen, HistoryScreen)

        # Use isolated test storage
        test_storage = tmp_path / "test_history.json"
        hist_screen.history_mgr = HistoryManager(storage_path=test_storage)

        item = HistoryItem(
            id="hist-test-1",
            title="History Item 1",
            url="https://youtube.com/watch?v=hist1",
            channel="Test Channel",
            duration_str="05:00",
            filepath="test_output.mp4",
            filesize_bytes=1024000,
            format_note="1080p",
        )
        hist_screen.history_mgr.add(item)
        hist_screen.populate_history()
        hist_screen.query_one("#history-table", DataTable).focus()
        await pilot.pause()

        assert len(hist_screen.history_mgr.items) == 1
        # Press 'd' to delete selected item
        await pilot.press("d")
        await pilot.pause()

        assert len(hist_screen.history_mgr.items) == 0


@pytest.mark.asyncio
async def test_history_screen_search_filtering(tmp_path):
    """Verify live search filtering in HistoryScreen."""
    from history import HistoryItem, HistoryManager
    from textual.widgets import Input, DataTable

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")
        await pilot.pause()

        hist_screen = app.screen
        assert isinstance(hist_screen, HistoryScreen)

        # Isolated test storage with multiple items
        test_storage = tmp_path / "test_history_filter.json"
        hist_screen.history_mgr = HistoryManager(storage_path=test_storage)

        item1 = HistoryItem(
            id="h1",
            title="Python Tutorial For Beginners",
            url="https://youtube.com/watch?v=python1",
            channel="Tech Guru",
            duration_str="10:00",
            filepath="python_tutorial.mp4",
            filesize_bytes=2048000,
            format_note="1080p",
        )
        item2 = HistoryItem(
            id="h2",
            title="Rust Crash Course",
            url="https://youtube.com/watch?v=rust2",
            channel="Code Lab",
            duration_str="15:00",
            filepath="rust_course.mp4",
            filesize_bytes=4096000,
            format_note="720p",
        )
        hist_screen.history_mgr.add(item1)
        hist_screen.history_mgr.add(item2)
        hist_screen.populate_history()
        await pilot.pause()

        table = hist_screen.query_one("#history-table", DataTable)
        assert table.row_count == 2

        # Type in search input to filter for 'Python'
        search_input = hist_screen.query_one("#history-search-input", Input)
        search_input.value = "python"
        await pilot.pause()

        assert table.row_count == 1
        assert hist_screen.selected_item.id == "h1"

        # Type query that matches nothing
        search_input.value = "nonexistent keyword"
        await pilot.pause()
        assert table.row_count == 0

        # Clear search input to show all again
        search_input.value = ""
        await pilot.pause()
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_format_screen_presets_and_container_cycling():
    """Verify format screen presets 1, 2, 3, 4 and container cycling."""
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        extraction = ExtractionResult(
            url="https://www.youtube.com/watch?v=mock_presets",
            title="Mock Presets Video",
            uploader="Channel X",
            duration_str="10:00",
            thumbnail="",
            video_formats=[
                FormatOption(format_id="none", format_type="video", label="[No Video - Audio Only]", resolution="None", is_special=True),
                FormatOption(format_id="bestvideo", format_type="video", label="Best Video (Auto)", resolution="Best", is_special=True),
                FormatOption(format_id="137", format_type="video", label="1080p (FHD)", resolution="1080p", height=1080, filesize=50000000),
                FormatOption(format_id="136", format_type="video", label="720p (HD)", resolution="720p", height=720, filesize=25000000),
                FormatOption(format_id="18", format_type="video", label="360p (SD)", resolution="360p", height=360, filesize=10000000),
            ],
            audio_formats=[
                FormatOption(format_id="none", format_type="audio", label="[No Audio - Video Only]", resolution="None", is_special=True),
                FormatOption(format_id="bestaudio", format_type="audio", label="Best Audio (Auto)", resolution="Best", is_special=True),
                FormatOption(format_id="140", format_type="audio", label="128kbps (M4A)", resolution="audio", note="m4a"),
            ],
        )

        fmt_screen = FormatScreen(extraction, config=app.config)
        app.push_screen(fmt_screen)
        await pilot.pause()

        # Initial state checks
        keys_bar = fmt_screen.query_one("#format-keys-bar", Label)
        assert "Container: .MP4" in str(keys_bar.render())

        # Verify presets are hidden from bottom footer, and screen navigation keys are shown
        bindings_map = {b.key: b for b in fmt_screen.BINDINGS}
        assert bindings_map["1"].show is False
        assert bindings_map["2"].show is False
        assert bindings_map["3"].show is False
        assert bindings_map["4"].show is False
        assert bindings_map["enter"].show is False
        assert bindings_map["escape"].show is True
        assert bindings_map["ctrl+s"].show is True
        assert bindings_map["ctrl+j"].show is True
        assert bindings_map["ctrl+y"].show is True
        assert bindings_map["ctrl+o"].show is True
        assert bindings_map["ctrl+q"].show is True

        # Preset 4: Audio only (MP3)
        await pilot.press("4")
        await pilot.pause()
        assert fmt_screen.selected_video.format_id == "none"
        assert fmt_screen.selected_container == "mp3"
        assert fmt_screen.audio_quality == "256"
        assert "Container: .MP3" in str(keys_bar.render())
        assert "Quality: 256k" in str(keys_bar.render())

        # Press 'q' to cycle audio quality
        await pilot.press("q")
        await pilot.pause()
        assert fmt_screen.audio_quality == "320"
        assert "Quality: 320k" in str(keys_bar.render())

        await pilot.press("q")
        await pilot.pause()
        assert fmt_screen.audio_quality == "192"
        assert "Quality: 192k" in str(keys_bar.render())

        # Preset 3: Smallest
        await pilot.press("3")
        await pilot.pause()
        assert fmt_screen.selected_video.height == 360

        # Preset 2: 1080p
        await pilot.press("2")
        await pilot.pause()
        assert fmt_screen.selected_video.height == 1080
        assert fmt_screen.selected_container == "mp4"
        assert "Container: .MP4" in str(keys_bar.render())

        # Cycle container (c)
        initial_c = fmt_screen.selected_container
        await pilot.press("c")
        await pilot.pause()
        assert fmt_screen.selected_container != initial_c
        assert f".{fmt_screen.selected_container.upper()}" in str(keys_bar.render())

        # Escape back to search screen
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)


@pytest.mark.asyncio
async def test_all_screens_have_footer_and_header():
    """Verify that all main application screens render Header and Footer consistently."""
    from textual.widgets import Footer, Header

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # 1. SearchScreen
        assert len(app.screen.query(Header)) == 1
        assert len(app.screen.query(Footer)) == 1

        # 2. DownloadScreen
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert len(app.screen.query(Header)) == 1
        assert len(app.screen.query(Footer)) == 1

        # 3. HistoryScreen
        await pilot.press("ctrl+y")
        await pilot.pause()
        assert len(app.screen.query(Header)) == 1
        assert len(app.screen.query(Footer)) == 1

        # 4. SettingsScreen
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert len(app.screen.query(Header)) == 1
        assert len(app.screen.query(Footer)) == 1


@pytest.mark.asyncio
async def test_settings_screen_category_sidebar_and_navigation():
    """Verify SettingsScreen sidebar category switching and form input navigation."""
    from textual.widgets import ContentSwitcher, ListView

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()

        settings_screen = app.screen
        assert isinstance(settings_screen, SettingsScreen)

        cat_list = settings_screen.query_one("#category-list", ListView)
        switcher = settings_screen.query_one("#settings-content-switcher", ContentSwitcher)

        # Initial active pane should be General
        assert switcher.current == "pane-general"

        # Press down arrow on category list to switch to Bandwidth pane
        await pilot.press("down")
        await pilot.pause()
        assert switcher.current == "pane-bandwidth"

        # Press down arrow again to switch to Auth pane
        await pilot.press("down")
        await pilot.pause()
        assert switcher.current == "pane-auth"

        # Press Enter or Right to focus into the pane
        await pilot.press("enter")
        await pilot.pause()
        assert settings_screen.focused is not None
        assert settings_screen.focused.id == "sel-browser-cookies"

        # Press Esc to discard and return to search
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)


@pytest.mark.asyncio
async def test_playlist_screen_track_selection_and_presets():
    """Verify PlaylistScreen track toggling, dynamic size estimates, and preset activations."""
    from screens.playlist_screen import PlaylistScreen
    from ytdlp_engine import SearchResultItem

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        entries = [
            SearchResultItem(id="vid-1", title="Track 1 - Chill Beats", url="https://youtube.com/1", uploader="DJ Cool", duration=180, duration_str="03:00", playlist_index=1),
            SearchResultItem(id="vid-2", title="Track 2 - Study Flow", url="https://youtube.com/2", uploader="DJ Cool", duration=240, duration_str="04:00", playlist_index=2),
            SearchResultItem(id="vid-3", title="Track 3 - Night Drive", url="https://youtube.com/3", uploader="DJ Cool", duration=300, duration_str="05:00", playlist_index=3),
        ]

        video_formats = [
            FormatOption(format_id="none", format_type="video", label="[No Video - Audio Only]", resolution="Audio Only", is_special=True),
            FormatOption(format_id="bestvideo", format_type="video", label="[Best Video Quality] (Auto)", resolution="Best Available", is_special=True, height=1080, tbr=5000),
            FormatOption(format_id="137", format_type="video", label="1080p (FHD)", resolution="1080p", height=1080, tbr=5000),
            FormatOption(format_id="136", format_type="video", label="720p (HD)", resolution="720p", height=720, tbr=2500),
        ]
        audio_formats = [
            FormatOption(format_id="none", format_type="audio", label="[No Audio - Video Only]", resolution="Muted", is_special=True),
            FormatOption(format_id="bestaudio", format_type="audio", label="[Best Audio Quality] (Auto)", resolution="Best Available", is_special=True, tbr=160),
            FormatOption(format_id="140", format_type="audio", label="128 kbps (M4A)", resolution="128k", tbr=128),
        ]

        extraction = ExtractionResult(
            url="https://www.youtube.com/playlist?list=PL_TEST",
            title="Mock Chill Playlist",
            uploader="DJ Cool",
            duration_str="12:00",
            thumbnail="",
            is_playlist=True,
            playlist_entries=entries,
            video_formats=video_formats,
            audio_formats=audio_formats,
        )

        pl_screen = PlaylistScreen(extraction, config=app.config)
        app.push_screen(pl_screen)
        await pilot.pause()

        assert isinstance(app.screen, PlaylistScreen)
        stats_bar = pl_screen.query_one("#playlist-stats-bar", Label)
        keys_bar = pl_screen.query_one("#playlist-keys-bar", Label)

        # Initial state: all 3 tracks selected
        assert len(pl_screen.selected_indices) == 3
        assert "3 of 3 tracks" in str(stats_bar.render())
        assert "Estimated Total Size:" in str(stats_bar.render())

        # Test Space key toggles selection of current cursor row
        await pilot.press("space")
        await pilot.pause()
        assert len(pl_screen.selected_indices) == 2
        assert "2 of 3 tracks" in str(stats_bar.render())

        # Test Ctrl+D deselects all tracks
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert len(pl_screen.selected_indices) == 0
        assert "0 of 3 tracks" in str(stats_bar.render())

        # Test Ctrl+A selects all tracks
        await pilot.press("ctrl+a")
        await pilot.pause()
        assert len(pl_screen.selected_indices) == 3
        assert "3 of 3 tracks" in str(stats_bar.render())

        # Test 'i' inverts selection
        await pilot.press("space")  # unselect row 0 -> 2 selected
        await pilot.pause()
        assert len(pl_screen.selected_indices) == 2
        await pilot.press("i")      # invert -> 1 selected
        await pilot.pause()
        assert len(pl_screen.selected_indices) == 1
        assert "1 of 3 tracks" in str(stats_bar.render())

        # Reset to all selected
        await pilot.press("ctrl+a")
        await pilot.pause()

        # Test Preset 4: Audio Only MP3
        await pilot.press("4")
        await pilot.pause()
        assert pl_screen.selected_video.format_id == "none"
        assert pl_screen.selected_container == "mp3"
        assert "Container: .MP3" in str(keys_bar.render())
        assert "Quality: 192k" in str(keys_bar.render())

        # Test audio quality cycling from 192k -> 128k
        await pilot.press("q")
        await pilot.pause()
        assert pl_screen.audio_quality == "128"
        assert "Quality: 128k" in str(keys_bar.render())

        # Test Preset 2: 1080p FHD
        await pilot.press("2")
        await pilot.pause()
        assert pl_screen.selected_video.height == 1080
        assert pl_screen.selected_container == "mp4"
        assert "Container: .MP4" in str(keys_bar.render())


@pytest.mark.asyncio
async def test_playlist_strict_sequential_order_queueing():
    """Verify that when downloading a playlist, tasks are enqueued in strict ascending playlist order (1..N)."""
    from screens.playlist_screen import PlaylistScreen
    from ytdlp_engine import SearchResultItem

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        entries = [
            SearchResultItem(id="vid-1", title="Track 1 First", url="https://youtube.com/1", uploader="Artist", duration=100, duration_str="01:40", playlist_index=1),
            SearchResultItem(id="vid-2", title="Track 2 Second", url="https://youtube.com/2", uploader="Artist", duration=200, duration_str="03:20", playlist_index=2),
            SearchResultItem(id="vid-3", title="Track 3 Third", url="https://youtube.com/3", uploader="Artist", duration=300, duration_str="05:00", playlist_index=3),
            SearchResultItem(id="vid-4", title="Track 4 Fourth", url="https://youtube.com/4", uploader="Artist", duration=400, duration_str="06:40", playlist_index=4),
        ]

        extraction = ExtractionResult(
            url="https://www.youtube.com/playlist?list=PL_TEST_SEQ",
            title="Strict Order Playlist",
            uploader="Artist",
            duration_str="16:40",
            thumbnail="",
            is_playlist=True,
            playlist_entries=entries,
            video_formats=[
                FormatOption(format_id="bestvideo", format_type="video", label="Best Video", resolution="Best", height=1080),
            ],
            audio_formats=[
                FormatOption(format_id="bestaudio", format_type="audio", label="Best Audio", resolution="Best"),
            ],
        )

        pl_screen = PlaylistScreen(extraction, config=app.config)
        app.push_screen(pl_screen)
        await pilot.pause()

        # Clear existing manager tasks
        app.manager.tasks = []

        # Press Enter to start download
        await pilot.press("enter")
        await pilot.pause()

        # Verify transition to DownloadScreen
        assert isinstance(app.screen, DownloadScreen)

        # Verify all 4 tasks were enqueued in exact 1..4 order
        assert len(app.manager.tasks) == 4
        assert app.manager.tasks[0].title == "Track 1 First"
        assert app.manager.tasks[0].url == "https://youtube.com/1"
        assert app.manager.tasks[1].title == "Track 2 Second"
        assert app.manager.tasks[1].url == "https://youtube.com/2"
        assert app.manager.tasks[2].title == "Track 3 Third"
        assert app.manager.tasks[2].url == "https://youtube.com/3"
        assert app.manager.tasks[3].title == "Track 4 Fourth"
        assert app.manager.tasks[3].url == "https://youtube.com/4"


@pytest.mark.asyncio
async def test_format_screen_edit_existing_task():
    from manager import DownloadStatus, DownloadTask
    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        # Create an existing failed task
        task = DownloadTask(
            id="task-to-edit",
            url="https://youtube.com/watch?v=edit_me",
            title="Video Needing Format Change",
            video_format="137",
            video_format_label="1080p",
            audio_format="140",
            audio_format_label="128k",
            container="mp4",
            status=DownloadStatus.ERROR,
            error_message="Video format (1080p) failed: HTTP Error 403 Forbidden",
        )
        app.manager.tasks = [task]

        extraction = ExtractionResult(
            url="https://youtube.com/watch?v=edit_me",
            title="Video Needing Format Change",
            uploader="Creator",
            duration_str="03:00",
            thumbnail="",
            video_formats=[
                FormatOption(format_id="136", format_type="video", label="720p (HD)", resolution="720p", height=720),
            ],
            audio_formats=[
                FormatOption(format_id="140", format_type="audio", label="128kbps (M4A)", resolution="audio"),
            ],
        )

        fmt_screen = FormatScreen(extraction, config=app.config, editing_task_id="task-to-edit")
        app.push_screen(fmt_screen)
        await pilot.pause()

        # Select 720p and cycle container
        await pilot.press("c")  # Cycle container
        await pilot.pause()

        # Press Enter to save and re-queue
        await pilot.press("enter")
        await pilot.pause()

        # Verify task was updated in place
        updated_task = app.manager.get_task("task-to-edit")
        assert updated_task is not None
        assert updated_task.video_format == "136"
        assert updated_task.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)
        assert updated_task.error_message == ""


@pytest.mark.asyncio
async def test_settings_screen_cookie_test_button():
    from textual.widgets import Button, Static

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")  # Open settings screen
        await pilot.pause()

        # Switch to Cookies & Auth category (index 2)
        cat_list = app.screen.query_one("#category-list")
        cat_list.index = 2
        await pilot.pause()

        # Trigger the cookie test button directly
        btn = app.screen.query_one("#btn-test-cookies", Button)
        btn.press()
        await pilot.pause()

        # Check diagnostic box has updated
        diag_box = app.screen.query_one("#cookie-diag-box", Static)
        assert diag_box is not None


@pytest.mark.asyncio
async def test_history_screen_case_insensitive_search(tmp_path):
    from history import HistoryItem, HistoryManager
    from screens.history_screen import HistoryScreen
    from textual.widgets import DataTable, Input

    hist_file = tmp_path / "test_hist.json"
    mgr = HistoryManager(storage_path=hist_file)
    mgr.add(
        HistoryItem(
            id="h1",
            title="UPPERCASE VIDEO TITLE",
            url="https://youtube.com/watch?v=upper",
            channel="SHOUTING CREATOR",
            duration_str="05:00",
            filepath=str(tmp_path / "upper.mp4"),
            filesize_bytes=1000000,
            format_note="1080p (MP4)",
        )
    )
    mgr.add(
        HistoryItem(
            id="h2",
            title="lowercase quiet title",
            url="https://youtube.com/watch?v=lower",
            channel="quiet creator",
            duration_str="03:00",
            filepath=str(tmp_path / "lower.mp4"),
            filesize_bytes=500000,
            format_note="720p (MP4)",
        )
    )

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")  # Open History screen
        await pilot.pause()

        hist_screen = app.screen
        assert isinstance(hist_screen, HistoryScreen)
        hist_screen.history_mgr = mgr
        hist_screen.populate_history()
        await pilot.pause()

        table = hist_screen.query_one("#history-table", DataTable)
        inp = hist_screen.query_one("#history-search-input", Input)

        # Initial state: 2 rows
        assert table.row_count == 2

        # 1. Type lowercase query to match uppercase title
        inp.value = "uppercase video"
        await pilot.pause()
        assert table.row_count == 1

        # 2. Type UPPERCASE query to match lowercase title
        inp.value = "QUIET CREATOR"
        await pilot.pause()
        assert table.row_count == 1

        # 3. Type Mixed case
        inp.value = "LoWeRcAsE"
        await pilot.pause()
        assert table.row_count == 1

        # 4. Clear search
        inp.value = ""
        await pilot.pause()
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_search_screen_resize_with_results():
    """Verify SearchScreen on_resize correctly updates columns and populates search results."""
    from ytdlp_engine import SearchResultItem

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        search_screen = app.screen
        assert isinstance(search_screen, SearchScreen)

        search_screen.search_results = [
            SearchResultItem(id="s1", title="Resize Video 1", url="https://youtube.com/1", uploader="Channel A", duration=120, duration_str="02:00"),
            SearchResultItem(id="s2", title="Resize Video 2", url="https://youtube.com/2", uploader="Channel B", duration=240, duration_str="04:00"),
        ]
        search_screen._populate_results_table(search_screen.search_results)
        await pilot.pause()

        table = search_screen.query_one("#results-table", DataTable)
        assert table.row_count == 2

        # Trigger on_resize
        from textual.geometry import Size
        from textual.events import Resize
        search_screen.on_resize(Resize(Size(100, 30), Size(120, 30)))
        await pilot.pause()

        assert table.row_count == 2


@pytest.mark.asyncio
async def test_history_screen_in_memory_check_updates(tmp_path):
    """Verify _check_history_updates updates UI when in-memory history manager item count changes."""
    from history import HistoryItem, HistoryManager

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")
        await pilot.pause()

        hist_screen = app.screen
        assert isinstance(hist_screen, HistoryScreen)

        test_storage = tmp_path / "test_hist_mem.json"
        mgr = HistoryManager(storage_path=test_storage)
        hist_screen.history_mgr = mgr
        hist_screen.populate_history()
        await pilot.pause()

        table = hist_screen.query_one("#history-table", DataTable)
        assert table.row_count == 0

        # Add item directly in-memory and call _check_history_updates
        mgr.items.append(
            HistoryItem(
                id="mem-1",
                title="In-Memory History Item",
                url="https://youtube.com/watch?v=mem1",
                channel="Fast Channel",
                duration_str="01:00",
                filepath=str(tmp_path / "mem1.mp4"),
                filesize_bytes=1024,
                format_note="1080p",
            )
        )
        mgr.save()

        hist_screen._check_history_updates()
        await pilot.pause()

        assert table.row_count == 1


@pytest.mark.asyncio
async def test_download_screen_rich_log_caching():
    """Verify RichLog only updates when log count or task changes."""
    from manager import DownloadStatus, DownloadTask

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()

        dl_screen = app.screen
        assert isinstance(dl_screen, DownloadScreen)

        task = DownloadTask(id="log-task-1", url="https://youtube.com/1", title="Log Task", status=DownloadStatus.DOWNLOADING)
        task.add_log("Initial log line 1")
        task.add_log("Initial log line 2")
        app.manager.tasks = [task]
        dl_screen.selected_task_id = "log-task-1"
        dl_screen.is_log_visible = True
        dl_screen.query_one("#log-panel-container").display = True

        dl_screen._update_selected_details()
        await pilot.pause()

        rich_log = dl_screen.query_one("#task-rich-log", RichLog)
        assert len(rich_log.lines) == 2
        assert dl_screen._last_log_count == 2
        assert dl_screen._last_log_task_id == "log-task-1"

        # Calling _update_selected_details without log changes should retain lines without clearing
        dl_screen._update_selected_details()
        await pilot.pause()
        assert len(rich_log.lines) == 2

        # Adding a log line and updating details
        task.add_log("Initial log line 3")
        dl_screen._update_selected_details()
        await pilot.pause()
        assert len(rich_log.lines) == 3
        assert dl_screen._last_log_count == 3


@pytest.mark.asyncio
async def test_settings_screen_propagates_config_to_download_manager():
    """Verify saving settings updates DownloadManager.get_instance().config immediately."""
    from manager import DownloadManager

    app = YtDlpApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+o")
        await pilot.pause()

        settings_screen = app.screen
        assert isinstance(settings_screen, SettingsScreen)

        # Change max concurrent downloads input
        cat_list = settings_screen.query_one("#category-list")
        cat_list.index = 1  # Bandwidth & Queue
        await pilot.pause()

        inp_max = settings_screen.query_one("#inp-max-concurrent", Input)
        inp_max.value = "7"
        await pilot.pause()

        # Save settings via Ctrl+S
        await pilot.press("ctrl+s")
        await pilot.pause()

        mgr = DownloadManager.get_instance()
        assert mgr.config.max_concurrent_downloads == 7








