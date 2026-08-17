"""Unit tests for ytdlp_engine module."""

from config import AppConfig
from ytdlp_engine import FormatOption, YtDlpEngine, format_bytes, format_duration, is_url


def test_url_detection():
    assert is_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert is_url("http://youtu.be/dQw4w9WgXcQ") is True
    assert is_url("www.twitch.tv/streamer") is True
    assert is_url("lofi hip hop beats") is False
    assert is_url("taylor swift concert") is False


def test_format_helpers():
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "1:01:05"
    assert format_duration(None) == "--:--"

    assert "MB" in format_bytes(10 * 1024 * 1024)
    assert format_bytes(None) == "N/A"


def test_parse_formats():
    dummy_raw_formats = [
        {"format_id": "137", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "fps": 60, "ext": "mp4", "filesize": 50000000},
        {"format_id": "136", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720, "fps": 30, "ext": "mp4", "filesize": 25000000},
        {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128, "ext": "m4a", "filesize": 4000000},
        {"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 160, "ext": "webm", "filesize": 5000000},
    ]

    video_opts, audio_opts = YtDlpEngine._parse_formats(dummy_raw_formats)

    # Check special "No Video" and "No Audio" options
    assert any(opt.format_id == "none" and opt.format_type == "video" for opt in video_opts)
    assert any(opt.format_id == "none" and opt.format_type == "audio" for opt in audio_opts)

    # Check parsed video formats
    assert any(opt.height == 1080 for opt in video_opts)
    assert any(opt.height == 720 for opt in video_opts)

    # Check parsed audio formats
    assert any("160 kbps" in opt.label or "128 kbps" in opt.label for opt in audio_opts)


def test_build_download_options_resilience_and_settings():
    config = AppConfig(
        download_dir="~/TestDownloads",
        rate_limit="1M",
        retries=15,
        fragment_retries=15,
        continuedl=True,
        download_subtitles=True,
        subtitle_mode="embed",
        subtitle_langs="en,es",
        download_thumbnail=True,
        thumbnail_mode="embed",
        embed_metadata=True,
    )

    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="mp4",
    )

    assert opts["format"] == "137+140/best"
    assert opts["ratelimit"] == "1M"
    assert opts["retries"] == 15
    assert opts["fragment_retries"] == 15
    assert opts["continuedl"] is True
    assert opts["ignoreerrors"] is False
    assert opts["remote_components"] == ["ejs:github"]
    assert "youtube" in opts["extractor_args"]
    assert opts["writesubtitles"] is True
    assert opts["subtitleslangs"] == ["en", "es"]
    assert opts["writethumbnail"] is True

    pp_keys = [pp.get("key") for pp in opts.get("postprocessors", [])]
    assert "FFmpegThumbnailsConvertor" in pp_keys
    assert "FFmpegMetadata" in pp_keys
    assert "FFmpegEmbedSubtitle" in pp_keys
    assert "EmbedThumbnail" in pp_keys
    assert "FFmpegVideoRemuxer" in pp_keys


def test_incompatible_webm_streams_are_converted():
    config = AppConfig(download_dir="~/TestDownloads")
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="webm",
        video_codec="avc1",
        audio_codec="mp4a",
    )

    assert opts["merge_output_format"] == "mkv"
    pp_keys = [pp.get("key") for pp in opts.get("postprocessors", [])]
    assert "FFmpegVideoConvertor" in pp_keys


def test_both_subtitle_mode_keeps_external_file():
    config = AppConfig(download_dir="~/TestDownloads", download_subtitles=True, subtitle_mode="both")
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="mp4",
    )

    embed_pp = next(pp for pp in opts["postprocessors"] if pp.get("key") == "FFmpegEmbedSubtitle")
    assert embed_pp["already_have_subtitle"] is True


def test_auto_subtitles_include_generated_language_variants():
    config = AppConfig(
        download_dir="~/TestDownloads",
        download_subtitles=True,
        auto_generated_subtitles=True,
        subtitle_mode="embed",
        subtitle_langs="en,es",
    )
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="mp4",
    )

    assert opts["writeautomaticsub"] is True
    assert opts["subtitleslangs"] == [r"en(?:[-_].*)?", r"es(?:[-_].*)?"]


def test_build_download_options_audio_only():
    config = AppConfig(download_dir="~/TestDownloads")
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="none",
        audio_format_id="140",
        target_container="mp3",
        audio_quality="320",
    )

    assert opts["format"] == "140"
    assert "merge_output_format" not in opts
    pp_list = opts.get("postprocessors", [])
    extract_pp = next((pp for pp in pp_list if pp.get("key") == "FFmpegExtractAudio"), None)
    assert extract_pp is not None
    assert extract_pp["preferredcodec"] == "mp3"
    assert extract_pp["preferredquality"] == "320"


def test_sponsorblock_removal_postprocessors_are_configured():
    config = AppConfig(
        download_dir="~/TestDownloads",
        remove_sponsor_segments=True,
        sponsorblock_categories="sponsor,selfpromo",
    )
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="mp4",
    )

    postprocessors = opts["postprocessors"]
    sponsorblock_pp = next(pp for pp in postprocessors if pp.get("key") == "SponsorBlock")
    modify_chapters_pp = next(pp for pp in postprocessors if pp.get("key") == "ModifyChapters")

    assert sponsorblock_pp["categories"] == ["sponsor", "selfpromo"]
    assert sponsorblock_pp["when"] == "after_filter"
    assert modify_chapters_pp["remove_sponsor_segments"] == ["sponsor", "selfpromo"]
    assert postprocessors.index(sponsorblock_pp) < postprocessors.index(modify_chapters_pp)


def test_thumbnail_is_embedded_after_sponsorblock_cutting():
    config = AppConfig(
        download_dir="~/TestDownloads",
        download_thumbnail=True,
        thumbnail_mode="embed",
        remove_sponsor_segments=True,
    )
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="137",
        audio_format_id="140",
        target_container="mp4",
    )

    postprocessors = opts["postprocessors"]
    modify_chapters_pp = next(pp for pp in postprocessors if pp.get("key") == "ModifyChapters")
    embed_thumbnail_pp = next(pp for pp in postprocessors if pp.get("key") == "EmbedThumbnail")

    assert embed_thumbnail_pp["already_have_thumbnail"] is False
    assert postprocessors.index(modify_chapters_pp) < postprocessors.index(embed_thumbnail_pp)


def test_resolve_output_filepath(tmp_path):
    f = tmp_path / "song.mp3"
    f.write_text("dummy")

    # When exact file exists
    assert YtDlpEngine.resolve_output_filepath(str(f), container="mp3", is_audio_only=True) == str(f)

    # When stem with different extension exists
    dummy_orig = tmp_path / "song.webm"
    assert YtDlpEngine.resolve_output_filepath(str(dummy_orig), container="mp3", is_audio_only=True) == str(f)


def test_shorts_detection_and_urls():
    from ytdlp_engine import is_shorts

    # Shorts URLs
    assert is_shorts("https://www.youtube.com/shorts/dQw4w9WgXcQ") is True
    assert is_shorts("https://youtube.com/shorts/3xyz987") is True
    assert is_shorts("http://youtu.be/shorts/abc-123_45") is True

    # Standard video URLs
    assert is_shorts("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is False
    assert is_shorts("https://youtu.be/dQw4w9WgXcQ") is False
    assert is_shorts("https://vimeo.com/123456") is False

    # Metadata dict detection
    assert is_shorts("https://youtube.com/watch?v=1", info={"is_shorts": True}) is True
    assert is_shorts("https://youtube.com/watch?v=1", info={"webpage_url": "https://www.youtube.com/shorts/1"}) is True
    assert is_shorts("https://youtube.com/watch?v=1", info={"is_shorts": False, "webpage_url": "https://youtube.com/watch?v=1"}) is False


def test_parse_formats_non_youtube_sites():
    # 1. Muxed formats (e.g. Vimeo, Twitter, direct MP4)
    muxed_fmts = [
        {"format_id": "http-1080p", "vcodec": "h264", "acodec": "aac", "height": 1080, "ext": "mp4", "filesize": 30000000},
        {"format_id": "http-720p", "vcodec": "h264", "acodec": "aac", "height": 720, "ext": "mp4", "filesize": 15000000},
    ]
    v_opts, a_opts = YtDlpEngine._parse_formats(muxed_fmts)
    assert any("1080p" in opt.label for opt in v_opts)
    assert any("720p" in opt.label for opt in v_opts)

    # 2. String resolution / format_note without integer height (Reddit, Twitch, HLS)
    res_str_fmts = [
        {"format_id": "source", "vcodec": "avc1", "acodec": "mp4a", "height": None, "resolution": "1080x1920", "ext": "mp4"},
        {"format_id": "chunked", "vcodec": "avc1", "acodec": "mp4a", "height": None, "format_note": "720p60", "ext": "mp4"},
    ]
    v_res, _ = YtDlpEngine._parse_formats(res_str_fmts)
    assert any("1080" in opt.label for opt in v_res)
    assert any("720" in opt.label for opt in v_res)

    # 3. Audio-only sites (SoundCloud, Mixcloud, Bandcamp)
    audio_fmts = [
        {"format_id": "http_mp3", "vcodec": "none", "acodec": "mp3", "abr": 128, "ext": "mp3"},
        {"format_id": "hls_opus", "vcodec": "none", "acodec": "opus", "tbr": 160, "ext": "opus"},
    ]
    _, a_res = YtDlpEngine._parse_formats(audio_fmts)
    assert any("128 kbps" in opt.label for opt in a_res)
    assert any("160 kbps" in opt.label for opt in a_res)

    # 4. Download options generation for non-YouTube muxed format
    config = AppConfig()
    opts = YtDlpEngine.build_download_options(
        config=config,
        video_format_id="http-1080p",
        audio_format_id="bestaudio",
        target_container="mp4",
    )
    assert opts["format"] == "http-1080p+bestaudio/http-1080p/best"


def test_bitrate_and_size_estimation():
    fmt_1080p = FormatOption(format_id="137", format_type="video", label="1080p (FHD)", resolution="1080p", height=1080, tbr=5000)
    fmt_720p = FormatOption(format_id="136", format_type="video", label="720p (HD)", resolution="720p", height=720, tbr=2500)
    fmt_audio_320 = FormatOption(format_id="140", format_type="audio", label="320 kbps [MP3]", resolution="320k", tbr=320)
    fmt_no_video = FormatOption(format_id="none", format_type="video", label="[No Video]", resolution="Audio Only", is_special=True)
    fmt_no_audio = FormatOption(format_id="none", format_type="audio", label="[No Audio]", resolution="Muted", is_special=True)

    # 1. 1080p + 320k audio bitrate test
    v_kbps, a_kbps, tot_kbps = YtDlpEngine.estimate_format_bitrates(fmt_1080p, fmt_audio_320)
    assert v_kbps == 5000.0
    assert a_kbps == 320.0
    assert tot_kbps == 5320.0

    # 2. Audio only mode
    v_kbps, a_kbps, tot_kbps = YtDlpEngine.estimate_format_bitrates(fmt_no_video, fmt_audio_320, audio_quality="320")
    assert v_kbps == 0.0
    assert a_kbps == 320.0
    assert tot_kbps == 320.0

    # 3. Video only mode
    v_kbps, a_kbps, tot_kbps = YtDlpEngine.estimate_format_bitrates(fmt_720p, fmt_no_audio)
    assert v_kbps == 2500.0
    assert a_kbps == 0.0
    assert tot_kbps == 2500.0

    # 4. Item size estimation for 60 seconds of 1080p (5320 kbps)
    # bytes = (5320 * 1000 / 8) * 60 = 665000 * 60 = 39,900,000 bytes (~39.9 MB)
    est_bytes = YtDlpEngine.estimate_item_size(60, fmt_1080p, fmt_audio_320)
    assert 39_000_000 <= est_bytes <= 41_000_000

    # 5. Playlist size estimation across 3 items
    from ytdlp_engine import SearchResultItem
    items = [
        SearchResultItem(id="1", title="Track 1", url="https://youtube.com/1", uploader="Artist", duration=60, duration_str="01:00", playlist_index=1),
        SearchResultItem(id="2", title="Track 2", url="https://youtube.com/2", uploader="Artist", duration=120, duration_str="02:00", playlist_index=2),
        SearchResultItem(id="3", title="Track 3", url="https://youtube.com/3", uploader="Artist", duration=180, duration_str="03:00", playlist_index=3),
    ]

    total_bytes, total_secs = YtDlpEngine.estimate_playlist_size(items, fmt_1080p, fmt_audio_320)
    assert total_secs == 360  # 60 + 120 + 180
    assert total_bytes > 0
    # Expected bytes for 360 seconds at 5320 kbps = ~239.4 MB
    assert 235_000_000 <= total_bytes <= 245_000_000


def test_playlist_fallback_formats():
    v_opts, a_opts = YtDlpEngine._get_playlist_fallback_formats()
    assert any(opt.format_id == "none" for opt in v_opts)
    assert any("2160p" in opt.label or "4K" in opt.label for opt in v_opts)
    assert any("1080p" in opt.label for opt in v_opts)
    assert any("720p" in opt.label for opt in v_opts)
    assert any("480p" in opt.label for opt in v_opts)
    assert any("320 kbps" in opt.label for opt in a_opts)
    assert any("128 kbps" in opt.label for opt in a_opts)


def test_cookie_setup_none():
    res = YtDlpEngine.test_cookie_setup(browser="none")
    assert res["success"] is True
    assert res["count"] == 0
    assert "No cookies" in res["message"]


def test_cookie_setup_file_not_found():
    res = YtDlpEngine.test_cookie_setup(cookies_file="/path/to/non_existent_cookies.txt")
    assert res["success"] is False
    assert res["error_type"] == "file_not_found"
    assert "not found" in res["message"].lower()


def test_cookie_setup_valid_file(tmp_path):
    cookie_file = tmp_path / "valid_cookies.txt"
    # Write a mock Netscape cookies.txt file
    content = (
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tLOGIN_INFO\taf6834jh\n"
        ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tsid_value\n"
        ".google.com\tTRUE\t/\tTRUE\t2147483647\tHSID\thsid_value\n"
    )
    cookie_file.write_text(content, encoding="utf-8")

    res = YtDlpEngine.test_cookie_setup(cookies_file=str(cookie_file))
    assert res["success"] is True
    assert res["count"] >= 3
    assert res["has_youtube_auth"] is True
    assert "Active YouTube login" in res["recommendation"]


def test_cookie_setup_browser_errors(monkeypatch):
    import yt_dlp

    # Test Chrome locked database simulation
    def mock_locked_ydl(*args, **kwargs):
        raise yt_dlp.utils.DownloadError("Could not copy Chrome cookie database: [Errno 13] Permission denied")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", mock_locked_ydl)
    res = YtDlpEngine.test_cookie_setup(browser="chrome")
    assert res["success"] is False
    assert res["error_type"] == "browser_locked"
    assert "locking its cookie database" in res["message"]
    assert "Get cookies.txt LOCALLY" in res["recommendation"]


def test_extract_audio_quality_and_containers():
    from ytdlp_engine import (
        extract_audio_container_from_option,
        extract_audio_quality_from_option,
        extract_video_container_from_option,
    )

    # 1. Video containers
    v_mp4 = FormatOption(format_id="137", format_type="video", label="1080p [MP4]", resolution="1080p", ext="mp4")
    v_webm = FormatOption(format_id="248", format_type="video", label="1080p [WEBM]", resolution="1080p", ext="webm")
    v_mkv = FormatOption(format_id="1", format_type="video", label="1080p [MKV]", resolution="1080p", ext="mkv")
    v_none = FormatOption(format_id="none", format_type="video", label="No Video", resolution="None")

    assert extract_video_container_from_option(v_mp4) == "mp4"
    assert extract_video_container_from_option(v_webm) == "webm"
    assert extract_video_container_from_option(v_mkv) == "mkv"
    assert extract_video_container_from_option(v_none) == "mp4"
    assert extract_video_container_from_option(None) == "mp4"

    # 2. Audio containers
    a_m4a = FormatOption(format_id="140", format_type="audio", label="128 kbps [M4A]", resolution="128k", ext="m4a", tbr=128)
    a_opus = FormatOption(format_id="251", format_type="audio", label="160 kbps [WEBM] (OPUS)", resolution="160k", ext="webm", acodec="opus", tbr=160)
    a_mp3 = FormatOption(format_id="1", format_type="audio", label="320 kbps [MP3]", resolution="320k", ext="mp3", tbr=320)
    a_flac = FormatOption(format_id="2", format_type="audio", label="Lossless [FLAC]", resolution="lossless", ext="flac")

    assert extract_audio_container_from_option(a_m4a) == "m4a"
    assert extract_audio_container_from_option(a_opus) == "opus"
    assert extract_audio_container_from_option(a_mp3) == "mp3"
    assert extract_audio_container_from_option(a_flac) == "flac"
    assert extract_audio_container_from_option(None) == "mp3"

    # 3. Audio qualities
    assert extract_audio_quality_from_option(a_m4a) == "128"
    assert extract_audio_quality_from_option(a_opus) == "192"  # 160k maps to 192k standard
    assert extract_audio_quality_from_option(a_mp3) == "320"
    assert extract_audio_quality_from_option(None) == "256"

