"""Unit tests for FaissIndexManager — error paths, migration, edge cases."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.exceptions import IndexCorruptedError, IndexNotInitialisedError, IndexWriteError


class TestFaissIndexManager:
    def test_load_or_create_creates_new_index(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        assert mgr.is_ready
        assert mgr.ntotal == 0

    def test_add_and_search(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        vec = [0.1] * 512
        mgr.add(1, vec)
        assert mgr.ntotal == 1
        results = mgr.search(vec, 5)
        assert len(results) == 1
        assert results[0].score > 0.99

    def test_add_batch(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        vec = [0.2] * 512
        mgr.add_batch([1, 2], [vec, vec])
        assert mgr.ntotal == 2

    def test_add_batch_empty(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        mgr.add_batch([], [])
        assert mgr.ntotal == 0

    def test_add_batch_mismatched_lengths(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        with pytest.raises(ValueError, match="length"):
            mgr.add_batch([1], [])

    def test_search_empty_index(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        assert mgr.search([0.1] * 512, 5) == []

    def test_save_and_reload(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        mgr.add(1, [0.3] * 512)
        mgr.save()
        mgr2 = FaissIndexManager(tmp_path)
        mgr2.load_or_create()
        assert mgr2.ntotal == 1

    def test_add_without_load_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        with pytest.raises(IndexNotInitialisedError):
            mgr.add(1, [0.1] * 512)

    def test_add_batch_without_load_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        with pytest.raises(IndexNotInitialisedError):
            mgr.add_batch([1], [[0.1] * 512])

    def test_search_without_load_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        with pytest.raises(IndexNotInitialisedError):
            mgr.search([0.1] * 512, 5)

    def test_save_without_load_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        with pytest.raises(IndexNotInitialisedError):
            mgr.save()

    def test_load_corrupted_file_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        mgr._path.write_bytes(b"not a valid FAISS index")
        with pytest.raises(IndexCorruptedError):
            mgr.load_or_create()

    def test_initialise_alias(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.initialise()
        assert mgr.is_ready

    def test_reset(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        mgr.add(1, [0.4] * 512)
        assert mgr.ntotal == 1
        mgr.reset()
        assert mgr.ntotal == 0

    def test_faiss_id_filtering_negative_ids(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        vec = [0.5] * 512
        mgr.add(1, vec)
        results = mgr.search(vec, 5)
        for r in results:
            assert r.faiss_id >= 0

    def test_save_write_error(self, tmp_path: Path, monkeypatch) -> None:
        from app.services.faiss_index import FaissIndexManager

        def bad_replace(src, dst):
            raise OSError("permission denied")

        monkeypatch.setattr(os, "replace", bad_replace)
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        mgr.add(1, [0.6] * 512)
        with pytest.raises(IndexWriteError, match="write failed"):
            mgr.save()

    def test_get_faiss_not_initialised(self) -> None:
        import app.services.faiss_index as fi_mod
        old_mgr = fi_mod._manager
        fi_mod._manager = None
        from app.services.faiss_index import get_faiss
        with pytest.raises(IndexNotInitialisedError):
            get_faiss()
        fi_mod._manager = old_mgr

    def test_init_faiss_creates_manager(self, tmp_path: Path) -> None:
        from app.services.faiss_index import init_faiss
        mgr = init_faiss(tmp_path)
        assert mgr.is_ready

    def test_ntotal_when_none(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        assert mgr.ntotal == 0

    def test_load_with_wrong_dimension_raises(self, tmp_path: Path) -> None:
        from app.services.faiss_index import FaissIndexManager
        import faiss
        mgr = FaissIndexManager(tmp_path)
        mgr._path.parent.mkdir(parents=True, exist_ok=True)
        wrong = faiss.IndexFlatIP(128)
        faiss.write_index(wrong, str(mgr._path))
        with pytest.raises(IndexCorruptedError):
            mgr.load_or_create()

    def test_auto_migrate_to_ivfpq(self, tmp_path: Path, monkeypatch) -> None:
        import app.services.faiss_index as fi_mod
        monkeypatch.setattr(fi_mod, "AUTO_MIGRATE_THRESHOLD", 300)
        monkeypatch.setattr(fi_mod, "IVF_NLIST", 64)
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        rng = __import__('numpy').random.default_rng(42)
        for i in range(350):
            vec = rng.random(512).tolist()
            mgr.add(i, vec)
        assert mgr.ntotal == 350
        assert mgr._is_flat is False

    def test_auto_migrate_on_add_batch(self, tmp_path: Path, monkeypatch) -> None:
        import app.services.faiss_index as fi_mod
        monkeypatch.setattr(fi_mod, "AUTO_MIGRATE_THRESHOLD", 300)
        monkeypatch.setattr(fi_mod, "IVF_NLIST", 64)
        from app.services.faiss_index import FaissIndexManager
        mgr = FaissIndexManager(tmp_path)
        mgr.load_or_create()
        rng = __import__('numpy').random.default_rng(42)
        vecs = [rng.random(512).tolist() for _ in range(350)]
        mgr.add_batch(list(range(350)), vecs)
        assert mgr.ntotal == 350
        assert mgr._is_flat is False
