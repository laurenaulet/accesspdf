"""FastAPI web application for browser-based alt text review."""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from accesspdf.alttext.sidecar import SidecarFile, SidecarManager
from accesspdf.models import AltTextStatus

def _clean_title(name: str) -> str:
    """Return *name* only if it looks like a real document title, not a filename."""
    if name.lower().endswith(".pdf"):
        return ""
    return name


# ── In-memory job storage ───────────────────────────────────────────────────

_MAX_JOB_AGE_SECONDS = 3600  # 1 hour

# Processing stages (in order)
STAGE_UPLOADING = "uploading"
STAGE_ANALYZING = "analyzing"
STAGE_FIXING = "fixing"
STAGE_LOADING = "loading"
STAGE_DONE = "done"
STAGE_ERROR = "error"


class _Job:
    """Represents a single upload + processing session."""

    __slots__ = ("job_id", "work_dir", "input_path", "output_path", "sidecar",
                 "sidecar_path", "created_at", "error", "analysis", "stage",
                 "gen_stage", "gen_current", "gen_total", "gen_errors",
                 "sidecar_lock")

    def __init__(self, job_id: str, work_dir: Path) -> None:
        self.job_id = job_id
        self.work_dir = work_dir
        self.input_path: Path | None = None
        self.output_path: Path | None = None
        self.sidecar: SidecarFile | None = None
        self.sidecar_path: Path | None = None
        self.created_at = time.time()
        self.error: str | None = None
        self.analysis: dict | None = None
        self.stage: str = STAGE_UPLOADING
        # AI generation state
        self.gen_stage: str = "idle"  # idle | generating | done | error
        self.gen_current: int = 0
        self.gen_total: int = 0
        self.gen_errors: list[dict] = []
        # Lock to protect concurrent sidecar reads/writes
        self.sidecar_lock = threading.Lock()


_jobs: dict[str, _Job] = {}


def _cleanup_old_jobs() -> None:
    """Remove jobs and batch jobs older than _MAX_JOB_AGE_SECONDS."""
    now = time.time()
    expired = [jid for jid, j in _jobs.items() if now - j.created_at > _MAX_JOB_AGE_SECONDS]
    for jid in expired:
        job = _jobs.pop(jid)
        shutil.rmtree(job.work_dir, ignore_errors=True)
    expired_b = [bid for bid, b in _batch_jobs.items() if now - b.created_at > _MAX_JOB_AGE_SECONDS]
    for bid in expired_b:
        batch = _batch_jobs.pop(bid)
        shutil.rmtree(batch.work_dir, ignore_errors=True)


def _get_job(job_id: str) -> _Job:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


def _process_job(job: _Job) -> None:
    """Process a job in a background thread (analyze + fix + load sidecar)."""
    # Stage 1: Analyze the original PDF
    job.stage = STAGE_ANALYZING
    try:
        from accesspdf.analyzer import PDFAnalyzer

        analyzer = PDFAnalyzer()
        result = analyzer.analyze(job.input_path)
        job.analysis = {
            "pages": result.page_count,
            "is_tagged": result.is_tagged,
            "has_lang": result.has_lang,
            "title": result.title or "",
            "images": len(result.images),
            "errors": result.error_count,
            "warnings": result.warning_count,
            "is_scanned": result.is_scanned,
            "issues": [
                {
                    "rule": issue.rule,
                    "severity": issue.severity.value,
                    "message": issue.message,
                }
                for issue in result.issues
            ],
        }
    except Exception:
        pass  # analysis is optional, don't block processing

    # Stage 2: Run the fix pipeline
    job.stage = STAGE_FIXING
    output_path = job.work_dir / f"{job.input_path.stem}_accessible.pdf"
    try:
        from accesspdf.pipeline import run_pipeline

        run_pipeline(job.input_path, output_path)
        job.output_path = output_path
    except Exception as exc:
        job.error = str(exc)
        job.stage = STAGE_ERROR
        return

    # Stage 3: Load sidecar
    job.stage = STAGE_LOADING
    try:
        sidecar_path = SidecarManager.sidecar_path_for(output_path)
        if sidecar_path.is_file():
            job.sidecar = SidecarManager.load(sidecar_path)
            job.sidecar_path = sidecar_path
        else:
            job.sidecar = SidecarFile(document=output_path.name)
            job.sidecar_path = sidecar_path
    except Exception as exc:
        job.error = str(exc)
        job.stage = STAGE_ERROR
        return

    job.stage = STAGE_DONE


_CONCURRENT_REQUESTS = 1  # Sequential — provider throttle handles pacing


def _generate_alt_text(job: _Job, provider: object, pending_entries: list,
                       document_context: str = "") -> None:
    """Generate AI alt text in a background thread using concurrent requests."""
    import asyncio

    async def _run() -> None:
        from accesspdf.alttext.extract import extract_image, prepare_for_ai
        from accesspdf.providers.base import ImageContext

        job.gen_stage = "generating"
        job.gen_total = len(pending_entries)
        job.gen_current = 0
        job.gen_errors = []

        sem = asyncio.Semaphore(_CONCURRENT_REQUESTS)
        completed = 0

        async def _process_one(entry: object) -> None:
            nonlocal completed
            try:
                img = extract_image(job.output_path, entry.hash)
                if img is None:
                    completed += 1
                    job.gen_current = completed
                    return

                context = ImageContext(
                    image_bytes=prepare_for_ai(img),
                    page=entry.page,
                    caption=entry.caption,
                    surrounding_text=entry.context,
                    document_title=_clean_title(job.sidecar.document),
                    document_context=document_context,
                )

                async with sem:
                    result = await provider.generate(context)

                if result.alt_text:
                    with job.sidecar_lock:
                        entry.ai_draft = result.alt_text
                elif result.error:
                    job.gen_errors.append({"image_id": entry.id, "error": result.error})
            except Exception as exc:
                job.gen_errors.append({"image_id": entry.id, "error": str(exc)})

            completed += 1
            job.gen_current = completed

        await asyncio.gather(*[_process_one(e) for e in pending_entries])

        # Save sidecar
        if job.sidecar_path:
            with job.sidecar_lock:
                SidecarManager.save(job.sidecar, job.sidecar_path)

        job.gen_stage = "done"

    try:
        asyncio.run(_run())
    except Exception as exc:
        job.gen_errors.append({"image_id": "unknown", "error": str(exc)})
        job.gen_stage = "error"


# ── Batch job storage ─────────────────────────────────────────────────────

_MAX_BATCH_FILES = 50


class _BatchJob:
    """Represents a batch upload + processing session (no alt text review)."""

    __slots__ = ("batch_id", "work_dir", "created_at", "stage",
                 "files", "current_index", "total_files", "error")

    def __init__(self, batch_id: str, work_dir: Path) -> None:
        self.batch_id = batch_id
        self.work_dir = work_dir
        self.created_at = time.time()
        self.stage: str = STAGE_UPLOADING
        self.files: list[dict] = []  # [{name, input_path, output_path, status, error}]
        self.current_index: int = 0
        self.total_files: int = 0
        self.error: str | None = None


_batch_jobs: dict[str, _BatchJob] = {}


def _get_batch(batch_id: str) -> _BatchJob:
    if batch_id not in _batch_jobs:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _batch_jobs[batch_id]


def _process_batch(batch: _BatchJob) -> None:
    """Process all files in a batch sequentially in a background thread."""
    try:
        from accesspdf.analyzer import PDFAnalyzer
        from accesspdf.pipeline import run_pipeline

        batch.stage = STAGE_FIXING
        analyzer = PDFAnalyzer()

        for i, file_info in enumerate(batch.files):
            batch.current_index = i
            file_info["status"] = "fixing"

            try:
                # Check if scanned before processing
                try:
                    analysis = analyzer.analyze(file_info["input_path"])
                    file_info["is_scanned"] = analysis.is_scanned
                except Exception:
                    file_info["is_scanned"] = False

                run_pipeline(file_info["input_path"], file_info["output_path"])
                file_info["status"] = "done"
            except Exception as exc:
                file_info["status"] = "error"
                file_info["error"] = str(exc)

        batch.stage = STAGE_DONE
    except Exception as exc:
        batch.error = str(exc)
        batch.stage = STAGE_ERROR


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
        """Upload a PDF and start background processing. Returns job_id immediately."""
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

        # Start processing in background thread
        thread = threading.Thread(target=_process_job, args=(job,), daemon=True)
        thread.start()

        return {"job_id": job.job_id, "stage": job.stage}

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

        with job.sidecar_lock:
            for update in updates:
                entry = job.sidecar.get_entry(update["image_hash"])
                if entry is None:
                    continue
                if "alt_text" in update:
                    entry.alt_text = update["alt_text"]
                if "context" in update:
                    entry.context = update["context"]
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
        """Start AI alt text generation in the background.

        Expects JSON: {provider, api_key?, model?}
        Returns immediately. Poll /api/job/{job_id} for gen_stage progress.
        """
        job = _get_job(job_id)
        if job.output_path is None or job.sidecar is None:
            raise HTTPException(status_code=400, detail="Job not ready.")

        if job.gen_stage == "generating":
            raise HTTPException(status_code=409, detail="Generation already in progress.")

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

        pending = [e for e in job.sidecar.images
                   if not e.ai_draft and e.status == AltTextStatus.NEEDS_REVIEW]

        if not pending:
            return {"gen_stage": "done", "gen_current": 0, "gen_total": 0}

        # Preflight check — verify API key and rate limit before starting batch
        if hasattr(provider, "preflight"):
            try:
                error = await provider.preflight()
            except Exception as exc:
                error = str(exc)
            if error:
                raise HTTPException(status_code=429, detail=error)

        # Start generation in background thread
        job.gen_stage = "generating"
        job.gen_total = len(pending)
        job.gen_current = 0
        job.gen_errors = []

        document_context = request.get("document_context", "")

        thread = threading.Thread(
            target=_generate_alt_text, args=(job, provider, pending, document_context),
            daemon=True,
        )
        thread.start()

        return {"gen_stage": "generating", "gen_current": 0, "gen_total": len(pending)}

    # ── Batch endpoints ───────────────────────────────────────────────────

    @app.post("/api/batch/upload")
    async def batch_upload(files: List[UploadFile] = File(...)) -> dict:
        """Upload multiple PDFs for batch structural fixing. Returns batch_id."""
        _cleanup_old_jobs()

        if len(files) > _MAX_BATCH_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"Too many files. Maximum is {_MAX_BATCH_FILES}.",
            )

        for f in files:
            if not f.filename or not f.filename.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Not a PDF: {f.filename or '(unnamed)'}",
                )

        batch_id = uuid.uuid4().hex[:12]
        work_dir = Path(tempfile.mkdtemp(prefix=f"accesspdf_batch_{batch_id}_"))

        batch = _BatchJob(batch_id, work_dir)
        batch.total_files = len(files)

        # Handle duplicate filenames by appending a counter
        seen_names: dict[str, int] = {}
        for f in files:
            name = f.filename or "file.pdf"
            if name in seen_names:
                seen_names[name] += 1
                stem = Path(name).stem
                suffix = Path(name).suffix
                name = f"{stem}_{seen_names[name]}{suffix}"
            else:
                seen_names[name] = 0

            input_path = work_dir / name
            contents = await f.read()
            input_path.write_bytes(contents)

            output_path = work_dir / f"{input_path.stem}_accessible.pdf"
            batch.files.append({
                "name": name,
                "input_path": input_path,
                "output_path": output_path,
                "status": "pending",
                "error": None,
                "is_scanned": False,
            })

        _batch_jobs[batch_id] = batch

        thread = threading.Thread(target=_process_batch, args=(batch,), daemon=True)
        thread.start()

        return {"batch_id": batch_id, "total_files": len(files)}

    @app.get("/api/batch/{batch_id}")
    async def batch_status(batch_id: str) -> dict:
        """Get batch processing status with per-file progress."""
        batch = _get_batch(batch_id)
        done_count = sum(1 for f in batch.files if f["status"] == "done")
        failed_count = sum(1 for f in batch.files if f["status"] == "error")
        return {
            "batch_id": batch.batch_id,
            "stage": batch.stage,
            "total_files": batch.total_files,
            "current_index": batch.current_index,
            "done_count": done_count,
            "failed_count": failed_count,
            "files": [
                {
                    "name": fi["name"],
                    "status": fi["status"],
                    "error": fi["error"],
                    "is_scanned": fi.get("is_scanned", False),
                }
                for fi in batch.files
            ],
        }

    @app.get("/api/batch/{batch_id}/download")
    async def batch_download(batch_id: str) -> StreamingResponse:
        """Download all successfully fixed PDFs as a ZIP."""
        batch = _get_batch(batch_id)
        if batch.stage != STAGE_DONE:
            raise HTTPException(status_code=400, detail="Batch not finished yet.")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fi in batch.files:
                if fi["status"] == "done" and fi["output_path"].is_file():
                    zf.write(fi["output_path"], fi["output_path"].name)

        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=accessible_pdfs.zip"},
        )

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
                "context": entry.context,
                "status": entry.status.value,
            })

    return {
        "job_id": job.job_id,
        "stage": job.stage,
        "filename": job.input_path.name if job.input_path else None,
        "error": job.error,
        "images": images,
        "stats": job.sidecar.stats if job.sidecar else None,
        "analysis": job.analysis,
        "gen_stage": job.gen_stage,
        "gen_current": job.gen_current,
        "gen_total": job.gen_total,
        "gen_errors": job.gen_errors,
    }
