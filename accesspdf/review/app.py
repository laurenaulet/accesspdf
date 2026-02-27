"""Textual TUI app for reviewing and editing alt text."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header

from accesspdf.alttext.extract import extract_all_images
from accesspdf.alttext.sidecar import AltTextEntry, SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus
from accesspdf.review.renderer import image_dimensions_text, render_image_plain
from accesspdf.review.widgets import (
    AltTextEditor,
    ImagePreview,
    InfoPanel,
    NavigationBar,
    StatusSelector,
)

logger = logging.getLogger(__name__)


class ReviewApp(App):
    """TUI for reviewing and approving alt text for images in a PDF."""

    TITLE = "AccessPDF Review"

    CSS = """
    Screen {
        layout: vertical;
    }
    VerticalScroll {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("n", "next_image", "Next"),
        Binding("p", "prev_image", "Previous"),
        Binding("a", "approve", "Approve"),
        Binding("d", "mark_decorative", "Decorative"),
        Binding("ctrl+s", "save", "Save"),
        Binding("q", "save_and_exit", "Save & Exit"),
    ]

    def __init__(
        self,
        pdf_path: Path,
        sidecar: SidecarFile,
        sidecar_path: Path,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.pdf_path = pdf_path
        self.sidecar = sidecar
        self.sidecar_path = sidecar_path
        self.current_index = 0
        self.images: dict[str, Image.Image] = {}
        self._dirty = False

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield ImagePreview(id="image-preview")
            yield InfoPanel(id="info-panel")
            yield AltTextEditor(id="alt-editor")
            yield StatusSelector(id="status-selector")
        yield NavigationBar(id="nav-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Load images and show the first one."""
        self.sub_title = self.pdf_path.name
        self._load_images()
        self._show_current()

    def _load_images(self) -> None:
        """Extract images from the PDF and match to sidecar entries."""
        try:
            extracted = extract_all_images(self.pdf_path)
            for img_hash, _page, img in extracted:
                self.images[img_hash] = img
        except Exception:
            logger.warning("Failed to extract images", exc_info=True)

    @property
    def entries(self) -> list[AltTextEntry]:
        return self.sidecar.images

    @property
    def current_entry(self) -> AltTextEntry | None:
        if not self.entries:
            return None
        if 0 <= self.current_index < len(self.entries):
            return self.entries[self.current_index]
        return None

    def _save_current_edits(self) -> None:
        """Save edits from the UI back to the current sidecar entry."""
        entry = self.current_entry
        if entry is None:
            return

        editor = self.query_one("#alt-editor", AltTextEditor)
        status_sel = self.query_one("#status-selector", StatusSelector)

        entry.alt_text = editor.value
        status_str = status_sel.get_status()
        entry.status = AltTextStatus(status_str)
        self._dirty = True

    def _show_current(self) -> None:
        """Display the current image entry in the UI."""
        entry = self.current_entry
        preview = self.query_one("#image-preview", ImagePreview)
        info = self.query_one("#info-panel", InfoPanel)
        editor = self.query_one("#alt-editor", AltTextEditor)
        status_sel = self.query_one("#status-selector", StatusSelector)
        nav = self.query_one("#nav-bar", NavigationBar)

        if entry is None:
            preview.preview_text = "[No images found in this PDF]"
            preview.meta_text = ""
            info.caption = ""
            info.ai_draft = ""
            editor.value = ""
            nav.progress = "0 / 0"
            return

        # Update progress
        reviewed = sum(1 for e in self.entries if e.status != AltTextStatus.NEEDS_REVIEW)
        nav.progress = f"{reviewed} / {len(self.entries)} reviewed  |  Image {self.current_index + 1} of {len(self.entries)}"

        # Render image preview
        pil_image = self.images.get(entry.hash)
        if pil_image is not None:
            preview.preview_text = render_image_plain(pil_image, max_width=60, max_height=12)
            meta = image_dimensions_text(pil_image.width, pil_image.height, entry.page, entry.id)
        else:
            preview.preview_text = "[Image not available for preview]"
            meta = image_dimensions_text(0, 0, entry.page, entry.id)
        preview.meta_text = meta

        # Update info panel
        info.caption = entry.caption
        info.ai_draft = entry.ai_draft

        # Update editor
        editor.value = entry.alt_text

        # Update status selector
        status_sel.set_status(entry.status.value)

    def action_next_image(self) -> None:
        """Move to the next image."""
        if not self.entries:
            return
        self._save_current_edits()
        self.current_index = min(self.current_index + 1, len(self.entries) - 1)
        self._show_current()

    def action_prev_image(self) -> None:
        """Move to the previous image."""
        if not self.entries:
            return
        self._save_current_edits()
        self.current_index = max(self.current_index - 1, 0)
        self._show_current()

    def action_approve(self) -> None:
        """Set the current entry status to approved."""
        entry = self.current_entry
        if entry is None:
            return
        self._save_current_edits()
        entry.status = AltTextStatus.APPROVED
        self._dirty = True
        self._show_current()

    def action_mark_decorative(self) -> None:
        """Set the current entry status to decorative."""
        entry = self.current_entry
        if entry is None:
            return
        self._save_current_edits()
        entry.status = AltTextStatus.DECORATIVE
        entry.alt_text = ""
        self._dirty = True
        self._show_current()

    def action_save(self) -> None:
        """Save the sidecar to disk."""
        self._save_current_edits()
        SidecarManager.save(self.sidecar, self.sidecar_path)
        self._dirty = False
        self.notify("Sidecar saved.")

    def action_save_and_exit(self) -> None:
        """Save and exit the app."""
        self._save_current_edits()
        SidecarManager.save(self.sidecar, self.sidecar_path)
        self._dirty = False
        self.exit()

    def on_button_pressed(self, event: object) -> None:
        """Handle button presses in the navigation bar."""
        # Textual Button.Pressed has a button attribute
        button = getattr(event, "button", None)
        if button is None:
            return
        button_id = getattr(button, "id", "")
        if button_id == "btn-prev":
            self.action_prev_image()
        elif button_id == "btn-next":
            self.action_next_image()
        elif button_id == "btn-approve":
            self.action_approve()
        elif button_id == "btn-decorative":
            self.action_mark_decorative()
        elif button_id == "btn-save-exit":
            self.action_save_and_exit()
