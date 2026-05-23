"""FAISS index manager tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.services.faiss_index import FaissIndexManager, VECTOR_DIM, SearchResult
from app.exceptions import IndexNotInitialisedError, IndexCorruptedError


def _random_unit_vector() -> list[float]:
    v = np.random.standard_normal(VECTOR_DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _identical_unit_vector(seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(VECTOR_DIM).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


@pytest.fixture
def tmp_index_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def manager(tmp_index_dir: Path) -> FaissIndexManager:
    m = FaissIndexManager(tmp_index_dir, vector_dim=512)
    m.initialise()
    return m


class TestFaissIndexManager:
    def test_initialises_empty(self, manager: FaissIndexManager) -> None:
        assert manager.ntotal == 0
        assert manager.is_ready is True

    def test_add_single_vector(self, manager: FaissIndexManager) -> None:
        manager.add(0, _random_unit_vector())
        assert manager.ntotal == 1

    def test_add_batch(self, manager: FaissIndexManager) -> None:
        vecs = [_random_unit_vector() for _ in range(10)]
        manager.add_batch(list(range(10)), vecs)
        assert manager.ntotal == 10

    def test_add_batch_length_mismatch_raises(self, manager: FaissIndexManager) -> None:
        with pytest.raises(ValueError, match="length"):
            manager.add_batch([0, 1], [_random_unit_vector()])

    def test_search_empty_returns_empty(self, manager: FaissIndexManager) -> None:
        results = manager.search(_random_unit_vector(), k=5)
        assert results == []

    def test_search_finds_identical_vector(self, manager: FaissIndexManager) -> None:
        vec = _identical_unit_vector(seed=7)
        manager.add(0, vec)
        results = manager.search(vec, k=1)
        assert len(results) == 1
        assert results[0].faiss_id == 0
        assert results[0].score == pytest.approx(1.0, abs=1e-5)

    def test_search_k_clamped_to_ntotal(self, manager: FaissIndexManager) -> None:
        for i in range(3):
            manager.add(i, _random_unit_vector())
        results = manager.search(_random_unit_vector(), k=100)
        assert len(results) <= 3

    def test_search_returns_descending_scores(self, manager: FaissIndexManager) -> None:
        vecs = [_random_unit_vector() for _ in range(20)]
        manager.add_batch(list(range(20)), vecs)
        results = manager.search(_random_unit_vector(), k=10)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_atomic_save_and_reload(
        self, tmp_index_dir: Path, manager: FaissIndexManager
    ) -> None:
        vec = _identical_unit_vector(seed=99)
        manager.add(0, vec)
        manager.save()

        # Load a fresh instance from the saved file
        manager2 = FaissIndexManager(tmp_index_dir, vector_dim=512)
        manager2.load_or_create()
        assert manager2.ntotal == 1

        results = manager2.search(vec, k=1)
        assert results[0].score == pytest.approx(1.0, abs=1e-5)

    def test_operations_before_init_raise(self, tmp_index_dir: Path) -> None:
        m = FaissIndexManager(tmp_index_dir / "uninit", vector_dim=512)
        with pytest.raises(IndexNotInitialisedError):
            m.add(0, _random_unit_vector())

    def test_search_result_is_named_tuple(self, manager: FaissIndexManager) -> None:
        manager.add(0, _random_unit_vector())
        result = manager.search(_random_unit_vector(), k=1)[0]
        assert isinstance(result, SearchResult)
        assert isinstance(result.faiss_id, int)
        assert isinstance(result.score, float)

    def test_save_creates_index_file(
        self, tmp_index_dir: Path, manager: FaissIndexManager
    ) -> None:
        manager.add(0, _random_unit_vector())
        manager.save()
        assert (tmp_index_dir / "faiss.index").exists()

    def test_tmp_file_cleaned_up_after_save(
        self, tmp_index_dir: Path, manager: FaissIndexManager
    ) -> None:
        manager.add(0, _random_unit_vector())
        manager.save()
        assert not (tmp_index_dir / "faiss.index.tmp").exists()
