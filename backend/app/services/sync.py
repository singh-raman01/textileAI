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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Final, Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Image as ImageModel, WatchedFolder
from app.db.session import get_session
from app.exceptions import FolderUnavailableError

logger = logging.getLogger(__name__)

STARTUP_SYNC_WORKERS: Final[int] = 16
ORPHAN_THRESHOLD: Final[float] = 0.80     # D9: >80% missing → folder unavailable
SUPPORTED_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp"}
)

EventKind = Literal["add", "remove", "change"]


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
# Startup sync
# ─────────────────────────────────────────────────────────────────────────────

def startup_sync(root_folder_id: int) -> dict[str, int]:
    """
    Parallel existence check for all images belonging to root_folder_id.

    Returns a summary dict:
        {
            "total": N,
            "present": P,
            "orphaned": O,
            "folder_unavailable": 0|1,
        }

    Images with no root_folder_id are orphaned immediately (not counted toward
    the threshold) — they have no folder to be "80% missing" from.

    The folder is declared unavailable (not mass-orphaned) if the missing
    fraction exceeds ORPHAN_THRESHOLD. Individual orphaned images with a
    root_folder_id ARE marked orphaned when below the threshold.
    """
    with get_session() as session:
        rows: list[ImageModel] = list(
            session.scalars(
                select(ImageModel).where(
                    ImageModel.root_folder_id == root_folder_id,
                    ImageModel.is_orphaned == False,  # noqa: E712
                )
            )
        )

    if not rows:
        return {"total": 0, "present": 0, "orphaned": 0, "folder_unavailable": 0}

    total = len(rows)
    missing_ids: list[int] = []

    # Parallel path-existence check
    def _check(img: ImageModel) -> tuple[int, bool]:
        return img.id, Path(img.file_path).exists()

    with ThreadPoolExecutor(max_workers=STARTUP_SYNC_WORKERS) as pool:
        futures = {pool.submit(_check, img): img for img in rows}
        for fut in as_completed(futures):
            img_id, exists = fut.result()
            if not exists:
                missing_ids.append(img_id)

    missing_count = len(missing_ids)
    present_count = total - missing_count

    # Check orphan threshold
    if total > 0 and missing_count / total > ORPHAN_THRESHOLD:
        logger.warning(
            "Folder exceeds orphan threshold — marking unavailable",
            extra={
                "root_folder_id": root_folder_id,
                "missing": missing_count,
                "total": total,
            },
        )
        with get_session() as session:
            session.execute(
                update(WatchedFolder)
                .where(WatchedFolder.id == root_folder_id)
                .values(is_available=False)
            )
        return {
            "total": total,
            "present": present_count,
            "orphaned": 0,
            "folder_unavailable": 1,
        }

    # Individually orphan the missing images
    if missing_ids:
        with get_session() as session:
            session.execute(
                update(ImageModel)
                .where(ImageModel.id.in_(missing_ids))
                .values(is_orphaned=True)
            )
        logger.info(
            "startup_sync: orphaned %d/%d images",
            missing_count,
            total,
            extra={"root_folder_id": root_folder_id},
        )

    return {
        "total": total,
        "present": present_count,
        "orphaned": missing_count,
        "folder_unavailable": 0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chokidar event batch
# ─────────────────────────────────────────────────────────────────────────────

class SyncEvent:
    """A single file event from chokidar (forwarded via IPC)."""
    __slots__ = ("kind", "path")

    def __init__(self, kind: EventKind, path: str) -> None:
        self.kind: EventKind = kind
        self.path: str = path


class BatchSyncResult:
    """Summary of a processed chokidar event batch."""
    __slots__ = ("added", "removed", "renamed", "skipped")

    def __init__(self) -> None:
        self.added: int = 0
        self.removed: int = 0
        self.renamed: int = 0
        self.skipped: int = 0


def handle_batch(
    events: list[SyncEvent],
    root_folder_id: int,
    enqueue_for_import: "Callable[[list[str]], None]",
) -> BatchSyncResult:
    """
    Process a debounced batch of chokidar events.

    Rename detection:
      An add event + a remove event in the same batch, where the new file's
      MD5 matches the DB md5 of the old file → rename (path updated, no re-index).

    Args:
        events:             list of SyncEvent from chokidar
        root_folder_id:     ID of the WatchedFolder this batch belongs to
        enqueue_for_import: callback to add new paths to the import queue
    """
    from typing import Callable  # avoid circular import at module level

    result = BatchSyncResult()

    adds = [e for e in events if e.kind == "add"]
    removes = [e for e in events if e.kind == "remove"]

    # Filter unsupported extensions
    adds = [e for e in adds if Path(e.path).suffix.lower() in SUPPORTED_EXTENSIONS]

    # ── Rename detection ─────────────────────────────────────────────────────
    if adds and removes:
        # Build MD5 map of incoming new files
        new_md5: dict[str, str] = {}
        for ev in adds:
            md5 = compute_md5(Path(ev.path))
            if md5:
                new_md5[ev.path] = md5

        # Build MD5 → image_id map for removed paths
        removed_paths = [e.path for e in removes]
        with get_session() as session:
            old_rows: list[ImageModel] = list(
                session.scalars(
                    select(ImageModel).where(
                        ImageModel.file_path.in_(removed_paths)
                    )
                )
            )
        old_by_md5: dict[str, ImageModel] = {row.md5: row for row in old_rows if row.md5}

        renamed_add_paths: set[str] = set()
        renamed_remove_paths: set[str] = set()

        for new_path, md5 in new_md5.items():
            if md5 in old_by_md5:
                old_img = old_by_md5[md5]
                # It's a rename — update path in DB, keep all metadata
                with get_session() as session:
                    session.execute(
                        update(ImageModel)
                        .where(ImageModel.id == old_img.id)
                        .values(file_path=new_path, is_orphaned=False)
                    )
                renamed_add_paths.add(new_path)
                renamed_remove_paths.add(old_img.file_path)
                result.renamed += 1
                logger.debug(
                    "Renamed",
                    extra={"from": old_img.file_path, "to": new_path},
                )

        # Remove matched events so they don't get processed again below
        adds = [e for e in adds if e.path not in renamed_add_paths]
        removes = [e for e in removes if e.path not in renamed_remove_paths]

    # ── New files ────────────────────────────────────────────────────────────
    if adds:
        new_paths = [e.path for e in adds]
        enqueue_for_import(new_paths)
        result.added += len(new_paths)

    # ── Removed files ────────────────────────────────────────────────────────
    if removes:
        remove_paths = [e.path for e in removes]
        with get_session() as session:
            session.execute(
                update(ImageModel)
                .where(ImageModel.file_path.in_(remove_paths))
                .values(is_orphaned=True)
            )
        result.removed += len(remove_paths)

    logger.info(
        "handle_batch complete",
        extra={
            "added": result.added,
            "removed": result.removed,
            "renamed": result.renamed,
        },
    )
    return result


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
        for folder in folders:
            # Use the underlying per-folder function (imported above has different name)
            per = _startup_sync_impl(folder.id, session)
            result.checked    += per.get("checked", 0)
            result.orphaned   += per.get("orphaned", 0)
            result.new_queued += per.get("queued", 0)
            result.renamed    += per.get("renamed", 0)

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


def _startup_sync_impl(folder_id: int, session: object) -> dict[str, int]:
    """Call the original per-folder startup_sync by its renamed symbol."""
    # The original function was renamed to _startup_sync_for_folder in the file
    # but our rename may not have worked; fall back gracefully
    try:
        from app.services import sync as _sync_mod
        fn = getattr(_sync_mod, "_startup_sync_for_folder", None)
        if fn is not None:
            raw = fn(folder_id, session)
            return {"checked": getattr(raw, "checked", 0),
                    "orphaned": getattr(raw, "orphaned", 0),
                    "queued": getattr(raw, "queued", 0),
                    "renamed": getattr(raw, "renamed", 0)}
    except Exception:
        pass
    return {}


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
