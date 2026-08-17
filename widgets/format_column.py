"""Format column item and list widgets for side-by-side stream selection."""

from typing import Callable, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static

from rtl_utils import fix_rtl
from ytdlp_engine import FormatOption


class FormatItemWidget(ListItem):
    """An individual selectable format row in a format column."""

    def __init__(self, option: FormatOption, is_selected: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.option = option
        self.is_selected = is_selected

    def compose(self) -> ComposeResult:
        check = "[●]" if self.is_selected else "[ ]"
        t = Text()
        label_text = fix_rtl(self.option.label)
        if self.is_selected:
            t.append(f"{check} ", style="bold green")
            t.append(label_text, style="bold")
        else:
            t.append(f"{check} ", style="dim")
            t.append(label_text, style="none")

        if self.option.note and not self.option.is_special:
            t.append(f"  ({fix_rtl(self.option.note)})", style="dim")

        yield Label(t, classes="format-item-line")

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        # Update label content in-place instead of rebuilding DOM
        check = "[●]" if selected else "[ ]"
        t = Text()
        label_text = fix_rtl(self.option.label)
        if selected:
            t.append(f"{check} ", style="bold green")
            t.append(label_text, style="bold")
        else:
            t.append(f"{check} ", style="dim")
            t.append(label_text, style="none")
        if self.option.note and not self.option.is_special:
            t.append(f"  ({fix_rtl(self.option.note)})", style="dim")
        try:
            label = self.query_one(".format-item-line", Label)
            label.update(t)
        except Exception:
            pass


class FormatColumnView(Vertical):
    """A vertical column containing a title and a scrollable list of format choices."""

    class SelectedChanged(Message):
        """Posted when a format selection in this column changes."""

        def __init__(self, column_type: str, option: FormatOption, is_double_enter: bool = False):
            super().__init__()
            self.column_type = column_type  # 'video' or 'audio'
            self.option = option
            self.is_double_enter = is_double_enter

    def __init__(self, title: str, column_type: str, options: List[FormatOption], default_idx: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.column_title = title
        self.column_type = column_type
        self.options = options
        self.selected_idx = default_idx if 0 <= default_idx < len(options) else 0

    def compose(self) -> ComposeResult:
        yield Label(f"[bold]{self.column_title}[/]", classes="column-header")
        with ListView(id=f"list-{self.column_type}", classes="format-list-view", initial_index=self.selected_idx):
            for i, opt in enumerate(self.options):
                yield FormatItemWidget(option=opt, is_selected=(i == self.selected_idx), id=f"opt-{self.column_type}-{i}")

    def on_key(self, event) -> None:
        if event.key == "enter":
            if hasattr(self.screen, "action_start_download"):
                self.screen.action_start_download()
                event.prevent_default()
                event.stop()
                return
        if event.key in ("left", "right", "h", "l"):
            if event.key in ("left", "h") and hasattr(self.screen, "action_focus_video"):
                self.screen.action_focus_video()
                event.prevent_default()
                event.stop()
            elif event.key in ("right", "l") and hasattr(self.screen, "action_focus_audio"):
                self.screen.action_focus_audio()
                event.prevent_default()
                event.stop()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, FormatItemWidget):
            list_view = self.query_one(f"#list-{self.column_type}", ListView)
            items = [c for c in list_view.children if isinstance(c, FormatItemWidget)]
            try:
                new_idx = items.index(event.item)
            except ValueError:
                new_idx = self.selected_idx

            for child in items:
                child.set_selected(child == event.item)

            self.selected_idx = new_idx
            self.post_message(self.SelectedChanged(self.column_type, event.item.option, is_double_enter=False))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, FormatItemWidget):
            list_view = self.query_one(f"#list-{self.column_type}", ListView)
            items = [c for c in list_view.children if isinstance(c, FormatItemWidget)]
            try:
                new_idx = items.index(event.item)
            except ValueError:
                new_idx = self.selected_idx

            is_double = (new_idx == self.selected_idx)

            for child in items:
                child.set_selected(child == event.item)

            self.selected_idx = new_idx
            self.post_message(self.SelectedChanged(self.column_type, event.item.option, is_double_enter=is_double))

    def set_selected_index(self, idx: int) -> Optional[FormatOption]:
        """Programmatically select an index and update all child widgets visually."""
        if 0 <= idx < len(self.options):
            self.selected_idx = idx
            try:
                list_view = self.query_one(f"#list-{self.column_type}", ListView)
                items = [c for c in list_view.children if isinstance(c, FormatItemWidget)]
                for i, child in enumerate(items):
                    child.set_selected(i == idx)
                list_view.index = idx
            except Exception:
                pass
            return self.options[idx]
        return None

    def get_selected_option(self) -> Optional[FormatOption]:
        if 0 <= self.selected_idx < len(self.options):
            return self.options[self.selected_idx]
        return None
