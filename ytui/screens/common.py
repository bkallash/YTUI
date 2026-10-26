"""Helpers shared by screens."""

from typing import Iterable

CELL_PADDING = 1  # DataTable default, applied on both sides of every column
SCROLLBAR_WIDTH = 2


def flexible_width(total_width: int, fixed_widths: Iterable[int], column_count: int, extra: int = 0) -> int:
    """Width left for flexible columns after fixed columns, cell padding and the scrollbar."""
    return total_width - sum(fixed_widths) - column_count * 2 * CELL_PADDING - SCROLLBAR_WIDTH - extra
