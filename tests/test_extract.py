"""Tests for image extraction utility."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from accesspdf.alttext.extract import extract_all_images, extract_image


class TestExtractAllImages:
    def test_finds_images(self, images_pdf: Path) -> None:
        results = extract_all_images(images_pdf)
        assert len(results) == 3

    def test_returns_hash_page_image(self, images_pdf: Path) -> None:
        results = extract_all_images(images_pdf)
        for img_hash, page, img in results:
            assert isinstance(img_hash, str)
            assert len(img_hash) == 32  # md5 hex digest
            assert isinstance(page, int)
            assert page >= 1
            assert isinstance(img, Image.Image)

    def test_deduplicates(self, images_pdf: Path) -> None:
        results = extract_all_images(images_pdf)
        hashes = [h for h, _, _ in results]
        assert len(hashes) == len(set(hashes))

    def test_no_images_in_simple(self, simple_pdf: Path) -> None:
        results = extract_all_images(simple_pdf)
        assert len(results) == 0


class TestExtractImage:
    def test_finds_by_hash(self, images_pdf: Path) -> None:
        all_images = extract_all_images(images_pdf)
        assert len(all_images) > 0

        target_hash = all_images[0][0]
        img = extract_image(images_pdf, target_hash)
        assert img is not None
        assert isinstance(img, Image.Image)

    def test_returns_none_for_bad_hash(self, images_pdf: Path) -> None:
        img = extract_image(images_pdf, "0000000000000000000000000000dead")
        assert img is None

    def test_image_dimensions_match(self, images_pdf: Path) -> None:
        all_images = extract_all_images(images_pdf)
        for img_hash, _, img_from_all in all_images:
            img_single = extract_image(images_pdf, img_hash)
            assert img_single is not None
            assert img_single.size == img_from_all.size
