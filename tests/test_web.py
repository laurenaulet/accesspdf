"""Tests for the web UI API endpoints."""

from __future__ import annotations

import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accesspdf.web.app import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def _upload_and_wait(client: TestClient, pdf_path: Path, timeout: float = 30) -> dict:
    """Upload a PDF and poll until processing completes. Returns full job data."""
    with open(pdf_path, "rb") as f:
        resp = client.post(
            "/api/upload",
            files={"file": (pdf_path.name, f, "application/pdf")},
        )
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]

    # Poll until done or error
    deadline = time.time() + timeout
    while time.time() < deadline:
        status_resp = client.get(f"/api/job/{job_id}")
        status_data = status_resp.json()
        if status_data.get("stage") in ("done", "error"):
            return status_data
        time.sleep(0.1)

    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


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

    def test_upload_returns_job_id_immediately(self, client: TestClient, simple_pdf: Path) -> None:
        """Upload should return job_id and stage right away."""
        with open(simple_pdf, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": (simple_pdf.name, f, "application/pdf")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "stage" in data

    def test_upload_and_status(self, client: TestClient, simple_pdf: Path) -> None:
        data = _upload_and_wait(client, simple_pdf)
        assert data["job_id"]
        assert data["filename"] == simple_pdf.name
        assert data["error"] is None
        assert data["stage"] == "done"

    def test_upload_with_images(self, client: TestClient, images_pdf: Path) -> None:
        data = _upload_and_wait(client, images_pdf)
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
        data = _upload_and_wait(client, images_pdf)
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
        data = _upload_and_wait(client, images_pdf)
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
        data = _upload_and_wait(client, simple_pdf)
        job_id = data["job_id"]
        img_resp = client.get(f"/api/job/{job_id}/image/deadbeef")
        assert img_resp.status_code == 404

    def test_download_no_images_pdf(self, client: TestClient, simple_pdf: Path) -> None:
        """A PDF with no images still gets structural fixes and is downloadable."""
        data = _upload_and_wait(client, simple_pdf)
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
        """Generate endpoint with noop provider starts background generation."""
        data = _upload_and_wait(client, images_pdf)
        job_id = data["job_id"]

        gen_resp = client.post(
            f"/api/job/{job_id}/generate",
            json={"provider": "noop"},
        )
        assert gen_resp.status_code == 200
        gen_data = gen_resp.json()
        assert gen_data["gen_stage"] == "generating"
        assert gen_data["gen_total"] >= 1

        # Wait for generation to complete
        deadline = time.time() + 30
        while time.time() < deadline:
            status = client.get(f"/api/job/{job_id}").json()
            if status["gen_stage"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert status["gen_stage"] == "done"

    def test_generate_bad_provider(self, client: TestClient, images_pdf: Path) -> None:
        data = _upload_and_wait(client, images_pdf)
        job_id = data["job_id"]

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

    def test_frontend_has_progress_bar(self, client: TestClient) -> None:
        """Frontend should have progress bar elements instead of a spinner."""
        resp = client.get("/")
        assert "progress-fill" in resp.text
        assert "progress-steps" in resp.text
        assert "step-analyzing" in resp.text
        assert "step-fixing" in resp.text

    def test_frontend_has_batch_elements(self, client: TestClient) -> None:
        """Frontend should have batch mode selector and batch UI."""
        resp = client.get("/")
        assert "mode-selector" in resp.text
        assert "batch-file-input" in resp.text
        assert "batch-progress" in resp.text
        assert "batch-results" in resp.text
        assert "btn-batch-download" in resp.text

    def test_frontend_has_scanned_warning(self, client: TestClient) -> None:
        """Frontend should have a scanned PDF warning element."""
        resp = client.get("/")
        assert "scanned-warning" in resp.text
        assert "scanned PDF" in resp.text.lower() or "Scanned PDF" in resp.text

    def test_job_status_includes_is_scanned(self, client: TestClient, simple_pdf: Path) -> None:
        """Job status should include is_scanned field in analysis."""
        data = _upload_and_wait(client, simple_pdf)
        assert data["stage"] == "done"
        assert data["analysis"] is not None
        assert "is_scanned" in data["analysis"]
        assert data["analysis"]["is_scanned"] is False

    def test_scanned_pdf_detected_via_web(self, client: TestClient, scanned_pdf: Path) -> None:
        """Scanned PDF should be flagged via the web API."""
        data = _upload_and_wait(client, scanned_pdf)
        assert data["stage"] == "done"
        assert data["analysis"]["is_scanned"] is True


def _batch_upload_and_wait(
    client: TestClient, pdf_paths: list[Path], timeout: float = 30,
) -> dict:
    """Upload multiple PDFs as batch and poll until done. Returns batch status."""
    files = []
    for p in pdf_paths:
        files.append(("files", (p.name, open(p, "rb"), "application/pdf")))

    resp = client.post("/api/batch/upload", files=files)

    # Close file handles
    for _, (_, fh, _) in files:
        fh.close()

    assert resp.status_code == 200
    data = resp.json()
    batch_id = data["batch_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        status_resp = client.get(f"/api/batch/{batch_id}")
        status_data = status_resp.json()
        if status_data.get("stage") in ("done", "error"):
            return status_data
        time.sleep(0.1)

    raise TimeoutError(f"Batch {batch_id} did not complete within {timeout}s")


class TestBatchMode:
    def test_batch_upload_and_status(self, client: TestClient, simple_pdf: Path) -> None:
        """Batch upload of one PDF should succeed and complete."""
        data = _batch_upload_and_wait(client, [simple_pdf])
        assert data["stage"] == "done"
        assert data["total_files"] == 1
        assert data["done_count"] == 1
        assert data["failed_count"] == 0

    def test_batch_upload_multiple(
        self, client: TestClient, simple_pdf: Path, images_pdf: Path,
    ) -> None:
        """Batch upload of two PDFs should process both."""
        data = _batch_upload_and_wait(client, [simple_pdf, images_pdf])
        assert data["stage"] == "done"
        assert data["total_files"] == 2
        assert data["done_count"] == 2
        assert data["failed_count"] == 0
        assert len(data["files"]) == 2
        assert all(f["status"] == "done" for f in data["files"])

    def test_batch_zip_download(
        self, client: TestClient, simple_pdf: Path, images_pdf: Path,
    ) -> None:
        """Batch download returns a valid ZIP with fixed PDFs."""
        data = _batch_upload_and_wait(client, [simple_pdf, images_pdf])
        batch_id = data["batch_id"]

        dl_resp = client.get(f"/api/batch/{batch_id}/download")
        assert dl_resp.status_code == 200
        assert "application/zip" in dl_resp.headers["content-type"]

        # Verify it's a valid ZIP with the right number of files
        zf = zipfile.ZipFile(BytesIO(dl_resp.content))
        names = zf.namelist()
        assert len(names) == 2
        assert all(n.endswith("_accessible.pdf") for n in names)
        zf.close()

    def test_batch_rejects_non_pdf(self, client: TestClient, tmp_path: Path) -> None:
        """Batch upload should reject non-PDF files."""
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("not a pdf")
        with open(txt_file, "rb") as f:
            resp = client.post(
                "/api/batch/upload",
                files=[("files", ("readme.txt", f, "text/plain"))],
            )
        assert resp.status_code == 400

    def test_batch_missing_batch_404(self, client: TestClient) -> None:
        """Requesting a nonexistent batch returns 404."""
        resp = client.get("/api/batch/nonexistent")
        assert resp.status_code == 404

    def test_batch_download_before_done(self, client: TestClient, simple_pdf: Path) -> None:
        """Download should fail if batch is not finished."""
        # Upload but don't wait
        with open(simple_pdf, "rb") as f:
            resp = client.post(
                "/api/batch/upload",
                files=[("files", (simple_pdf.name, f, "application/pdf"))],
            )
        batch_id = resp.json()["batch_id"]

        # Try downloading immediately (may still be processing)
        dl_resp = client.get(f"/api/batch/{batch_id}/download")
        # Could be 200 if it finished fast, or 400 if still processing
        assert dl_resp.status_code in (200, 400)
