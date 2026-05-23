"""
Duplicates API — list flagged pairs, mark resolved.
Pairs are written by the import pipeline (MD5 exact match)
and by the background cosine similarity scan (Phase 4).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Duplicate, Image, TextileMetadata
from app.db.session import db_session

logger = logging.getLogger(__name__)
router = APIRouter()


class DuplicateImageInfo(BaseModel):
    id:             int
    filename:       str
    file_path:      str
    thumbnail_path: str | None
    file_size_bytes:int | None
    date_added:     str
    folder_name:    str | None


class DuplicatePairResponse(BaseModel):
    id:          int
    image_a:     DuplicateImageInfo
    image_b:     DuplicateImageInfo
    similarity:  float
    match_type:  str
    resolved:    bool


def _image_info(img: Image, session: Session) -> DuplicateImageInfo:
    folder = img.root_folder if img.root_folder else None
    return DuplicateImageInfo(
        id             = img.id,
        filename       = img.filename,
        file_path      = img.file_path,
        thumbnail_path = img.thumbnail_path,
        file_size_bytes= img.file_size_bytes,
        date_added     = img.date_added.isoformat() if img.date_added else "",
        folder_name    = folder.display_name if folder else None,
    )


@router.get("/duplicates", response_model=list[DuplicatePairResponse])
def list_duplicates(
    include_resolved: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(db_session),
) -> list[DuplicatePairResponse]:
    q = select(Duplicate)
    if not include_resolved:
        q = q.where(Duplicate.resolved == False)   # noqa: E712
    q = q.order_by(Duplicate.similarity.desc()).offset(offset).limit(limit)

    pairs = session.scalars(q).all()
    result: list[DuplicatePairResponse] = []

    for pair in pairs:
        img_a = session.get(Image, pair.image_id_a)
        img_b = session.get(Image, pair.image_id_b)
        if img_a is None or img_b is None:
            continue
        result.append(DuplicatePairResponse(
            id         = pair.id,
            image_a    = _image_info(img_a, session),
            image_b    = _image_info(img_b, session),
            similarity = pair.similarity,
            match_type = pair.match_type,
            resolved   = pair.resolved,
        ))

    return result


@router.post("/duplicates/{pair_id}/resolve")
def resolve_pair(
    pair_id: int,
    session: Session = Depends(db_session),
) -> dict[str, str]:
    pair = session.get(Duplicate, pair_id)
    if pair is None:
        raise HTTPException(status_code=404, detail=f"Duplicate pair {pair_id} not found")
    pair.resolved = True
    return {"status": "resolved"}


@router.post("/duplicates/resolve-all")
def resolve_all(session: Session = Depends(db_session)) -> dict[str, int]:
    result = session.execute(
        update(Duplicate).where(Duplicate.resolved == False).values(resolved=True)  # noqa: E712
    )
    count: int = result.rowcount
    logger.info("All duplicate pairs resolved", extra={"count": count})
    return {"resolved": count}


@router.get("/duplicates/count")
def count_pending(session: Session = Depends(db_session)) -> dict[str, int]:
    from sqlalchemy import func
    count = session.scalar(
        select(func.count()).where(Duplicate.resolved == False)  # noqa: E712
    ) or 0
    return {"pending": count}
