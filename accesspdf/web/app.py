"""FastAPI web application for browser-based alt text review."""

from __future__ import annotations

import io
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from accesspdf.alttext.sidecar import SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus

# ── In-memory job storage ───────────────────────────────────────────────────

_MAX_JOB_AGE_SECONDS = 3600  # 1 hour


class _Job:
    """Represents a single upload + processing session."""

    __slots__ = ("job_id", "work_dir", "input_path", "output_path", "sidecar",
                 "sidecar_path", "created_at", "error")

    def __init__(self, job_id: str, work_dir: Path) -> None:
        self.job_id = job_id
        self.work_dir = work_dir
        self.input_path: Path | None = None
        self.output_path: Path | None = None
        self.sidecar: SidecarFile | None = None
        self.sidecar_path: Path | None = None
        self.created_at = time.time()
        self.error: str | None = None


_jobs: dict[str, _Job] = {}


def _cleanup_old_jobs() -> None:
    """Remove jobs older than _MAX_JOB_AGE_SECONDS."""
    now = time.time()
    expired = [jid for jid, j in _jobs.items() if now - j.created_at > _MAX_JOB_AGE_SECONDS]
    for jid in expired:
        job = _jobs.pop(jid)
        shutil.rmtree(job.work_dir, ignore_errors=True)


def _get_job(job_id: str) -> _Job:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


# ── FastAPI app ─────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and return the FastAPI application."""
    app = FastAPI(title="AccessPDF", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        from jinja2 import Environment, FileSystemLoader

        templates_dir = Path(__file__).parent / "templates"
        env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
        template = env.get_template("index.html")
        return HTMLResponse(template.render())

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        """Upload a PDF, run the pipeline, return job info."""
        _cleanup_old_jobs()

        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

        job_id = uuid.uuid4().hex[:12]
        work_dir = Path(tempfile.mkdtemp(prefix=f"accesspdf_{job_id}_"))

        job = _Job(job_id, work_dir)
        _jobs[job_id] = job

        # Save uploaded file
        input_path = work_dir / file.filename
        contents = await file.read()
        input_path.write_bytes(contents)
        job.input_path = input_path

        # Run pipeline
        output_path = work_dir / f"{input_path.stem}_accessible.pdf"
        try:
            from accesspdf.pipeline import run_pipeline

            run_pipeline(input_path, output_path)
            job.output_path = output_path

            # Load the sidecar
            sidecar_path = SidecarManager.sidecar_path_for(output_path)
            if sidecar_path.is_file():
                job.sidecar = SidecarManager.load(sidecar_path)
                job.sidecar_path = sidecar_path
            else:
                job.sidecar = SidecarFile(document=output_path.name)
                job.sidecar_path = sidecar_path
        except Exception as exc:
            job.error = str(exc)

        return _job_status_dict(job)

    @app.get("/api/job/{job_id}")
    async def job_status(job_id: str) -> dict:
        """Get the status and image list for a job."""
        return _job_status_dict(_get_job(job_id))

    @app.get("/api/job/{job_id}/image/{image_hash}")
    async def get_image(job_id: str, image_hash: str) -> StreamingResponse:
        """Return a specific image from the processed PDF as PNG."""
        job = _get_job(job_id)
        if job.output_path is None:
            raise HTTPException(status_code=400, detail="Job has no output.")

        from accesspdf.alttext.extract import extract_image

        img = extract_image(job.output_path, image_hash)
        if img is None:
            raise HTTPException(status_code=404, detail="Image not found.")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    @app.post("/api/job/{job_id}/alt-text")
    async def save_alt_text(job_id: str, updates: list[dict]) -> dict:
        """Save alt text edits for a job.

        Expects a JSON array of {image_hash, alt_text, status}.
        """
        job = _get_job(job_id)
        if job.sidecar is None:
            raise HTTPException(status_code=400, detail="No sidecar for this job.")

        for update in updates:
            entry = job.sidecar.get_entry(update["image_hash"])
            if entry is None:
                continue
            if "alt_text" in update:
                entry.alt_text = update["alt_text"]
            if "status" in update:
                entry.status = AltTextStatus(update["status"])

        # Save to disk
        if job.sidecar_path:
            SidecarManager.save(job.sidecar, job.sidecar_path)

        return {"saved": len(updates)}

    @app.post("/api/job/{job_id}/inject")
    async def inject(job_id: str) -> dict:
        """Re-inject approved alt text and prepare download."""
        job = _get_job(job_id)
        if job.output_path is None or job.sidecar is None:
            raise HTTPException(status_code=400, detail="Job not ready.")

        from accesspdf.alttext.injector import inject_alt_text

        count = inject_alt_text(job.output_path, job.sidecar)
        return {"injected": count}

    @app.get("/api/job/{job_id}/download")
    async def download(job_id: str) -> FileResponse:
        """Download the fixed PDF."""
        job = _get_job(job_id)
        if job.output_path is None or not job.output_path.is_file():
            raise HTTPException(status_code=400, detail="No output file available.")

        return FileResponse(
            path=job.output_path,
            filename=job.output_path.name,
            media_type="application/pdf",
        )

    @app.get("/api/providers")
    async def get_providers() -> dict:
        """Return available AI providers."""
        from accesspdf.providers import list_available

        providers = []
        for name, available in list_available():
            providers.append({
                "name": name,
                "available": available,
                "needs_api_key": name not in ("ollama", "noop"),
            })
        return {"providers": providers}

    @app.post("/api/job/{job_id}/generate")
    async def generate(job_id: str, request: dict) -> dict:
        """Generate AI alt text drafts for images in a job.

        Expects JSON: {provider, api_key?, model?}
        """
        job = _get_job(job_id)
        if job.output_path is None or job.sidecar is None:
            raise HTTPException(status_code=400, detail="Job not ready.")

        provider_name = request.get("provider", "ollama")
        api_key = request.get("api_key")
        model = request.get("model")

        from accesspdf.providers import get_provider

        kwargs: dict = {}
        if model:
            kwargs["model"] = model
        try:
            provider = get_provider(provider_name, api_key=api_key, **kwargs)
        except (ValueError, ImportError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Generate for images that need drafts
        from accesspdf.alttext.extract import extract_image
        from accesspdf.providers.base import ImageContext

        pending = [e for e in job.sidecar.images
                   if not e.ai_draft and e.status == AltTextStatus.NEEDS_REVIEW]

        import asyncio

        generated = 0
        errors = []
        for i, entry in enumerate(pending):
            img = extract_image(job.output_path, entry.hash)
            if img is None:
                continue

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            context = ImageContext(
                image_bytes=buf.getvalue(),
                page=entry.page,
                caption=entry.caption,
                document_title=job.sidecar.document,
            )

            result = await provider.generate(context)
            if result.alt_text:
                entry.ai_draft = result.alt_text
                generated += 1
            elif result.error:
                errors.append({"image_id": entry.id, "error": result.error})

            # Brief pause between requests to respect rate limits
            if i < len(pending) - 1:
                await asyncio.sleep(2)

        # Save sidecar
        if job.sidecar_path:
            SidecarManager.save(job.sidecar, job.sidecar_path)

        return {
            "generated": generated,
            "errors": errors,
            "images": [
                {
                    "id": e.id,
                    "image_hash": e.hash,
                    "page": e.page,
                    "alt_text": e.alt_text,
                    "ai_draft": e.ai_draft,
                    "status": e.status.value,
                }
                for e in job.sidecar.images
            ],
        }

    return app


def _job_status_dict(job: _Job) -> dict:
    """Build a JSON-serializable status dict for a job."""
    images = []
    if job.sidecar:
        for entry in job.sidecar.images:
            images.append({
                "id": entry.id,
                "image_hash": entry.hash,
                "page": entry.page,
                "alt_text": entry.alt_text,
                "ai_draft": entry.ai_draft,
                "status": entry.status.value,
            })

    return {
        "job_id": job.job_id,
        "filename": job.input_path.name if job.input_path else None,
        "error": job.error,
        "images": images,
        "stats": job.sidecar.stats if job.sidecar else None,
    }
