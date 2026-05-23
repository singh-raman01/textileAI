"""DuplicateScanner tests with mock FAISS."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.db.models import Duplicate, Image
from app.db.session import get_session
from app.services.faiss_index import VECTOR_DIM, FaissIndexManager
from app.services.duplicate_scanner import run_similarity_scan


def _unit_vector(seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(VECTOR_DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _identical_vector(val: float = 0.5) -> list[float]:
    v = np.full(VECTOR_DIM, val, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _index_image(
    faiss_mgr: FaissIndexManager, vector: list[float]
) -> int:
    """Add vector to FAISS and create a DB row.  Returns the faiss_id."""
    faiss_id = faiss_mgr.ntotal
    faiss_mgr.add(faiss_id, vector)
    with get_session() as session:
        session.add(Image(
            file_path=f"/tmp/dup_{faiss_id}.jpg",
            filename=f"dup_{faiss_id}.jpg",
            import_status="done",
            faiss_id=faiss_id,
        ))
    return faiss_id


@pytest.fixture
def faiss_mgr(app_config, db_ready) -> FaissIndexManager:
    from app.services.faiss_index import init_faiss
    mgr = init_faiss(app_config.faiss_dir)
    mgr.reset()
    with get_session() as session:
        session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=OFF"))
        session.query(Duplicate).delete()
        session.query(Image).delete()
        session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=ON"))
    return mgr


class TestRunSimilarityScan:
    def test_empty_index_returns_zero(self, faiss_mgr: FaissIndexManager) -> None:
        count = run_similarity_scan(faiss_mgr=faiss_mgr)
        assert count == 0

    def test_single_vector_returns_zero(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        _index_image(faiss_mgr, _unit_vector(1))
        assert faiss_mgr.ntotal == 1
        count = run_similarity_scan(faiss_mgr=faiss_mgr)
        assert count == 0

    def test_identical_vectors_detected(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        vec = _identical_vector(0.5)
        _index_image(faiss_mgr, vec)
        _index_image(faiss_mgr, vec)
        assert faiss_mgr.ntotal == 2
        count = run_similarity_scan(faiss_mgr=faiss_mgr)
        assert count == 1

    def test_low_similarity_not_detected(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        _index_image(faiss_mgr, _unit_vector(1))
        _index_image(faiss_mgr, _unit_vector(2))
        count = run_similarity_scan(threshold=0.99, faiss_mgr=faiss_mgr)
        assert count == 0

    def test_respects_threshold(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        """Low threshold finds pair that high threshold misses."""
        with get_session() as session:
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=OFF"))
            session.query(Duplicate).delete()
            session.query(Image).delete()
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=ON"))
        faiss_mgr.reset()
        # Two vectors with cosine sim = 0.9, below 0.99 threshold
        angle = np.arccos(0.9)
        base = [1.0] + [0.0] * (VECTOR_DIM - 1)
        s = np.sin(angle)
        c = np.cos(angle)
        rotated = [c] + [s] + [0.0] * (VECTOR_DIM - 2)
        _index_image(faiss_mgr, base)
        _index_image(faiss_mgr, rotated)
        high = run_similarity_scan(threshold=0.99, faiss_mgr=faiss_mgr)
        with get_session() as session:
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=OFF"))
            session.query(Duplicate).delete()
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=ON"))
        low = run_similarity_scan(threshold=0.50, faiss_mgr=faiss_mgr)
        assert high == 0
        assert low == 1

    def test_skips_existing_pairs(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        vec = _identical_vector(0.5)
        _index_image(faiss_mgr, vec)
        _index_image(faiss_mgr, vec)
        first = run_similarity_scan(faiss_mgr=faiss_mgr)
        second = run_similarity_scan(faiss_mgr=faiss_mgr)
        assert first == 1
        assert second == 0

    def test_creates_duplicate_records(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        vec = _identical_vector(0.5)
        _index_image(faiss_mgr, vec)
        _index_image(faiss_mgr, vec)
        run_similarity_scan(faiss_mgr=faiss_mgr)
        with get_session() as session:
            pairs = session.query(Duplicate).all()
        assert len(pairs) >= 1
        pair = pairs[0]
        assert pair.match_type == "visual"
        assert pair.resolved is False
        assert pair.similarity > 0.95

    def test_multiple_duplicates(self, faiss_mgr: FaissIndexManager, db_ready: bool) -> None:
        for _ in range(5):
            _index_image(faiss_mgr, _identical_vector(0.3))
        count = run_similarity_scan(threshold=0.99, faiss_mgr=faiss_mgr)
        assert count > 1
