"""
Search history API — auto-logged on every search, browseable, re-openable.
Retention: configurable via app_settings.history_retention_days (default 365).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from app.db.models import SearchHistory, Image
from app.db.session import db_session

logger = logging.getLogger(__name__)
router = APIRouter()


class HistoryEntryResponse(BaseModel):
    id:              int
    query_image_path:str
    searched_at:     str
    k:               int
    result_count:    int
    top_result_ids:  list[int]


class LogSearchRequest(BaseModel):
    query_image_path: str
    k:               int
    result_ids:      list[int]   # ordered by similarity, first 20 stored


@router.post("/history", response_model=HistoryEntryResponse)
def log_search(
    body: LogSearchRequest,
    session: Session = Depends(db_session),
) -> HistoryEntryResponse:
    """
    Called by the Electron main process immediately after every search.
    Stores query image path, k, and the ordered result IDs.
    """
    entry = SearchHistory(
        query_image_path = body.query_image_path,
        searched_at      = datetime.now(timezone.utc),
        k                = body.k,
        result_count     = len(body.result_ids),
        top_result_ids   = ",".join(str(i) for i in body.result_ids[:20]),
    )
    session.add(entry)
    session.flush()

    return HistoryEntryResponse(
        id               = entry.id,
        query_image_path = entry.query_image_path,
        searched_at      = entry.searched_at.isoformat(),
        k                = entry.k,
        result_count     = entry.result_count,
        top_result_ids   = body.result_ids[:20],
    )


@router.get("/history", response_model=list[HistoryEntryResponse])
def get_history(
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(db_session),
) -> list[HistoryEntryResponse]:
    """Return search history, newest first."""
    rows = session.scalars(
        select(SearchHistory)
        .order_by(SearchHistory.searched_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        HistoryEntryResponse(
            id               = r.id,
            query_image_path = r.query_image_path,
            searched_at      = r.searched_at.isoformat(),
            k                = r.k,
            result_count     = r.result_count,
            top_result_ids   = [int(x) for x in r.top_result_ids.split(",") if x]
                               if r.top_result_ids else [],
        )
        for r in rows
    ]


@router.delete("/history")
def clear_history(session: Session = Depends(db_session)) -> dict[str, int]:
    """Delete all search history entries."""
    result = session.execute(delete(SearchHistory))
    count: int = result.rowcount
    logger.info("Search history cleared", extra={"count": count})
    return {"deleted": count}


@router.delete("/history/{entry_id}")
def delete_entry(
    entry_id: int,
    session: Session = Depends(db_session),
) -> dict[str, str]:
    entry = session.get(SearchHistory, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"History entry {entry_id} not found")
    session.delete(entry)
    return {"status": "deleted"}
