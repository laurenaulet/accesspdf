"""Tests for the web UI API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accesspdf.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


class TestWebUI:
    def test_index_returns_html(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "AccessPDF" in resp.text
        assert "text/html" in resp.headers["content-type"]

    def test_upload_rejects_non_pdf(self, client: TestClient, tmp_path: Path) -> None:
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("not a pdf")
        with open(txt_file, "rb") as f:
            resp = client.post("/api/upload", files={"file": ("readme.txt", f, "text/plain")})
        assert resp.status_code == 400

    def test_upload_and_status(self, client: TestClient, simple_pdf: Path) -> None:
        with open(simple_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (simple_pdf.name, f, "application/pdf")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["filename"] == simple_pdf.name
        assert data["error"] is None

        # Fetch status
        job_id = data["job_id"]
        status_resp = client.get(f"/api/job/{job_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["job_id"] == job_id

    def test_upload_with_images(self, client: TestClient, images_pdf: Path) -> None:
        with open(images_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (images_pdf.name, f, "application/pdf")},
            )
        data = resp.json()
        assert data["error"] is None
        assert len(data["images"]) >= 1

        job_id = data["job_id"]

        # Test image endpoint
        first_image = data["images"][0]
        img_resp = client.get(f"/api/job/{job_id}/image/{first_image['image_hash']}")
        assert img_resp.status_code == 200
        assert img_resp.headers["content-type"] == "image/png"
        assert len(img_resp.content) > 0

    def test_save_alt_text(self, client: TestClient, images_pdf: Path) -> None:
        with open(images_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (images_pdf.name, f, "application/pdf")},
            )
        data = resp.json()
        job_id = data["job_id"]
        first_hash = data["images"][0]["image_hash"]

        # Save alt text
        save_resp = client.post(
            f"/api/job/{job_id}/alt-text",
            json=[{"image_hash": first_hash, "alt_text": "A blue rectangle", "status": "approved"}],
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["saved"] == 1

        # Verify it persisted
        status_resp = client.get(f"/api/job/{job_id}")
        img = next(i for i in status_resp.json()["images"] if i["image_hash"] == first_hash)
        assert img["status"] == "approved"
        assert img["alt_text"] == "A blue rectangle"

    def test_inject_and_download(self, client: TestClient, images_pdf: Path) -> None:
        with open(images_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (images_pdf.name, f, "application/pdf")},
            )
        data = resp.json()
        job_id = data["job_id"]

        # Approve all images
        updates = [
            {"image_hash": img["image_hash"], "alt_text": f"Description for {img['id']}", "status": "approved"}
            for img in data["images"]
        ]
        client.post(f"/api/job/{job_id}/alt-text", json=updates)

        # Inject
        inject_resp = client.post(f"/api/job/{job_id}/inject")
        assert inject_resp.status_code == 200
        assert inject_resp.json()["injected"] >= 1

        # Download
        dl_resp = client.get(f"/api/job/{job_id}/download")
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-type"] == "application/pdf"
        assert len(dl_resp.content) > 0

    def test_missing_job_404(self, client: TestClient) -> None:
        resp = client.get("/api/job/nonexistent")
        assert resp.status_code == 404

    def test_missing_image_404(self, client: TestClient, simple_pdf: Path) -> None:
        with open(simple_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (simple_pdf.name, f, "application/pdf")},
            )
        job_id = resp.json()["job_id"]
        img_resp = client.get(f"/api/job/{job_id}/image/deadbeef")
        assert img_resp.status_code == 404

    def test_download_no_images_pdf(self, client: TestClient, simple_pdf: Path) -> None:
        """A PDF with no images still gets structural fixes and is downloadable."""
        with open(simple_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (simple_pdf.name, f, "application/pdf")},
            )
        data = resp.json()
        job_id = data["job_id"]
        assert len(data["images"]) == 0

        dl_resp = client.get(f"/api/job/{job_id}/download")
        assert dl_resp.status_code == 200
        assert len(dl_resp.content) > 0

    def test_providers_endpoint(self, client: TestClient) -> None:
        resp = client.get("/api/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        names = [p["name"] for p in data["providers"]]
        assert "ollama" in names
        assert "noop" in names

    def test_generate_with_noop(self, client: TestClient, images_pdf: Path) -> None:
        """Generate endpoint with noop provider returns 0 drafts (expected)."""
        with open(images_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (images_pdf.name, f, "application/pdf")},
            )
        data = resp.json()
        job_id = data["job_id"]

        gen_resp = client.post(
            f"/api/job/{job_id}/generate",
            json={"provider": "noop"},
        )
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert gen_data["generated"] == 0  # noop returns empty alt_text
        assert "images" in gen_data

    def test_generate_bad_provider(self, client: TestClient, images_pdf: Path) -> None:
        with open(images_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (images_pdf.name, f, "application/pdf")},
            )
        job_id = resp.json()["job_id"]

        gen_resp = client.post(
            f"/api/job/{job_id}/generate",
            json={"provider": "nonexistent"},
        )
        assert gen_resp.status_code == 400

    def test_frontend_has_ai_toggle(self, client: TestClient) -> None:
        resp = client.get("/")
        assert "ai-toggle" in resp.text
        assert "provider-select" in resp.text
        assert "api-key-input" in resp.text
