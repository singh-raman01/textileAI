"""
TextileSearch — Import Pipeline

Runs in a background thread. Processes 'queued' images from the DB:
  1. Compute MD5 (skip duplicate file_md5 within folder)
  2. Embed image (FashionCLIP)
  3. Run OCR
  4. Parse label fields
  5. Generate thumbnail
  6. Write to DB + FAISS

Strict design:
  - No global state — all dependencies passed via constructor
  - Explicit pause/resume/stop via threading.Event
  - Crash recovery: on startup, any row with status='processing' is reset to 'queued'
  - Disk space guard: pauses at <500 MB free (D11)
  - ModelNotAvailableError: image is indexed (metadata only), faiss_id stays NULL
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Image as ImageModel, TextileMetadata, FabricComposition
from app.db.session import get_session
from app.exceptions import (
    DiskSpaceError,
    EmbeddingFailedError,
    ImageReadError,
    ModelNotAvailableError,
    OcrProcessingError,
)
from app.services.field_parser import parse_label
from app.services.protocols import EmbedderProtocol, OcrProtocol, ThumbnailProtocol
from app.services.faiss_index import FaissIndexManager
from app.services.thumbnail import ThumbnailService

logger = logging.getLogger(__name__)

BATCH_SIZE: Final[int] = 32
DISK_THRESHOLD_MB: Final[float] = 500.0
DISK_CHECK_INTERVAL: Final[int] = 10        # check every N images
LOCK_RETRY_COUNT: Final[int] = 3
LOCK_RETRY_DELAY_S: Final[float] = 2.0


# ---------------------------------------------------------------------------
# Progress snapshot (thread-safe read)
# ---------------------------------------------------------------------------

class ImportProgress:
    __slots__ = (
        "total_queued", "processed", "failed", "skipped",
        "is_running", "is_paused",
    )

    def __init__(self) -> None:
        self.total_queued: int = 0
        self.processed: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.is_running: bool = False
        self.is_paused: bool = False


# ---------------------------------------------------------------------------
# ImportWorker
# ---------------------------------------------------------------------------

class ImportWorker:
    """
    Background import worker. One instance per application lifetime.

    Usage:
        worker = ImportWorker(embedder, ocr, thumbnail_svc, faiss_mgr, data_dir)
        worker.start()
        worker.pause()
        worker.resume()
        worker.stop()
        progress = worker.get_progress()
    """

    def __init__(
        self,
        embedder: EmbedderProtocol,
        ocr: OcrProtocol,
        thumbnail_svc: ThumbnailProtocol,
        faiss_mgr: FaissIndexManager,
        data_dir: Path,
    ) -> None:
        self._embedder = embedder
        self._ocr = ocr
        self._thumbnail_svc = thumbnail_svc
        self._faiss = faiss_mgr
        self._thumbnail_dir = data_dir / "thumbnails"

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()      # not paused initially

        self._progress_lock = threading.Lock()
        self._progress = ImportProgress()
        self._thread: threading.Thread | None = None

    # -- control -------------------------------------------------------------

    def start(self) -> None:
        """Spawn the worker thread. Idempotent — safe to call if already running."""
        with self._progress_lock:
            if self._progress.is_running:
                return
            self._progress.is_running = True

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ImportWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("ImportWorker started")

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()      # unblock if paused so thread can exit
        if self._thread is not None:
            self._thread.join(timeout=10.0)
        with self._progress_lock:
            self._progress.is_running = False
        logger.info("ImportWorker stopped")

    def pause(self) -> None:
        self._pause_event.clear()
        with self._progress_lock:
            self._progress.is_paused = True
        logger.info("ImportWorker paused")

    def resume(self) -> None:
        self._pause_event.set()
        with self._progress_lock:
            self._progress.is_paused = False
        logger.info("ImportWorker resumed")

    def get_progress(self) -> ImportProgress:
        with self._progress_lock:
            snap = ImportProgress()
            snap.total_queued = self._progress.total_queued
            snap.processed = self._progress.processed
            snap.failed = self._progress.failed
            snap.skipped = self._progress.skipped
            snap.is_running = self._progress.is_running
            snap.is_paused = self._progress.is_paused
            return snap

    # -- crash recovery ------------------------------------------------------

    def recover_interrupted(self) -> None:
        """
        Reset any rows left in status='processing' from a previous crash.
        Call once before start() at app launch.
        """
        with get_session() as session:
            updated = session.execute(
                update(ImageModel)
                .where(ImageModel.import_status == "processing")
                .values(import_status="queued")
            ).rowcount
            if updated:
                logger.warning(
                    "Crash recovery: reset processing→queued",
                    extra={"count": updated},
                )

    # -- worker loop ---------------------------------------------------------

    def _run(self) -> None:
        images_since_disk_check = 0

        while not self._stop_event.is_set():
            # Respect pause
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            with get_session() as session:
                batch = self._fetch_batch(session)

            if not batch:
                # Nothing queued — sleep briefly then poll
                time.sleep(2.0)
                continue

            with self._progress_lock:
                self._progress.total_queued += len(batch)

            for image_id in batch:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()

                images_since_disk_check += 1
                if images_since_disk_check >= DISK_CHECK_INTERVAL:
                    images_since_disk_check = 0
                    self._check_disk_space()

                self._process_one(image_id)

            # Save FAISS index after each batch
            try:
                self._faiss.save()
            except Exception as exc:
                logger.error("FAISS save failed after batch", extra={"error": str(exc)})

        with self._progress_lock:
            self._progress.is_running = False

    def _fetch_batch(self, session: Session) -> list[int]:
        rows = session.scalars(
            select(ImageModel.id)
            .where(ImageModel.import_status == "queued")
            .limit(BATCH_SIZE)
        ).all()
        return list(rows)

    def _process_one(self, image_id: int) -> None:
        with get_session() as session:
            image = session.get(ImageModel, image_id)
            if image is None:
                return

            # Mark as processing
            image.import_status = "processing"
            session.flush()

            path = Path(image.file_path)
            if not path.exists():
                image.import_status = "failed"
                image.is_orphaned = True
                with self._progress_lock:
                    self._progress.failed += 1
                return

            success = self._embed_and_ocr(image, path, session)
            image.import_status = "done" if success else "failed"

            with self._progress_lock:
                if success:
                    self._progress.processed += 1
                else:
                    self._progress.failed += 1

    def _embed_and_ocr(
        self, image: ImageModel, path: Path, session: Session
    ) -> bool:
        # ── Embedding ─────────────────────────────────────────────────────────
        faiss_id: int | None = None
        try:
            result = self._embedder.embed(path)
            faiss_id = image.id       # use DB primary key as FAISS id
            self._faiss.add(faiss_id, result.vector)
            image.faiss_id = faiss_id
            image.model_version = self._embedder.model_version
        except ModelNotAvailableError:
            logger.warning(
                "Model unavailable — indexing metadata only",
                extra={"path": str(path)},
            )
        except EmbeddingFailedError as exc:
            logger.warning(
                "Embedding failed",
                extra={"path": exc.image_path, "reason": exc.reason},
            )
            return False

        # ── Thumbnail ─────────────────────────────────────────────────────────
        try:
            thumb_dest = self._thumbnail_svc.generate(path, image.id)
            image.thumbnail_path = str(thumb_dest)
        except ImageReadError as exc:
            logger.warning(
                "Thumbnail generation failed",
                extra={"path": exc.file_path, "reason": exc.reason},
            )
            # Not fatal — continue without thumbnail (placeholder shown in UI)

        # ── OCR + field parsing ────────────────────────────────────────────────
        try:
            ocr_result = self._ocr.extract(path)
            if ocr_result.has_text:
                parsed = parse_label(ocr_result.full_text)
                self._persist_metadata(image.id, parsed, session)
        except OcrProcessingError as exc:
            logger.warning(
                "OCR failed",
                extra={"path": exc.image_path, "reason": exc.reason},
            )
            # Not fatal — image stored without metadata

        return True

    def _persist_metadata(
        self,
        image_id: int,
        parsed: object,     # ParsedLabel — typed by field_parser
        session: Session,
    ) -> None:
        # Avoid circular import — import inline
        from app.services.field_parser import ParsedLabel

        if not isinstance(parsed, ParsedLabel):
            return

        meta = TextileMetadata(
            image_id=image_id,
            supplier=parsed.supplier.value if parsed.supplier.tier < 3 else None,
            supplier_confidence=parsed.supplier.confidence,
            item_no=parsed.item_no.value if parsed.item_no.tier < 3 else None,
            order_no=parsed.order_no.value if parsed.order_no.tier < 3 else None,
            fabric_type=parsed.fabric_type.value if parsed.fabric_type.tier < 3 else None,
            width_min=parsed.width_min.value if parsed.width_min.tier < 3 else None,
            width_max=parsed.width_max.value if parsed.width_max.tier < 3 else None,
            width_unit=parsed.width_unit.value if parsed.width_unit.tier < 3 else None,
            weight_gsm=parsed.weight_gsm.value if parsed.weight_gsm.tier < 3 else None,
            weight_gyd=parsed.weight_gyd.value if parsed.weight_gyd.tier < 3 else None,
            tolerance_pct=parsed.tolerance_pct.value if parsed.tolerance_pct.tier < 3 else None,
            needs_review=parsed.needs_review,
            no_label_detected=parsed.no_label_detected,
        )
        session.add(meta)
        session.flush()

        for comp in parsed.composition.components:
            session.add(FabricComposition(
                metadata_id=meta.id,
                material=comp.material,
                material_raw=comp.material_raw,
                percentage=comp.percentage,
                confidence_tier=comp.tier,
            ))

    def _check_disk_space(self) -> None:
        usage = shutil.disk_usage("/")
        free_mb = usage.free / (1024 * 1024)
        if free_mb < DISK_THRESHOLD_MB:
            logger.error(
                "Disk space critically low — pausing import",
                extra={"free_mb": round(free_mb, 1)},
            )
            self.pause()
            raise DiskSpaceError(free_mb, DISK_THRESHOLD_MB)


# ── Public aliases and utilities ──────────────────────────────────────────────

# Alias — tests and API routes use `Importer`
Importer = ImportWorker


def reset_in_flight_images() -> int:
    """
    Reset any images stuck in 'processing' (in-flight when app last crashed)
    back to 'queued'.  Called once at startup from main.py.
    Returns the count of rows reset.
    """
    from sqlalchemy import update as sa_update
    from app.db.session import get_session
    from app.db.models import Image

    with get_session() as session:
        result = session.execute(
            sa_update(Image)
            .where(Image.import_status == "processing")
            .values(import_status="queued")
        )
        count: int = result.rowcount

    if count:
        import logging
        logging.getLogger(__name__).info(
            "Reset in-flight images to queued", extra={"count": count}
        )
    return count


def init_importer(
    embedder: EmbedderProtocol,
    ocr: OcrProtocol,
    faiss_index: FaissIndexManager,
    thumbnail_dir: Path,
    disk_warning_mb: float = 500.0,
) -> ImportWorker:
    thumbnail_svc = ThumbnailService(thumbnail_dir)
    return ImportWorker(
        embedder=embedder,
        ocr=ocr,
        thumbnail_svc=thumbnail_svc,
        faiss_mgr=faiss_index,
        data_dir=thumbnail_dir,
    )
