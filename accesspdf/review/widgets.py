"""Textual widgets for the alt text review TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Label, RadioButton, RadioSet, Static, TextArea


class ImagePreview(Static):
    """Displays a rendered image preview and metadata."""

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        max-height: 20;
        border: round $accent;
        padding: 0 1;
    }
    """

    preview_text: reactive[str] = reactive("")
    meta_text: reactive[str] = reactive("")

    def render(self) -> str:
        if not self.preview_text:
            return "[No image to display]"
        return self.preview_text + "\n" + self.meta_text


class AltTextEditor(Static):
    """Editable text area for alt text with a label."""

    DEFAULT_CSS = """
    AltTextEditor {
        height: auto;
        padding: 0;
    }
    AltTextEditor Label {
        margin-bottom: 1;
    }
    AltTextEditor TextArea {
        height: 6;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Alt text:")
        yield TextArea(id="alt-text-input")

    @property
    def text_area(self) -> TextArea:
        return self.query_one("#alt-text-input", TextArea)

    @property
    def value(self) -> str:
        return self.text_area.text

    @value.setter
    def value(self, text: str) -> None:
        self.text_area.clear()
        self.text_area.insert(text)


class InfoPanel(Static):
    """Shows caption and AI draft (read-only info)."""

    DEFAULT_CSS = """
    InfoPanel {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    caption: reactive[str] = reactive("")
    ai_draft: reactive[str] = reactive("")

    def render(self) -> str:
        parts = []
        if self.caption:
            parts.append(f"Caption: {self.caption}")
        if self.ai_draft:
            parts.append(f"AI Draft: {self.ai_draft}")
        if not parts:
            parts.append("(No caption or AI draft available)")
        return "\n".join(parts)


class StatusSelector(Static):
    """Radio buttons for alt text status selection."""

    DEFAULT_CSS = """
    StatusSelector {
        height: auto;
        padding: 0 1;
    }
    StatusSelector RadioSet {
        layout: horizontal;
        height: 3;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Status:")
        with RadioSet(id="status-radio"):
            yield RadioButton("Needs Review", id="status-needs-review", value=True)
            yield RadioButton("Approved", id="status-approved")
            yield RadioButton("Decorative", id="status-decorative")

    @property
    def radio_set(self) -> RadioSet:
        return self.query_one("#status-radio", RadioSet)

    def set_status(self, status: str) -> None:
        """Set the selected status radio button."""
        mapping = {
            "needs_review": "status-needs-review",
            "approved": "status-approved",
            "decorative": "status-decorative",
        }
        target_id = mapping.get(status, "status-needs-review")
        for btn in self.radio_set.query(RadioButton):
            if btn.id == target_id:
                btn.value = True
                break

    def get_status(self) -> str:
        """Get the currently selected status value."""
        for btn in self.radio_set.query(RadioButton):
            if btn.value:
                mapping = {
                    "status-needs-review": "needs_review",
                    "status-approved": "approved",
                    "status-decorative": "decorative",
                }
                return mapping.get(btn.id or "", "needs_review")
        return "needs_review"


class NavigationBar(Static):
    """Bottom bar with navigation buttons and progress."""

    DEFAULT_CSS = """
    NavigationBar {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }
    NavigationBar Horizontal {
        height: 3;
        align: center middle;
    }
    NavigationBar Button {
        margin: 0 1;
    }
    NavigationBar #progress-label {
        content-align: center middle;
        width: auto;
        margin: 0 2;
    }
    """

    progress: reactive[str] = reactive("0 / 0")

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Button("Prev (p)", id="btn-prev", variant="default")
            yield Button("Next (n)", id="btn-next", variant="default")
            yield Label(self.progress, id="progress-label")
            yield Button("Approve (a)", id="btn-approve", variant="success")
            yield Button("Decorative (d)", id="btn-decorative", variant="warning")
            yield Button("Save & Exit (q)", id="btn-save-exit", variant="primary")

    def watch_progress(self, value: str) -> None:
        try:
            self.query_one("#progress-label", Label).update(value)
        except Exception:
            pass
