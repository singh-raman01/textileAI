"""
TextileSearch — Images API

POST /images/search   Visual similarity search (requires query image)
POST /images/browse   Filter-only search (no query image, ≥1 filter required)
GET  /images/{id}     Fetch single image record with full metadata
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, and_
from sqlalchemy.orm import Session

from app.db.models import Image as ImageModel, TextileMetadata
from app.db.session import db_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])

# Lazy reference — set by app factory after embedder + faiss are ready
_embedder: object | None = None
_faiss: object | None = None


def set_search_deps(embedder: object, faiss: object) -> None:
    global _embedder, _faiss
    _embedder = embedder
    _faiss = faiss


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CompositionItem(BaseModel):
    material: str
    material_raw: str
    percentage: float
    confidence_tier: int


class ImageMetadataResponse(BaseModel):
    supplier: str | None
    item_no: str | None
    order_no: str | None
    fabric_type: str | None
    construction: str | None
    width_min: float | None
    width_max: float | None
    width_unit: str | None
    weight_gsm: float | None
    weight_gyd: float | None
    tolerance_pct: float | None
    needs_review: bool
    no_label_detected: bool
    composition: list[CompositionItem]


class ImageResponse(BaseModel):
    id: int
    abs_path: str
    filename: str
    thumbnail_path: str | None
    import_status: str
    is_orphaned: bool
    date_added: str | None
    faiss_id: int | None
    model_version: str | None
    # Extended fields (populated by GET /images/{id})
    file_hash: str | None = None
    file_size_bytes: int | None = None
    width_px: int | None = None
    height_px: int | None = None
    relative_path: str | None = None
    folder_name: str | None = None
    metadata: ImageMetadataResponse | None


class SearchResultItem(BaseModel):
    image: ImageResponse
    score: float | None = None   # None for browse-mode results


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    total: int
    truncated: bool          # True if k > total images (D20)


# ---------------------------------------------------------------------------
# Filter model (shared between search + browse)
# ---------------------------------------------------------------------------

class ImageFilters(BaseModel):
    supplier: str | None = None
    fabric_type: str | None = None
    min_gsm: float | None = None
    max_gsm: float | None = None
    min_width: float | None = None
    max_width: float | None = None
    needs_review: bool | None = None
    verified_only: bool = False       # exclude Tier 2/3 when True
    item_no_pattern: str | None = None  # partial match on item_no
    include_orphaned: bool = False      # include orphaned images in results
    sort_by: str = "date_desc"          # date_desc | date_asc | filename_asc | filename_desc | supplier | weight_gsm


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _row_to_response(image: ImageModel, include_extended: bool = False) -> ImageResponse:
    meta_out: ImageMetadataResponse | None = None
    if image.textile_metadata is not None:
        m = image.textile_metadata
        meta_out = ImageMetadataResponse(
            supplier=m.supplier,
            item_no=m.item_no,
            order_no=m.order_no,
            fabric_type=m.fabric_type,
            construction=m.construction,
            width_min=m.width_min,
            width_max=m.width_max,
            width_unit=m.width_unit,
            weight_gsm=m.weight_gsm,
            weight_gyd=m.weight_gyd,
            tolerance_pct=m.tolerance_pct,
            needs_review=m.needs_review,
            no_label_detected=m.no_label_detected,
            composition=[
                CompositionItem(
                    material=c.material,
                    material_raw=c.material_raw,
                    percentage=c.percentage,
                    confidence_tier=c.confidence_tier,
                )
                for c in m.compositions
            ],
        )
    folder_name: str | None = None
    if include_extended and image.root_folder is not None:
        folder_name = image.root_folder.display_name
    return ImageResponse(
        id=image.id,
        abs_path=image.file_path,
        filename=image.filename,
        thumbnail_path=image.thumbnail_path,
        import_status=image.import_status,
        is_orphaned=image.is_orphaned,
        date_added=str(image.date_added) if image.date_added else None,
        faiss_id=image.faiss_id,
        model_version=image.model_version,
        file_hash=image.file_hash if include_extended else None,
        file_size_bytes=image.file_size_bytes if include_extended else None,
        width_px=image.image_width_px if include_extended else None,
        height_px=image.image_height_px if include_extended else None,
        relative_path=image.relative_path if include_extended else None,
        folder_name=folder_name,
        metadata=meta_out,
    )


def _apply_filters(stmt: Any, filters: ImageFilters) -> Any:
    """Apply metadata and image-level filters to a select statement."""
    # Orphan filter — by default exclude orphaned images
    if not filters.include_orphaned:
        stmt = stmt.where(ImageModel.is_orphaned == False)  # noqa: E712

    meta_conditions = []
    if filters.supplier is not None:
        meta_conditions.append(TextileMetadata.supplier.ilike(f"%{filters.supplier}%"))
    if filters.fabric_type is not None:
        meta_conditions.append(TextileMetadata.fabric_type.ilike(f"%{filters.fabric_type}%"))
    if filters.min_gsm is not None:
        meta_conditions.append(TextileMetadata.weight_gsm >= filters.min_gsm)
    if filters.max_gsm is not None:
        meta_conditions.append(TextileMetadata.weight_gsm <= filters.max_gsm)
    if filters.min_width is not None:
        meta_conditions.append(TextileMetadata.width_min >= filters.min_width)
    if filters.max_width is not None:
        meta_conditions.append(TextileMetadata.width_max <= filters.max_width)
    if filters.needs_review is not None:
        meta_conditions.append(TextileMetadata.needs_review == filters.needs_review)
    if filters.verified_only:
        meta_conditions.append(TextileMetadata.needs_review == False)  # noqa: E712
    if filters.item_no_pattern is not None:
        meta_conditions.append(TextileMetadata.item_no.ilike(f"%{filters.item_no_pattern}%"))

    if meta_conditions:
        stmt = stmt.join(ImageModel.textile_metadata).where(and_(*meta_conditions))
    return stmt


def _apply_sort(stmt: Any, sort_by: str) -> Any:
    """Apply sort order to a select statement."""
    from sqlalchemy import asc, desc
    order_map = {
        "date_desc":     desc(ImageModel.date_added),
        "date_asc":      asc(ImageModel.date_added),
        "filename_asc":  asc(ImageModel.filename),
        "filename_desc": desc(ImageModel.filename),
        "supplier":      asc(TextileMetadata.supplier),
        "weight_gsm":    asc(TextileMetadata.weight_gsm),
    }
    order = order_map.get(sort_by, desc(ImageModel.date_added))
    return stmt.order_by(order)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/search", response_model=SearchResponse)
async def visual_search(
    query_image: Annotated[UploadFile, File(description="Query fabric image")],
    k: Annotated[int, Form(ge=1, le=200)] = 20,
    supplier: Annotated[str | None, Form()] = None,
    fabric_type: Annotated[str | None, Form()] = None,
    min_gsm: Annotated[float | None, Form()] = None,
    max_gsm: Annotated[float | None, Form()] = None,
    verified_only: Annotated[bool, Form()] = False,
    session: Annotated[Session, Depends(db_session)] = None,  # type: ignore[assignment]
) -> SearchResponse:
    if _embedder is None or _faiss is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search not ready — ML models not initialised.",
        )

    # Write upload to temp file so embedder can open it
    suffix = Path(query_image.filename or "query.jpg").suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await query_image.read())
        tmp_path = Path(tmp.name)

    from app.exceptions import EmbeddingFailedError, ModelNotAvailableError
    try:
        embedding = _embedder.embed(tmp_path)  # type: ignore[attr-defined]
    except (EmbeddingFailedError, ModelNotAvailableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    filters = ImageFilters(
        supplier=supplier,
        fabric_type=fabric_type,
        min_gsm=min_gsm,
        max_gsm=max_gsm,
        verified_only=verified_only,
    )

    # Search FAISS with k×20 candidates, then post-filter
    candidates = _faiss.search(embedding.vector, k=k * 20)  # type: ignore[attr-defined]
    faiss_ids = [r.faiss_id for r in candidates]
    score_map = {r.faiss_id: r.score for r in candidates}

    stmt = select(ImageModel).where(ImageModel.faiss_id.in_(faiss_ids))
    stmt = _apply_filters(stmt, filters)
    images = list(session.scalars(stmt).all())

    # Re-rank by FAISS score
    images.sort(key=lambda img: score_map.get(img.faiss_id or -1, 0.0), reverse=True)
    images = images[:k]

    total_in_index = _faiss.ntotal  # type: ignore[attr-defined]
    truncated = k >= total_in_index

    return SearchResponse(
        results=[
            SearchResultItem(
                image=_row_to_response(img),
                score=score_map.get(img.faiss_id or -1),
            )
            for img in images
        ],
        total=len(images),
        truncated=truncated,
    )


@router.post("/browse", response_model=SearchResponse)
def browse_images(
    filters: ImageFilters,
    limit: int = 100,
    offset: int = 0,
    session: Annotated[Session, Depends(db_session)] = None,  # type: ignore[assignment]
) -> SearchResponse:
    base = select(ImageModel)
    base = _apply_filters(base, filters)
    base = _apply_sort(base, filters.sort_by)
    count_q = select(func.count()).select_from(base.subquery())

    total = session.scalar(count_q) or 0

    stmt = base.offset(offset).limit(limit)
    images = list(session.scalars(stmt).all())

    return SearchResponse(
        results=[SearchResultItem(image=_row_to_response(img)) for img in images],
        total=total,
        truncated=False,
    )


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(
    image_id: int,
    session: Annotated[Session, Depends(db_session)],
) -> ImageResponse:
    from sqlalchemy.orm import joinedload
    image = session.scalars(
        select(ImageModel)
        .options(joinedload(ImageModel.root_folder))
        .where(ImageModel.id == image_id)
    ).first()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image id={image_id} not found.",
        )
    return _row_to_response(image, include_extended=True)
