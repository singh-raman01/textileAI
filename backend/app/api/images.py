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
from sqlalchemy import select, and_
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
    width_min: float | None
    width_max: float | None
    width_unit: str | None
    weight_gsm: float | None
    weight_gyd: float | None
    tolerance_pct: float | None
    needs_review: bool
    composition: list[CompositionItem]


class ImageResponse(BaseModel):
    id: int
    abs_path: str
    filename: str
    thumbnail_path: str | None
    import_status: str
    is_orphaned: bool
    faiss_id: int | None
    model_version: str | None
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
    verified_only: bool = False   # D4: exclude Tier 2/3 when True


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _row_to_response(image: ImageModel) -> ImageResponse:
    meta_out: ImageMetadataResponse | None = None
    if image.textile_metadata is not None:
        m = image.textile_metadata
        meta_out = ImageMetadataResponse(
            supplier=m.supplier,
            item_no=m.item_no,
            order_no=m.order_no,
            fabric_type=m.fabric_type,
            width_min=m.width_min,
            width_max=m.width_max,
            width_unit=m.width_unit,
            weight_gsm=m.weight_gsm,
            weight_gyd=m.weight_gyd,
            tolerance_pct=m.tolerance_pct,
            needs_review=m.needs_review,
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
    return ImageResponse(
        id=image.id,
        abs_path=image.abs_path,
        filename=image.filename,
        thumbnail_path=image.thumbnail_path,
        import_status=image.import_status,
        is_orphaned=image.is_orphaned,
        faiss_id=image.faiss_id,
        model_version=image.model_version,
        metadata=meta_out,
    )


def _apply_filters(stmt: Any, filters: ImageFilters) -> Any:
    """Apply metadata filters to an SQLAlchemy select statement."""
    conditions = []

    if filters.supplier is not None:
        conditions.append(TextileMetadata.supplier.ilike(f"%{filters.supplier}%"))
    if filters.fabric_type is not None:
        conditions.append(TextileMetadata.fabric_type.ilike(f"%{filters.fabric_type}%"))
    if filters.min_gsm is not None:
        conditions.append(TextileMetadata.weight_gsm >= filters.min_gsm)
    if filters.max_gsm is not None:
        conditions.append(TextileMetadata.weight_gsm <= filters.max_gsm)
    if filters.min_width is not None:
        conditions.append(TextileMetadata.width_min >= filters.min_width)
    if filters.max_width is not None:
        conditions.append(TextileMetadata.width_max <= filters.max_width)
    if filters.needs_review is not None:
        conditions.append(TextileMetadata.needs_review == filters.needs_review)
    if filters.verified_only:
        conditions.append(TextileMetadata.needs_review == False)  # noqa: E712

    if conditions:
        stmt = stmt.join(ImageModel.textile_metadata).where(and_(*conditions))
    return stmt


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

    stmt = select(ImageModel).where(
        ImageModel.faiss_id.in_(faiss_ids),
        ImageModel.is_orphaned == False,  # noqa: E712
    )
    stmt = _apply_filters(stmt, filters)
    images = list(session.scalars(stmt).all())

    # Re-rank by FAISS score
    images.sort(key=lambda img: score_map.get(img.faiss_id or -1, 0.0), reverse=True)
    images = images[:k]

    total_in_index = _faiss.stats().total_vectors  # type: ignore[attr-defined]
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
    # D31: browse requires at least one filter
    has_filter = any([
        filters.supplier,
        filters.fabric_type,
        filters.min_gsm,
        filters.max_gsm,
        filters.min_width,
        filters.max_width,
        filters.needs_review is not None,
        filters.verified_only,
    ])
    if not has_filter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Browse mode requires at least one filter. (D31)",
        )

    stmt = select(ImageModel).where(ImageModel.is_orphaned == False)  # noqa: E712
    stmt = _apply_filters(stmt, filters)
    total_stmt = stmt
    stmt = stmt.offset(offset).limit(limit)

    images = list(session.scalars(stmt).all())
    total = session.scalar(
        select(ImageModel.id).where(ImageModel.is_orphaned == False)  # noqa: E712
    )

    return SearchResponse(
        results=[SearchResultItem(image=_row_to_response(img)) for img in images],
        total=len(images),
        truncated=False,
    )


@router.get("/{image_id}", response_model=ImageResponse)
def get_image(
    image_id: int,
    session: Annotated[Session, Depends(db_session)],
) -> ImageResponse:
    image = session.get(ImageModel, image_id)
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Image id={image_id} not found.",
        )
    return _row_to_response(image)
