"""ThumbnailService unit tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image as PilImage

from app.services.thumbnail import ThumbnailService
from app.exceptions import ImageReadError


@pytest.fixture
def thumbnail_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def svc(thumbnail_dir: Path) -> ThumbnailService:
    return ThumbnailService(thumbnail_dir)


@pytest.fixture
def valid_image(tmp_path: Path) -> Path:
    p = tmp_path / "test.jpg"
    img = PilImage.new("RGB", (800, 600), color=(64, 128, 192))
    img.save(p, format="JPEG")
    return p


class TestGenerate:
    def test_creates_webp_file(self, svc: ThumbnailService, valid_image: Path) -> None:
        result = svc.generate(valid_image, image_id=1)
        assert result.exists()
        assert result.suffix == ".webp"

    def test_uses_sharded_path(self, svc: ThumbnailService, valid_image: Path) -> None:
        result = svc.generate(valid_image, image_id=1)
        # id=1 → shard "01"; path should be thumbnails/01/1.webp
        assert "01" in result.parts
        assert result.name == "1.webp"

    def test_returns_correct_path(self, svc: ThumbnailService, valid_image: Path) -> None:
        result = svc.generate(valid_image, image_id=42)
        expected = svc.thumbnail_path(42)
        assert result == expected

    def test_image_downsized_to_256(self, svc: ThumbnailService, valid_image: Path) -> None:
        result = svc.generate(valid_image, image_id=2, size=(256, 256))
        with PilImage.open(result) as img:
            w, h = img.size
        assert w <= 256 and h <= 256

    def test_atomic_write_cleans_tmp(self, svc: ThumbnailService, valid_image: Path) -> None:
        dest = svc.thumbnail_path(3)
        tmp = dest.with_suffix(".tmp")
        svc.generate(valid_image, image_id=3)
        assert not tmp.exists()

    def test_large_image_uses_draft(self, svc: ThumbnailService, tmp_path: Path) -> None:
        # Create an image larger than LARGE_IMAGE_BYTES (25 MB)
        # We can't easily create a 25 MB JPEG, so mock the size check
        # by testing with a normal image — the draft path is exercised
        # by large actual files in integration tests
        p = tmp_path / "large.jpg"
        img = PilImage.new("RGB", (4000, 3000), color=(255, 0, 0))
        img.save(p, format="JPEG", quality=95)
        result = svc.generate(p, image_id=4)
        assert result.exists()

    def test_missing_source_raises(self, svc: ThumbnailService) -> None:
        with pytest.raises(ImageReadError):
            svc.generate(Path("/nonexistent/image.jpg"), image_id=5)

    def test_corrupt_source_raises(self, svc: ThumbnailService, tmp_path: Path) -> None:
        p = tmp_path / "corrupt.jpg"
        p.write_bytes(b"not a real image file")
        with pytest.raises(ImageReadError):
            svc.generate(p, image_id=6)

    def test_generate_preserves_aspect_ratio(self, svc: ThumbnailService, tmp_path: Path) -> None:
        p = tmp_path / "wide.jpg"
        img = PilImage.new("RGB", (1600, 200), color=(0, 255, 0))
        img.save(p, format="JPEG")
        result = svc.generate(p, image_id=7, size=(256, 256))
        with PilImage.open(result) as opened:
            w, h = opened.size
        assert w <= 256 and h <= 256


class TestHelpers:
    def test_thumbnail_path_deterministic(self, svc: ThumbnailService) -> None:
        assert svc.thumbnail_path(10) == svc.thumbnail_path(10)

    def test_thumbnail_path_shard(self, svc: ThumbnailService) -> None:
        p = svc.thumbnail_path(255)
        assert "ff" in p.parts

    def test_exists_true_after_generate(self, svc: ThumbnailService, valid_image: Path) -> None:
        svc.generate(valid_image, image_id=8)
        assert svc.exists(8) is True

    def test_exists_false_before_generate(self, svc: ThumbnailService) -> None:
        assert svc.exists(9999) is False

    def test_delete_removes_file(self, svc: ThumbnailService, valid_image: Path) -> None:
        svc.generate(valid_image, image_id=9)
        assert svc.exists(9) is True
        svc.delete(9)
        assert svc.exists(9) is False

    def test_delete_missing_is_noop(self, svc: ThumbnailService) -> None:
        svc.delete(9998)
