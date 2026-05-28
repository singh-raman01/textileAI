"""
TextileSearch Backend — Main Entry Point
Spawned by Electron main process as a child process.
Usage: python main.py --port 8765 --data-dir /path/to/data
"""
from __future__ import annotations

import os

# ── Apple Silicon (MPS) safety net ────────────────────────────────────────────
# Per Hugging Face / PyTorch official guidance, some ops are not yet
# implemented for the MPS backend and will raise NotImplementedError or
# segfault when first invoked. This env var tells PyTorch to silently fall
# back to a CPU kernel for those ops instead of crashing. Must be set
# BEFORE `import torch` runs anywhere in the process.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# ── Multi-library OpenMP collision ────────────────────────────────────────────
# torch, faiss-cpu, onnxruntime, opencv, etc. all bundle their own copy of
# libomp.dylib. When more than one is loaded into the same Python process,
# the OpenMP runtime aborts with:
#   "OMP: Error #15: Initializing libomp.dylib, but found libomp.dylib
#    already initialized."
# On macOS this manifests as a SIGSEGV at the first MPS / FAISS kernel call.
# `KMP_DUPLICATE_LIB_OK=TRUE` tells the runtime to accept the duplicate
# instead of aborting — the official Intel/LLVM-documented escape hatch for
# this exact situation. Must be set BEFORE any ML library imports.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# Tokenizers parallelism warning suppression — we are single-threaded per
# request so this isn't a real problem, but the warning is noisy.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import logging
import sys
from pathlib import Path

from app.core.config import AppConfig, parse_args, set_config
from app.core.logging_config import setup_logging

# ── 1. Config + logging — must come before any other imports ──────────────────
args   = parse_args()
config = AppConfig(args)
set_config(config)

setup_logging(
    log_dir = config.log_dir,
    debug   = os.environ.get("TEXTILE_DEBUG", "").lower() == "true",
)

logger = logging.getLogger(__name__)
logger.info(
    "Backend starting",
    extra={"port": config.port, "data_dir": str(config.data_dir)},
)

# ── 2. Database migrations ─────────────────────────────────────────────────────
os.environ["TEXTILE_DB_URL"] = config.database_url

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig


def _run_migrations() -> None:
    alembic_cfg = AlembicConfig(str(Path(__file__).parent / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).parent / "migrations")
    )
    alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)
    try:
        alembic_command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations complete")
    except Exception as exc:
        logger.critical("Database migration failed", extra={"error": str(exc)})
        sys.exit(1)


_run_migrations()

# ── 3. DB session ──────────────────────────────────────────────────────────────
from app.db.session import init_db

init_db(config.database_url)

# ── 4. ML services — MUST come before importing anything that touches FAISS ───
# Load order matters on Apple Silicon: FAISS-CPU and PyTorch both link
# against BLAS/LAPACK (Accelerate/OpenBLAS) and fight over thread pools and
# globals at first touch on arm64 macOS — initialising FAISS first then
# loading torch+MPS reliably segfaults during the first MPS kernel JIT.
# So we import + load the embedder BEFORE `app.services.importer`,
# `app.services.faiss_index`, `app.services.sync`, etc. (any of which
# transitively pulls in the `faiss` C extension).
#
# Strategy: try to load real models at startup. If load fails (missing
# weights, missing optional deps, broken install), fall back to mock so
# the app still starts up and the user can browse / queue imports.
use_mock = os.environ.get("TEXTILE_USE_MOCK_ML", "").lower() == "true"

from app.services.embedder import init_embedder, MockEmbedder, FashionClipEmbedder
from app.services.ocr import init_ocr, MockOcrService, PaddleOcrService
from app.exceptions import ModelNotAvailableError, OcrModelNotAvailableError

embedder = init_embedder(
    cache_dir = config.models_dir,
    use_mock  = use_mock,
)
if isinstance(embedder, FashionClipEmbedder):
    try:
        embedder.load()
    except ModelNotAvailableError as exc:
        logger.warning(
            "Embedder model unavailable — falling back to MockEmbedder. "
            "Visual search will return arbitrary results until weights are installed.",
            extra={"error": str(exc)},
        )
        embedder = MockEmbedder()

ocr_service = init_ocr(
    model_dir = config.models_dir / "paddleocr",
    use_mock  = use_mock,
)
if isinstance(ocr_service, PaddleOcrService):
    try:
        ocr_service.load()
    except OcrModelNotAvailableError as exc:
        logger.warning(
            "OCR model unavailable — falling back to MockOcrService. "
            "Label fields will not be auto-extracted until OCR is installed.",
            extra={"error": str(exc)},
        )
        ocr_service = MockOcrService()

# ── 5. Crash recovery — reset in-flight imports ───────────────────────────────
# Now safe to pull in importer (which transitively imports faiss).
from app.services.importer import reset_in_flight_images

reset_in_flight_images()

# ── 6. Startup file system sync ────────────────────────────────────────────────
from app.services.sync import startup_sync

_sync_result = startup_sync()
logger.info(
    "Startup sync complete",
    extra={
        "checked":    _sync_result.checked,
        "orphaned":   _sync_result.orphaned,
        "new_queued": _sync_result.new_queued,
    },
)

# ── 7. FAISS index ─────────────────────────────────────────────────────────────
from app.services.faiss_index import init_faiss
from app.exceptions import IndexCorruptedError

try:
    faiss_manager = init_faiss(config.faiss_dir)
except IndexCorruptedError as exc:
    logger.critical(
        "FAISS index corrupted — rebuilding from DB",
        extra={"error": str(exc)},
    )
    # TODO Phase 4: implement rebuild_faiss_from_db()
    from app.services.faiss_index import FaissIndexManager
    faiss_manager = FaissIndexManager(config.faiss_dir)
    faiss_manager._create_flat()  # type: ignore[attr-defined]

# ── 8. Import pipeline ─────────────────────────────────────────────────────────
from app.services.importer import init_importer
from app.api.import_ import set_worker

importer = init_importer(
    embedder       = embedder,
    ocr            = ocr_service,
    faiss_index    = faiss_manager,
    thumbnail_dir  = config.thumbnail_dir,
    disk_warning_mb= float(500),
)
set_worker(importer)

# Auto-start worker if there are queued images
from sqlalchemy import select, func
from app.db.session import get_session
from app.db.models import Image as ImageModel

with get_session() as session:
    queued: int = session.scalar(
        select(func.count()).where(ImageModel.import_status == "queued")
    ) or 0

if queued > 0:
    logger.info("Auto-starting import worker", extra={"queued": queued})
    importer.start()

# ── 9. Wire search API deps ────────────────────────────────────────────────────
from app.api.images import set_search_deps
set_search_deps(embedder=embedder, faiss=faiss_manager)

# ── 10. FastAPI app + uvicorn ──────────────────────────────────────────────────
from app import create_app
import uvicorn

app = create_app()

if __name__ == "__main__":
    logger.info("Starting uvicorn", extra={"host": "127.0.0.1", "port": config.port})
    uvicorn.run(
        app,
        host      = "127.0.0.1",
        port      = config.port,
        log_level = "warning",
        access_log= False,
    )
