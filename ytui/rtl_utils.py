"""RTL and Arabic text shaping utility functions for terminal UI rendering."""

import re
from functools import lru_cache
from typing import Optional

from rich.text import Text

RTL_RE = re.compile(
    r"[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB1D-\uFB4F\uFB50-\uFDFF\uFE70-\uFEFF]"
)

# Reshaper configuration: clean presentation forms without overlapping diacritics / tatweel gaps
_RESHAPER_CONFIG = {
    "delete_harakat": True,
    "delete_tatweel": True,
    "support_ligatures": True,
    "support_zwj": True,
    "use_unshaped_instead_of_isolated": False,
}


@lru_cache(maxsize=1)
def _shaping():
    """Load the shaping libraries on first RTL text, so other users never pay their import cost."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    return arabic_reshaper.ArabicReshaper(configuration=_RESHAPER_CONFIG), get_display


_CURRENT_RTL_MODE = "reshaped_bidi"


def set_rtl_mode(mode: str) -> None:
    """Set active RTL rendering mode: 'reshaped_bidi', 'native_raw', 'bidi_only', or 'disabled'."""
    global _CURRENT_RTL_MODE
    if mode in ("reshaped_bidi", "native_raw", "bidi_only", "disabled"):
        _CURRENT_RTL_MODE = mode


def get_rtl_mode() -> str:
    """Return currently active RTL rendering mode."""
    return _CURRENT_RTL_MODE


@lru_cache(maxsize=2048)
def has_rtl(text: Optional[str]) -> bool:
    """Check whether a string contains RTL (Arabic, Hebrew, Persian, Urdu) characters."""
    if not text or not isinstance(text, str):
        return False
    return bool(RTL_RE.search(text))


@lru_cache(maxsize=2048)
def _fix_rtl_cached(text: str, mode: str) -> str:
    """Internal helper to shape and visually reorder RTL text with LRU caching."""
    if not has_rtl(text):
        return text

    if mode in ("native_raw", "disabled"):
        return text

    reshaper, get_display = _shaping()
    try:
        if mode == "bidi_only":
            return get_display(text)
        return get_display(reshaper.reshape(text))  # default 'reshaped_bidi'
    except Exception:
        return text


def fix_rtl(text: Optional[str], mode: Optional[str] = None) -> str:
    """Format Arabic / RTL text for terminal display according to selected mode.

    Modes:
    - 'reshaped_bidi' (default): Cleans Tashkeel/Tatweel artifacts, shapes glyphs, and applies BiDi visual ordering.
    - 'native_raw': Raw Unicode characters for modern terminals with native DirectWrite/HarfBuzz RTL text shaping.
    - 'bidi_only': Applies Unicode BiDi reordering without presentation form substitution.
    - 'disabled': Returns original text.
    """
    if not text or not isinstance(text, str):
        return text if text is not None else ""

    active_mode = mode or _CURRENT_RTL_MODE
    return _fix_rtl_cached(text, active_mode)


def rtl_truncate(text: Optional[str], max_len: int = 40, suffix: str = "...", mode: Optional[str] = None) -> str:
    """Truncate text cleanly before applying RTL shaping and BiDi reordering.

    Truncating prior to BiDi ensures that the logical start and end of strings
    are preserved rather than having characters chopped backwards.
    """
    if not text or not isinstance(text, str):
        return ""
    s = text.strip()
    if len(s) <= max_len:
        return fix_rtl(s, mode=mode)

    trunc_len = max(1, max_len - len(suffix))
    truncated = s[:trunc_len] + suffix
    return fix_rtl(truncated, mode=mode)


def render_rtl_text(text: Optional[str], style: str = "", mode: Optional[str] = None) -> Text:
    """Return a Rich Text object with RTL-formatted text and optional style."""
    fixed = fix_rtl(text, mode=mode)
    return Text(fixed, style=style) if style else Text(fixed)


def escape_markup(text: str) -> str:
    """Make text literal inside Textual markup.

    textual/rich `escape()` only escape tags that start with a lowercase letter, but Textual's
    parser also treats "[Official Video]" or "[MP4]" as tags and drops them. A backslash only
    matters right before "[", so a trailing one gets a zero-width space to keep it from
    escaping the caller's closing tag.
    """
    escaped = text.replace("[", "\\[")
    return escaped + "\u200b" if escaped.endswith("\\") else escaped


def markup_safe(text: Optional[str], max_len: Optional[int] = None) -> str:
    """RTL-format (and optionally truncate) text for embedding in Textual markup."""
    return escape_markup(rtl_truncate(text, max_len) if max_len else fix_rtl(text))
