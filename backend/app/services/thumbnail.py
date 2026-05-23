"""
TextileSearch — Thumbnail Generator

Generates thumbnails atomically (write to .tmp, rename).
Supports large images (>25 MB) via Pillow's draft() API to avoid OOM.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError  # type: ignore[import-untyped]

from app.exceptions import ImageReadError

logger = logging.getLogger(__name__)

DEFAULT_SIZE: Final[tuple[int, int]] = (256, 256)
LARGE_IMAGE_BYTES: Final[int] = 25 * 1024 * 1024   # 25 MB — D30
THUMBNAIL_FORMAT: Final[str] = "WEBP"
THUMBNAIL_QUALITY: Final[int] = 85
THUMBNAIL_SUFFIX: Final[str] = ".webp"


class ThumbnailService:
    """
    Generates WebP thumbnails from fabric images.
    Atomic writes: tmp file is renamed into place so a partial thumbnail
    is never visible to the search UI.
    """

    def __init__(self, thumbnail_dir: Path) -> None:
        self._thumbnail_dir = thumbnail_dir
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)

    def thumbnail_path(self, image_id: int) -> Path:
        """Deterministic path for a given image DB ID."""
        # Shard into 256 subdirs to avoid huge directories
        shard = f"{image_id % 256:02x}"
        return self._thumbnail_dir / shard / f"{image_id}{THUMBNAIL_SUFFIX}"

    def generate(
        self,
        image_path: Path,
        image_id: int,
        size: tuple[int, int] = DEFAULT_SIZE,
    ) -> Path:
        """
        Generate a thumbnail and write it atomically.
        Returns the thumbnail path on success.
        Raises ImageReadError if the source image cannot be opened.
        """
        dest = self.thumbnail_path(image_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")

        try:
            file_size = image_path.stat().st_size
        except OSError as exc:
            raise ImageReadError(str(image_path), str(exc)) from exc

        try:
            with Image.open(image_path) as img:
                # Use draft() for large images to load a reduced-size version
                if file_size > LARGE_IMAGE_BYTES:
                    img.draft("RGB", size)
                    logger.debug(
                        "Large image — using draft mode",
                        extra={"path": str(image_path), "bytes": file_size},
                    )

                img_rgb = img.convert("RGB")
                img_rgb.thumbnail(size, Image.LANCZOS)  # type: ignore[attr-defined]

                img_rgb.save(tmp, format=THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY)
        except UnidentifiedImageError as exc:
            tmp.unlink(missing_ok=True)
            raise ImageReadError(str(image_path), "unrecognised image format") from exc
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise ImageReadError(str(image_path), str(exc)) from exc

        # fsync + atomic rename
        try:
            with tmp.open("rb") as fh:
                os.fsync(fh.fileno())
        except OSError:
            pass   # fsync failure is non-fatal for thumbnails

        tmp.rename(dest)
        return dest

    def exists(self, image_id: int) -> bool:
        return self.thumbnail_path(image_id).exists()

    def delete(self, image_id: int) -> None:
        self.thumbnail_path(image_id).unlink(missing_ok=True)
