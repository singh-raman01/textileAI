"""Import pipeline and sync service tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image as PilImage
from sqlalchemy.orm import Session

from app.db.models import Image, WatchedFolder
from app.db.session import get_session
from app.services.embedder import MockEmbedder
from app.services.ocr import MockOcrService
from app.services.importer import Importer, reset_in_flight_images
from app.services.sync import (
    startup_sync,
    handle_batch,
    compute_file_hash,
    _derive_folder_tag_names,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_image_file(directory: Path, name: str = "test.jpg") -> Path:
    """Create a minimal valid JPEG in directory."""
    path = directory / name
    img = PilImage.new("RGB", (64, 64), color=(128, 64, 32))
    img.save(path, format="JPEG")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Sync: folder tag derivation
# ─────────────────────────────────────────────────────────────────────────────

class TestFolderTagDerivation:
    def test_single_level(self) -> None:
        root  = Path("/data/textiles")
        image = Path("/data/textiles/wool/item.jpg")
        tags  = _derive_folder_tag_names(image, root)
        assert tags == ["wool"]

    def test_two_levels(self) -> None:
        root  = Path("/data/textiles")
        image = Path("/data/textiles/wool/heavyweight/item.jpg")
        tags  = _derive_folder_tag_names(image, root)
        assert tags == ["wool", "heavyweight"]

    def test_three_levels(self) -> None:
        root  = Path("/data/textiles")
        image = Path("/data/textiles/cotton/summer-2025/supplier-A/item.jpg")
        tags  = _derive_folder_tag_names(image, root)
        assert tags == ["cotton", "summer-2025", "supplier-A"]

    def test_image_directly_in_root(self) -> None:
        root  = Path("/data/textiles")
        image = Path("/data/textiles/item.jpg")
        tags  = _derive_folder_tag_names(image, root)
        assert tags == []

    def test_unrelated_path_returns_empty(self) -> None:
        root  = Path("/data/textiles")
        image = Path("/other/path/item.jpg")
        tags  = _derive_folder_tag_names(image, root)
        assert tags == []


# ─────────────────────────────────────────────────────────────────────────────
# Sync: MD5 hashing
# ─────────────────────────────────────────────────────────────────────────────

class TestMd5Hashing:
    def test_same_file_same_hash(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        assert compute_file_hash(img) == compute_file_hash(img)

    def test_different_files_different_hash(self, tmp_path: Path) -> None:
        a = _make_image_file(tmp_path, "a.jpg")
        b = tmp_path / "b.jpg"
        b.write_bytes(b"different content")
        assert compute_file_hash(a) != compute_file_hash(b)

    def test_hash_is_hex_string(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        h   = compute_file_hash(img)
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


# ─────────────────────────────────────────────────────────────────────────────
# Importer: crash recovery
# ─────────────────────────────────────────────────────────────────────────────

class TestImporterCrashRecovery:
    def test_reset_in_flight_images(
        self, db_ready: bool, session: Session
    ) -> None:
        # Insert a stuck 'processing' image
        img = Image(
            file_path="/tmp/stuck_image.jpg",
            filename="stuck_image.jpg",
            import_status="processing",
        )
        session.add(img)
        session.commit()

        count = reset_in_flight_images()
        assert count >= 1

        # Verify it's been reset
        with get_session() as s:
            found = s.get(Image, img.id)
            assert found is not None
            assert found.import_status == "queued"


# ─────────────────────────────────────────────────────────────────────────────
# Importer: MockEmbedder produces consistent vectors
# ─────────────────────────────────────────────────────────────────────────────

class TestMockEmbedder:
    def test_same_path_same_vector(self, tmp_path: Path) -> None:
        img_path = _make_image_file(tmp_path)
        emb = MockEmbedder()
        r1 = emb.embed(img_path)
        r2 = emb.embed(img_path)
        assert r1.vector == r2.vector

    def test_different_paths_different_vectors(self, tmp_path: Path) -> None:
        a = _make_image_file(tmp_path, "a.jpg")
        b = _make_image_file(tmp_path, "b.jpg")
        emb = MockEmbedder()
        assert emb.embed(a).vector != emb.embed(b).vector

    def test_vector_is_unit_length(self, tmp_path: Path) -> None:
        import math
        img_path = _make_image_file(tmp_path)
        result = MockEmbedder().embed(img_path)
        norm = math.sqrt(sum(x * x for x in result.vector))
        assert norm == pytest.approx(1.0, abs=1e-5)

    def test_vector_dim(self, tmp_path: Path) -> None:
        img_path = _make_image_file(tmp_path)
        result = MockEmbedder().embed(img_path)
        assert len(result.vector) == 768

    def test_batch_matches_individual(self, tmp_path: Path) -> None:
        paths = [_make_image_file(tmp_path, f"img{i}.jpg") for i in range(5)]
        emb = MockEmbedder()
        batch = emb.embed_batch(paths)
        for i, path in enumerate(paths):
            single = emb.embed(path)
            assert batch[i].vector == single.vector


# ─────────────────────────────────────────────────────────────────────────────
# Importer: MockOcrService
# ─────────────────────────────────────────────────────────────────────────────

class TestMockOcrService:
    LABEL = "FAFA TEXTILES CO. LTD\nITEM NO: H4-7103WY\n100% COTTON"

    def test_returns_configured_text(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        ocr = MockOcrService({str(img): self.LABEL})
        result = ocr.extract(img)
        assert result.has_text is True
        assert "FAFA" in result.full_text

    def test_unknown_path_returns_empty(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        ocr = MockOcrService()
        result = ocr.extract(img)
        assert result.has_text is False
        assert result.full_text == ""

    def test_mean_confidence_for_canned_text(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        ocr = MockOcrService({str(img): self.LABEL})
        result = ocr.extract(img)
        assert result.mean_confidence == pytest.approx(0.95)

    def test_regions_count_matches_lines(self, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path)
        ocr = MockOcrService({str(img): self.LABEL})
        result = ocr.extract(img)
        non_empty_lines = [l for l in self.LABEL.splitlines() if l.strip()]
        assert len(result.text_regions) == len(non_empty_lines)


# ─────────────────────────────────────────────────────────────────────────────
# Startup sync
# ─────────────────────────────────────────────────────────────────────────────

class TestStartupSync:
    def test_sync_on_empty_db(self, db_ready: bool) -> None:
        result = startup_sync()
        assert isinstance(result.checked, int)
        assert isinstance(result.new_queued, int)
        assert result.checked >= 0

    def test_sync_queues_new_files(self, db_ready: bool, tmp_path: Path) -> None:
        # Register a watched folder with an image
        img_path = _make_image_file(tmp_path, "sync_test.jpg")
        with get_session() as s:
            folder = WatchedFolder(
                folder_path=str(tmp_path),
                display_name="Sync Test Folder",
            )
            s.add(folder)

        result = startup_sync()
        assert result.new_queued >= 1

    def test_sync_orphans_missing_files(self, db_ready: bool, tmp_path: Path) -> None:
        ghost = Image(
            file_path=str(tmp_path / "ghost_no_exist.jpg"),
            filename="ghost_no_exist.jpg",
            import_status="done",
            is_orphaned=False,
        )
        with get_session() as s:
            s.add(ghost)

        result = startup_sync()
        assert result.orphaned >= 1

        with get_session() as s:
            found = s.get(Image, ghost.id)
            assert found is not None
            assert found.is_orphaned is True


# ─────────────────────────────────────────────────────────────────────────────
# Handle batch (chokidar events)
# ─────────────────────────────────────────────────────────────────────────────

class TestHandleBatch:
    def test_new_file_queued(self, db_ready: bool, tmp_path: Path) -> None:
        img = _make_image_file(tmp_path, "batch_new.jpg")
        # Register the parent as a watched folder so the sync can find it
        with get_session() as s:
            existing = s.query(WatchedFolder).filter_by(
                folder_path=str(tmp_path)
            ).first()
            if not existing:
                s.add(WatchedFolder(
                    folder_path=str(tmp_path), display_name="Batch Test"
                ))

        result = handle_batch(added=[str(img)], removed=[])
        assert result.queued >= 1

    def test_removed_file_orphaned(self, db_ready: bool, tmp_path: Path) -> None:
        img = Image(
            file_path="/tmp/to_be_removed_batch.jpg",
            filename="to_be_removed_batch.jpg",
            import_status="done",
            is_orphaned=False,
            file_hash="deadbeef" * 8,
        )
        with get_session() as s:
            s.add(img)

        result = handle_batch(added=[], removed=[img.file_path])
        assert result.orphaned >= 1

    def test_empty_batch_is_no_op(self, db_ready: bool) -> None:
        result = handle_batch(added=[], removed=[])
        assert result.queued   == 0
        assert result.orphaned == 0
        assert result.renamed  == 0
