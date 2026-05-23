"""
TextileSearch — Import API

POST  /import/folder          Start importing a new folder
GET   /import/status          Get current import progress
POST  /import/pause
POST  /import/resume
POST  /import/sync-batch      Receive chokidar events from Electron
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy import func, select

from app.db.models import Image as ImageModel, WatchedFolder
from app.db.session import db_session
from app.services.sync import handle_batch, SyncBatchResult, _walk_supported

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/import", tags=["import"])

# ── Lazy references to the running ImportWorker (set by app factory) ─────────
# These are set once at startup — treated as write-once, read-many.
_worker: object | None = None   # ImportWorker, typed as object to avoid circular


def set_worker(worker: object) -> None:
    global _worker
    _worker = worker


def _get_worker() -> object:
    if _worker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Import worker not initialised.",
        )
    return _worker


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class FolderImportRequest(BaseModel):
    folder_path: str = Field(..., min_length=1)
    display_name: str = Field("", max_length=128)


class ImportStatusResponse(BaseModel):
    total_queued: int
    processed: int
    failed: int
    skipped: int
    is_running: bool
    is_paused: bool


class SyncEventIn(BaseModel):
    event_type: str = Field(..., pattern="^(add|unlink|change)$")
    abs_path: str


class SyncBatchRequest(BaseModel):
    events: list[SyncEventIn]


class SyncBatchResponse(BaseModel):
    queued_for_import: int
    orphaned: int
    requeued: int
    skipped: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/folder", status_code=status.HTTP_202_ACCEPTED)
def start_folder_import(
    req: FolderImportRequest,
    session: Annotated[Session, Depends(db_session)],
) -> dict[str, str | int]:
    p = Path(req.folder_path)
    if not p.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {req.folder_path}",
        )

    # Register folder in DB (idempotent)
    folder = (
        session.query(WatchedFolder)
        .filter(WatchedFolder.folder_path == str(p))
        .first()
    )
    if folder is None:
        folder = WatchedFolder(
            folder_path=str(p),
            display_name=req.display_name or p.name,
            is_available=True,
        )
        session.add(folder)
        session.commit()
        session.refresh(folder)

    # Queue images from the folder
    known: set[str] = {
        row[0]
        for row in session.execute(select(ImageModel.file_path))
    }
    new_count = 0
    for img_path in _walk_supported(p):
        if str(img_path) not in known:
            session.add(ImageModel(
                file_path      = str(img_path),
                filename       = img_path.name,
                root_folder_id = folder.id,
                relative_path  = str(img_path.relative_to(p)),
                import_status  = "queued",
            ))
            new_count += 1
    session.commit()

    # Tell the worker to start (idempotent)
    worker = _get_worker()
    worker.start()  # type: ignore[attr-defined]

    return {"folder_id": folder.id, "queued_count": new_count, "message": f"Folder import started ({new_count} images)"}


@router.get("/status", response_model=ImportStatusResponse)
def get_import_status() -> ImportStatusResponse:
    worker = _get_worker()
    prog = worker.get_progress()  # type: ignore[attr-defined]
    return ImportStatusResponse(
        total_queued=prog.total_queued,
        processed=prog.processed,
        failed=prog.failed,
        skipped=prog.skipped,
        is_running=prog.is_running,
        is_paused=prog.is_paused,
    )


@router.post("/pause", )
def pause_import() -> None:
    worker = _get_worker()
    worker.pause()  # type: ignore[attr-defined]


@router.post("/resume", )
def resume_import() -> None:
    worker = _get_worker()
    worker.resume()  # type: ignore[attr-defined]


@router.post("/sync-batch", response_model=SyncBatchResponse)
def sync_batch(
    req: SyncBatchRequest,
) -> SyncBatchResponse:
    added: list[str] = [ev.abs_path for ev in req.events if ev.event_type == "add"]
    removed: list[str] = [ev.abs_path for ev in req.events if ev.event_type == "unlink"]
    result: SyncBatchResult = handle_batch(added, removed)
    return SyncBatchResponse(
        queued_for_import=result.queued,
        orphaned=result.orphaned,
        requeued=result.renamed,
        skipped=0,
    )
