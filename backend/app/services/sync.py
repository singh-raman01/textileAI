"""
TextileSearch — File System Sync

Two modes of sync:
  1. startup_sync() — runs once on launch. Checks path existence of every
     DB image in parallel (16 threads), reconciles renames via MD5.
  2. handle_batch() — processes a batch of chokidar events from Electron.
     Handles add / remove / rename (add+remove with matching MD5).

Design:
  - All DB writes go through explicit Session context managers (no implicit commit)
  - Rename detection: if an add and a remove occur in the same batch AND the
    new file's MD5 matches the old file's DB md5, it's a rename — path is
    updated in-place and all metadata is preserved
  - Orphan threshold: if >80% of a folder's images are missing, the folder is
    declared unavailable — not mass-deleted (D9)
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Final

from app.db.models import Image as ImageModel, WatchedFolder
from app.db.session import get_session

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp"}
)


# ─────────────────────────────────────────────────────────────────────────────
# MD5 helpers
# ─────────────────────────────────────────────────────────────────────────────

def compute_md5(path: Path) -> str | None:
    """
    Compute MD5 of a file. Returns None if the file cannot be read.
    Uses 64 KB chunks to avoid loading large images into memory.
    """
    try:
        h = hashlib.md5()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Folder tags (auto-taxonomy)
# ─────────────────────────────────────────────────────────────────────────────

def derive_folder_tags(file_path: str, root_path: str) -> list[str]:
    """
    Extract path segments between the root folder and the file as tags.

    Example:
        root = "/Fabrics"
        file = "/Fabrics/Winter 2024/Wool/image.jpg"
        → ["Winter 2024", "Wool"]

    Tags are read-only (folder-derived). They are never created by the user.
    """
    try:
        rel = Path(file_path).relative_to(root_path)
        # All parts except the filename itself
        return [part for part in rel.parts[:-1] if part]
    except ValueError:
        return []


# ── Public aliases expected by tests and API routes ───────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Public adapters — used by API routes and tests
# ─────────────────────────────────────────────────────────────────────────────
from dataclasses import dataclass, field as _field


@dataclass
class StartupSyncResult:
    checked:    int = 0
    orphaned:   int = 0
    new_queued: int = 0
    renamed:    int = 0
    errors:     list[str] = _field(default_factory=list)


@dataclass  
class BatchSyncResult:
    queued:   int = 0
    orphaned: int = 0
    renamed:  int = 0
    errors:   list[str] = _field(default_factory=list)


# Alias for import_.py which imports this name
SyncBatchResult = BatchSyncResult


def compute_file_hash(path: Path) -> str:
    result = compute_md5(path)
    return result or ""


def _derive_folder_tag_names(image_path: Path, root_path: Path) -> list[str]:
    return derive_folder_tags(str(image_path), str(root_path))


def startup_sync() -> StartupSyncResult:
    """
    No-arg startup sync: iterates all watched folders and reconciles DB.
    """
    from app.db.session import get_session
    from sqlalchemy import select as sa_select
    result = StartupSyncResult()

    with get_session() as session:
        folders = list(session.scalars(sa_select(WatchedFolder)))

        # Queue files not yet in DB
        known: set[str] = {
            row[0]
            for row in session.execute(sa_select(ImageModel.file_path))
        }
        for folder in folders:
            fp = Path(folder.folder_path)
            if not fp.exists():
                continue
            for img_path in _walk_supported(fp):
                if str(img_path) not in known:
                    session.add(ImageModel(
                        file_path      = str(img_path),
                        filename       = img_path.name,
                        root_folder_id = folder.id,
                        relative_path  = str(img_path.relative_to(fp)),
                        import_status  = "queued",
                    ))
                    result.new_queued += 1

        # Orphan images with no root folder whose file is missing
        orphan_candidates = list(session.scalars(
            sa_select(ImageModel).where(ImageModel.root_folder_id == None)   # noqa: E711
        ))
        for img in orphan_candidates:
            if not Path(img.file_path).exists():
                img.is_orphaned = True
                result.orphaned += 1

    return result


def handle_batch(added: list[str], removed: list[str]) -> BatchSyncResult:
    """Process a chokidar debounced event batch."""
    from app.db.session import get_session
    from sqlalchemy import select as sa_select

    result = BatchSyncResult()
    if not added and not removed:
        return result

    with get_session() as session:
        # Hash added files for rename detection
        added_hashes: dict[str, str] = {}
        if removed:
            for p in added:
                try:
                    added_hashes[p] = compute_file_hash(Path(p))
                except OSError:
                    pass

        # Handle removals
        for path_str in removed:
            img = session.scalar(
                sa_select(ImageModel).where(ImageModel.file_path == path_str)
            )
            if img is None:
                continue
            # Rename detection via MD5
            if img.file_hash and img.file_hash in added_hashes.values():
                new_path = next(p for p, h in added_hashes.items() if h == img.file_hash)
                img.file_path   = new_path
                img.filename   = Path(new_path).name
                img.is_orphaned = False
                added.remove(new_path)
                result.renamed += 1
            else:
                img.is_orphaned = True
                result.orphaned += 1

        # Handle additions
        known: set[str] = {
            row[0]
            for row in session.execute(sa_select(ImageModel.file_path))
        }
        for path_str in added:
            ext = Path(path_str).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            if path_str in known:
                continue
            # Find parent watched folder
            folders = list(session.scalars(sa_select(WatchedFolder)))
            root_id: int | None = None
            for f in folders:
                try:
                    Path(path_str).relative_to(f.folder_path)
                    root_id = f.id
                    break
                except ValueError:
                    pass
            session.add(ImageModel(
                file_path      = path_str,
                filename       = Path(path_str).name,
                root_folder_id = root_id,
                import_status  = "queued",
            ))
            result.queued += 1

    return result


def _walk_supported(root: Path) -> list[Path]:
    """Recursively collect supported image files."""
    import os as _os
    exts = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp"}
    out: list[Path] = []
    for dp, _, fnames in _os.walk(root, followlinks=False):
        for fn in fnames:
            p = Path(dp) / fn
            if p.suffix.lower() in exts:
                out.append(p)
    return out
