"""
TextileSearch — ORM Models (Phase 1 canonical version)

Column naming convention (strict, no synonyms):
  - file_path/folder_path : absolute filesystem path
  - file_md5      : MD5 hex digest of file contents
  - import_status : queued | processing | done | failed
  - is_orphaned   : file no longer on disk
  - is_available  : watched folder currently accessible

All timestamps are stored as UTC, exposed as datetime without timezone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


IMPORT_STATUS_QUEUED: Final[str] = "queued"
IMPORT_STATUS_PROCESSING: Final[str] = "processing"
IMPORT_STATUS_DONE: Final[str] = "done"
IMPORT_STATUS_FAILED: Final[str] = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# Library management
# ─────────────────────────────────────────────────────────────────────────────

class WatchedFolder(Base):
    __tablename__ = "watched_folders"

    id:           Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    folder_path:  Mapped[str]        = mapped_column(String(1024), nullable=False, unique=True)
    display_name: Mapped[str]        = mapped_column(String(256), nullable=False, default="")
    is_available: Mapped[bool]       = mapped_column(Boolean, nullable=False, default=True)
    added_at:     Mapped[datetime]   = mapped_column(DateTime, server_default=func.now())

    images: Mapped[list[Image]] = relationship("Image", back_populates="root_folder")


class Image(Base):
    __tablename__ = "images"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path:       Mapped[str]           = mapped_column(String(1024), nullable=False, unique=True)
    filename:        Mapped[str]           = mapped_column(String(512), nullable=False)
    root_folder_id:  Mapped[int | None]    = mapped_column(Integer, ForeignKey("watched_folders.id"), index=True)
    relative_path:   Mapped[str | None]    = mapped_column(String(1024))
    file_hash:       Mapped[str | None]    = mapped_column(String(64), index=True)
    thumbnail_path:  Mapped[str | None]    = mapped_column(String(1024))
    faiss_id:        Mapped[int | None]    = mapped_column(Integer, unique=True, index=True)
    model_version:   Mapped[str | None]    = mapped_column(String(128))
    file_size_bytes: Mapped[int | None]    = mapped_column(Integer)
    image_width_px:  Mapped[int | None]    = mapped_column(Integer)
    image_height_px: Mapped[int | None]    = mapped_column(Integer)
    is_orphaned:     Mapped[bool]          = mapped_column(Boolean, nullable=False, default=False, index=True)
    import_status:   Mapped[str]           = mapped_column(String(32), nullable=False, default=IMPORT_STATUS_QUEUED, index=True)
    import_error:    Mapped[str | None]    = mapped_column(Text)
    date_added:      Mapped[datetime]      = mapped_column(DateTime, server_default=func.now(), index=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime)

    root_folder:      Mapped[WatchedFolder | None]  = relationship("WatchedFolder", back_populates="images")
    textile_metadata: Mapped[TextileMetadata | None] = relationship("TextileMetadata", back_populates="image", uselist=False)
    image_tags:       Mapped[list[ImageTag]]          = relationship("ImageTag", back_populates="image")
    duplicates_a:     Mapped[list[Duplicate]]         = relationship("Duplicate", foreign_keys="Duplicate.image_id_a")
    duplicates_b:     Mapped[list[Duplicate]]         = relationship("Duplicate", foreign_keys="Duplicate.image_id_b")


# ─────────────────────────────────────────────────────────────────────────────
# Textile metadata
# ─────────────────────────────────────────────────────────────────────────────

class TextileMetadata(Base):
    __tablename__ = "textile_metadata"

    id:       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(Integer, ForeignKey("images.id"), unique=True, nullable=False)

    raw_ocr_text: Mapped[str | None] = mapped_column(Text)

    # Supplier — links to Supplier table; raw string always stored for audit
    supplier:            Mapped[str | None]   = mapped_column(String(256), index=True)
    supplier_confidence: Mapped[float | None] = mapped_column(Float)

    item_no:   Mapped[str | None] = mapped_column(String(128), index=True)
    order_no:  Mapped[str | None] = mapped_column(String(128), index=True)

    fabric_type:  Mapped[str | None]   = mapped_column(String(128), index=True)
    construction: Mapped[str | None]   = mapped_column(String(256))

    # Dimensions
    width_min:   Mapped[float | None] = mapped_column(Float)
    width_max:   Mapped[float | None] = mapped_column(Float)
    width_unit:  Mapped[str | None]   = mapped_column(String(8))   # "IN" | "CM"

    # Weight
    weight_gsm:    Mapped[float | None] = mapped_column(Float)
    weight_gyd:    Mapped[float | None] = mapped_column(Float)
    tolerance_pct: Mapped[float | None] = mapped_column(Float)

    # Confidence / review flags
    needs_review:      Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    no_label_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    image:        Mapped[Image]                  = relationship("Image", back_populates="textile_metadata")
    compositions: Mapped[list[FabricComposition]] = relationship("FabricComposition", back_populates="textile_metadata")


class FabricComposition(Base):
    __tablename__ = "fabric_compositions"

    id:              Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    metadata_id:     Mapped[int]   = mapped_column(Integer, ForeignKey("textile_metadata.id"), nullable=False, index=True)
    material:        Mapped[str]   = mapped_column(String(128), nullable=False)    # normalised
    material_raw:    Mapped[str]   = mapped_column(String(128), nullable=False)    # as-found in OCR
    percentage:      Mapped[float] = mapped_column(Float, nullable=False)
    confidence_tier: Mapped[int]   = mapped_column(Integer, nullable=False)        # 1 | 2 | 3

    textile_metadata: Mapped[TextileMetadata] = relationship("TextileMetadata", back_populates="compositions")


# ─────────────────────────────────────────────────────────────────────────────
# Supplier deduplication
# ─────────────────────────────────────────────────────────────────────────────

class Supplier(Base):
    __tablename__ = "suppliers"

    id:           Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical:    Mapped[str]      = mapped_column(String(256), nullable=False, unique=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    aliases: Mapped[list[SupplierAlias]] = relationship("SupplierAlias", back_populates="supplier")


class SupplierAlias(Base):
    __tablename__ = "supplier_aliases"

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False)
    alias:       Mapped[str] = mapped_column(String(256), nullable=False, unique=True)

    supplier: Mapped[Supplier] = relationship("Supplier", back_populates="aliases")


class MaterialAlias(Base):
    __tablename__ = "material_aliases"

    id:        Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias:     Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    canonical: Mapped[str] = mapped_column(String(128), nullable=False)


class FabricType(Base):
    __tablename__ = "fabric_types"

    id:   Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tags (auto-taxonomy from folder paths)
# ─────────────────────────────────────────────────────────────────────────────

class Tag(Base):
    __tablename__ = "tags"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    is_auto:    Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    image_tags: Mapped[list[ImageTag]] = relationship("ImageTag", back_populates="tag")


class ImageTag(Base):
    __tablename__ = "image_tags"
    __table_args__ = (UniqueConstraint("image_id", "tag_id"),)

    id:       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(Integer, ForeignKey("images.id"), nullable=False)
    tag_id:   Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False)

    image: Mapped[Image] = relationship("Image", back_populates="image_tags")
    tag:   Mapped[Tag]   = relationship("Tag", back_populates="image_tags")


# ─────────────────────────────────────────────────────────────────────────────
# Duplicates
# ─────────────────────────────────────────────────────────────────────────────

class Duplicate(Base):
    __tablename__ = "duplicates"
    __table_args__ = (UniqueConstraint("image_id_a", "image_id_b"),)

    id:           Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    image_id_a:   Mapped[int]         = mapped_column(Integer, ForeignKey("images.id"), nullable=False)
    image_id_b:   Mapped[int]         = mapped_column(Integer, ForeignKey("images.id"), nullable=False)
    is_exact_md5: Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False)
    similarity:   Mapped[float | None] = mapped_column(Float)   # cosine similarity for near-dupes
    match_type:   Mapped[str]          = mapped_column(String(16), nullable=False, default='exact')
    resolved:     Mapped[bool]         = mapped_column(Boolean, nullable=False, default=False)
    detected_at:  Mapped[datetime]     = mapped_column(DateTime, server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Search history
# ─────────────────────────────────────────────────────────────────────────────

class SearchHistory(Base):
    __tablename__ = "search_history"

    id:             Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_image_path: Mapped[str | None] = mapped_column(String(1024))
    k:              Mapped[int | None]   = mapped_column(Integer)
    result_count:   Mapped[int | None]   = mapped_column(Integer)
    top_result_ids: Mapped[str | None]   = mapped_column(Text)    # comma-separated image IDs
    searched_at:    Mapped[datetime]     = mapped_column(DateTime, server_default=func.now(), index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────────────────

class AppSetting(Base):
    __tablename__ = "app_settings"

    key:   Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    version:     Mapped[str]      = mapped_column(String(32), nullable=False)
    applied_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    description: Mapped[str]      = mapped_column(Text, nullable=False, default="")
