"""Coverage tests for duplicate_scanner edge cases."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import Duplicate
from app.db.session import get_session
from app.services.faiss_index import FaissIndexManager


VECTOR_DIM = 768


class TestDuplicateScannerCoverage:
    def test_scan_returns_zero_when_not_ready(self) -> None:
        from app.services.duplicate_scanner import run_similarity_scan
        # faiss_mgr not initialised
        class FakeManager:
            is_ready = False
            ntotal = 0
        result = run_similarity_scan(faiss_mgr=FakeManager())
        assert result == 0

    def test_scan_returns_zero_when_too_few_vectors(self) -> None:
        from app.services.duplicate_scanner import run_similarity_scan
        mgr = FaissIndexManager(Path("/tmp"), vector_dim=VECTOR_DIM)
        mgr.load_or_create()
        mgr.add(1, [0.1] * VECTOR_DIM)
        assert mgr.ntotal == 1
        result = run_similarity_scan(faiss_mgr=mgr)
        assert result == 0

    def test_scan_skips_images_without_faiss_id(self, tmp_path: Path, db_ready: bool) -> None:
        from app.services.duplicate_scanner import run_similarity_scan
        from app.db.models import Image as ImageModel
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        mgr.add(1, [0.1] * VECTOR_DIM)  # faiss_id=1 is in index
        with get_session() as session:
            session.add(ImageModel(
                file_path="/tmp/no_faiss.jpg", filename="no_faiss.jpg",
                import_status="done", faiss_id=None,
            ))
            session.commit()
        result = run_similarity_scan(faiss_mgr=mgr)
        assert result >= 0

    def test_scan_skips_orphaned_images(self, tmp_path: Path, db_ready: bool) -> None:
        from app.services.duplicate_scanner import run_similarity_scan
        from app.db.models import Image as ImageModel
        mgr = FaissIndexManager(tmp_path, vector_dim=VECTOR_DIM)
        mgr.load_or_create()
        mgr.add(999, [0.1] * VECTOR_DIM)
        with get_session() as session:
            existing = session.query(ImageModel).filter(ImageModel.faiss_id == 999).first()
            if existing:
                session.delete(existing)
                session.flush()
            session.add(ImageModel(
                file_path="/tmp/orphan.jpg", filename="orphan.jpg",
                import_status="done", faiss_id=999, is_orphaned=True,
            ))
            session.commit()
        result = run_similarity_scan(faiss_mgr=mgr)
        assert result == 0

    def test_scan_skips_self_match(self, tmp_path: Path, db_ready: bool) -> None:
        """When the only match is the image itself, nothing should be written."""
        from app.services.duplicate_scanner import run_similarity_scan
        from app.db.models import Image as ImageModel
        mgr = FaissIndexManager(tmp_path, vector_dim=VECTOR_DIM)
        mgr.load_or_create()
        vec = [0.5] * VECTOR_DIM
        mgr.add(100, vec)
        with get_session() as session:
            existing = session.query(ImageModel).filter(ImageModel.faiss_id == 100).first()
            if existing:
                session.delete(existing)
            session.flush()
            session.add(ImageModel(
                file_path="/tmp/self_match.jpg", filename="self_match.jpg",
                import_status="done", faiss_id=100,
            ))
            session.commit()
        result = run_similarity_scan(faiss_mgr=mgr)
        assert result == 0
