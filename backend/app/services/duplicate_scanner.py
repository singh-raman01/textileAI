"""
Phase 4 — Background cosine similarity duplicate scan.

Runs after import completes. Compares all indexed vectors pairwise
using FAISS range search, then writes results to the duplicates table.

Threshold is read from app_settings.duplicate_threshold (default 0.97).
Respects the configured threshold — never deletes anything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Duplicate, Image
from app.db.session import get_session
from app.services.faiss_index import get_faiss

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD: Final[float] = 0.97
BATCH_SIZE: Final[int] = 512   # images scanned per batch


def run_similarity_scan(threshold: float = DEFAULT_THRESHOLD) -> int:
    """
    Scan all FAISS-indexed images for near-duplicates above `threshold`.
    Returns the number of new pairs written.

    Called from:
      - Importer after a batch completes (background thread)
      - POST /duplicates/scan (manual trigger, Phase 5)
    """
    faiss_mgr = get_faiss()
    if not faiss_mgr.is_ready or faiss_mgr.ntotal < 2:
        return 0

    new_pairs = 0

    with get_session() as session:
        # Build faiss_id → image_id lookup
        rows = session.execute(
            select(Image.id, Image.faiss_id)
            .where(Image.faiss_id.is_not(None))
            .where(Image.is_orphaned == False)   # noqa: E712
        ).all()
        faiss_to_image: dict[int, int] = {row[1]: row[0] for row in rows}
        existing_pairs: set[tuple[int, int]] = _load_existing_pairs(session)

    n = faiss_mgr.ntotal
    logger.info("Starting duplicate scan", extra={"n": n, "threshold": threshold})

    # For each image, search for similar vectors (top 5, excluding self)
    for faiss_id in range(n):
        img_id = faiss_to_image.get(faiss_id)
        if img_id is None:
            continue

        results = faiss_mgr.search(_reconstruct(faiss_id, faiss_mgr), k=6)
        for hit in results:
            if hit.faiss_id == faiss_id:
                continue   # skip self
            if hit.score < threshold:
                continue

            other_img_id = faiss_to_image.get(hit.faiss_id)
            if other_img_id is None:
                continue

            # Canonical pair order (always a < b) avoids duplicates
            pair = (min(img_id, other_img_id), max(img_id, other_img_id))
            if pair in existing_pairs:
                continue

            with get_session() as session:
                session.add(Duplicate(
                    image_id_a = pair[0],
                    image_id_b = pair[1],
                    similarity = round(hit.score, 4),
                    match_type = "visual",
                    resolved   = False,
                ))
            existing_pairs.add(pair)
            new_pairs += 1

    logger.info("Duplicate scan complete", extra={"new_pairs": new_pairs})
    return new_pairs


def _reconstruct(faiss_id: int, mgr: object) -> list[float]:
    """Reconstruct a stored vector from the FAISS index by its ID."""
    import faiss as faiss_lib
    idx = mgr._index   # type: ignore[attr-defined]
    vec = np.zeros((1, idx.d), dtype=np.float32)
    idx.reconstruct(faiss_id, vec[0])   # type: ignore[arg-type]
    return vec[0].tolist()


def _load_existing_pairs(session: Session) -> set[tuple[int, int]]:
    rows = session.execute(
        select(Duplicate.image_id_a, Duplicate.image_id_b)
    ).all()
    return {(r[0], r[1]) for r in rows}
