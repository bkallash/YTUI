"""RTL and Arabic text shaping utility functions for terminal UI rendering."""

from functools import lru_cache
from typing import Optional
import arabic_reshaper
from bidi.algorithm import get_display
from rich.text import Text

# Reshaper configuration: clean presentation forms without overlapping diacritics / tatweel gaps
_RESHAPER_CONFIG = {
    "delete_harakat": True,
    "delete_tatweel": True,
    "support_ligatures": True,
    "support_zwj": True,
    "use_unshaped_instead_of_isolated": False,
}
_reshaper = arabic_reshaper.ArabicReshaper(configuration=_RESHAPER_CONFIG)

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
    return any(
        "\u0590" <= ch <= "\u05FF"  # Hebrew
        or "\u0600" <= ch <= "\u06FF"  # Arabic
        or "\u0750" <= ch <= "\u077F"  # Arabic Supplement
        or "\u08A0" <= ch <= "\u08FF"  # Arabic Extended-A
        or "\uFB1D" <= ch <= "\uFB4F"  # Hebrew Presentation Forms
        or "\uFB50" <= ch <= "\uFDFF"  # Arabic Presentation Forms-A
        or "\uFE70" <= ch <= "\uFEFF"  # Arabic Presentation Forms-B
        for ch in text
    )


@lru_cache(maxsize=2048)
def _fix_rtl_cached(text: str, mode: str) -> str:
    """Internal helper to shape and visually reorder RTL text with LRU caching."""
    if not has_rtl(text):
        return text

    if mode in ("native_raw", "disabled"):
        return text

    if mode == "bidi_only":
        try:
            return get_display(text)
        except Exception:
            return text

    # Default 'reshaped_bidi'
    try:
        reshaped = _reshaper.reshape(text)
        return get_display(reshaped)
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
