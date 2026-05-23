"""Unit tests for ThumbnailService error paths."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.exceptions import ImageReadError
from app.services.thumbnail import ThumbnailService


class TestThumbnailService:
    def test_nonexistent_image_raises(self, tmp_path: Path) -> None:
        svc = ThumbnailService(tmp_path / "thumbnails")
        with pytest.raises(ImageReadError):
            svc.generate(tmp_path / "nonexistent.jpg", image_id=1)

    def test_invalid_image_raises(self, tmp_path: Path) -> None:
        svc = ThumbnailService(tmp_path / "thumbnails")
        src = tmp_path / "invalid.jpg"
        src.write_bytes(b"not an image")
        with pytest.raises(ImageReadError, match="unrecognised image format"):
            svc.generate(src, image_id=2)

    def test_valid_image(self, tmp_path: Path) -> None:
        svc = ThumbnailService(tmp_path / "thumbnails")
        src = tmp_path / "valid.jpg"
        Image.new("RGB", (200, 200), color="blue").save(str(src))
        result = svc.generate(src, image_id=3)
        assert result.exists()
        assert svc.exists(3) is True
        thumb = Image.open(result)
        assert thumb.width <= 256 and thumb.height <= 256

    def test_delete_thumbnail(self, tmp_path: Path) -> None:
        svc = ThumbnailService(tmp_path / "thumbnails")
        src = tmp_path / "delete_src.jpg"
        Image.new("RGB", (100, 100), color="red").save(str(src))
        result = svc.generate(src, image_id=4)
        assert result.exists()
        svc.delete(4)
        assert svc.exists(4) is False

    def test_delete_nonexistent_is_noop(self, tmp_path: Path) -> None:
        svc = ThumbnailService(tmp_path / "thumbnails")
        svc.delete(9999)  # should not raise

    def test_large_image_uses_draft_mode(self, tmp_path: Path) -> None:
        """Create a very large image to trigger the draft() code path."""
        svc = ThumbnailService(tmp_path / "thumbnails")
        src = tmp_path / "large.jpg"
        big = Image.new("RGB", (5000, 5000), color="gray")
        big.save(src, format="JPEG", quality=10)
        # Increase file size past LARGE_IMAGE_BYTES threshold
        with open(src, "ab") as f:
            f.write(b"\0" * (26 * 1024 * 1024))  # add 26MB of padding
        result = svc.generate(src, image_id=5)
        assert result.exists()
        assert svc.exists(5) is True

    def test_save_without_fsync_does_not_error(self, tmp_path: Path, monkeypatch) -> None:
        import os
        svc = ThumbnailService(tmp_path / "thumbnails")
        src = tmp_path / "fsync_test.jpg"
        Image.new("RGB", (50, 50), color="green").save(str(src))

        def bad_fsync(fd):
            raise OSError("fsync failed")

        monkeypatch.setattr(os, "fsync", bad_fsync)
        result = svc.generate(src, image_id=6)
        assert result.exists()
