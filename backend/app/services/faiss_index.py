"""TextileSearch — FAISS Index Manager (strict, thread-safe, atomic persistence)."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Final, NamedTuple

import faiss
import numpy as np
from numpy.typing import NDArray

from app.exceptions import (
    FaissError, IndexCorruptedError,
    IndexNotInitialisedError, IndexWriteError,
)

logger = logging.getLogger(__name__)

VECTOR_DIM: Final[int] = 512          # FashionCLIP ViT-B/32
AUTO_MIGRATE_THRESHOLD: Final[int] = 20_000
IVF_NLIST: Final[int] = 256
PQ_M: Final[int] = 64
PQ_NBITS: Final[int] = 8


class SearchResult(NamedTuple):
    faiss_id: int
    score: float   # cosine similarity 0-1


class FaissIndexManager:
    def __init__(self, index_dir: Path, vector_dim: int = VECTOR_DIM) -> None:
        self._dir: Final[Path] = index_dir
        self._path: Final[Path] = index_dir / "faiss.index"
        self._tmp: Final[Path] = index_dir / "faiss.index.tmp"
        self._dim: Final[int] = vector_dim
        self._lock: Final[threading.Lock] = threading.Lock()
        self._index: faiss.Index | None = None
        self._is_flat = True

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    def load_or_create(self) -> None:
        with self._lock:
            if self._path.exists():
                try:
                    idx = faiss.read_index(str(self._path))
                except Exception as e:
                    raise IndexCorruptedError(str(self._path)) from e
                if idx.d != self._dim:
                    raise IndexCorruptedError(str(self._path))
                self._index = idx
                self._is_flat = not isinstance(idx, faiss.IndexIVFPQ)
                logger.info("FAISS index loaded", extra={"ntotal": idx.ntotal})
            else:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._index = faiss.IndexFlatIP(self._dim)
                self._is_flat = True

    # Alias used by tests
    def initialise(self) -> None:
        self.load_or_create()

    def reset(self) -> None:
        """Drop all vectors and start with an empty flat index."""
        self._index = faiss.IndexFlatIP(self._dim)

    # ── Properties ──────────────────────────────────────────────────────────────

    @property
    def ntotal(self) -> int:
        return self._index.ntotal if self._index is not None else 0

    @property
    def is_ready(self) -> bool:
        return self._index is not None

    # ── Operations ──────────────────────────────────────────────────────────────

    def add(self, faiss_id: int, vector: list[float]) -> None:
        if self._index is None:
            raise IndexNotInitialisedError("call load_or_create() first")
        arr = _unit(vector)
        with self._lock:
            self._index.add(arr)   # type: ignore[arg-type]
            if self._is_flat and self._index.ntotal >= AUTO_MIGRATE_THRESHOLD:
                self._migrate()

    def add_batch(self, faiss_ids: list[int], vectors: list[list[float]]) -> None:
        if self._index is None:
            raise IndexNotInitialisedError("call load_or_create() first")
        if len(faiss_ids) != len(vectors):
            raise ValueError(f"faiss_ids length ({len(faiss_ids)}) != vectors ({len(vectors)})")
        if not vectors:
            return
        arr = np.stack([_unit(v)[0] for v in vectors]).astype(np.float32)
        with self._lock:
            self._index.add(arr)   # type: ignore[arg-type]
            if self._is_flat and self._index.ntotal >= AUTO_MIGRATE_THRESHOLD:
                self._migrate()

    def search(self, vector: list[float], k: int) -> list[SearchResult]:
        if self._index is None:
            raise IndexNotInitialisedError("call load_or_create() first")
        if self._index.ntotal == 0:
            return []
        k_actual = min(k, self._index.ntotal)
        arr = _unit(vector)
        scores: NDArray[np.float32]
        ids: NDArray[np.int64]
        scores, ids = self._index.search(arr, k_actual)  # type: ignore[assignment]
        return [
            SearchResult(faiss_id=int(fid), score=float(sc))
            for fid, sc in zip(ids[0], scores[0])
            if fid >= 0
        ]

    def save(self) -> None:
        if self._index is None:
            raise IndexNotInitialisedError("nothing to save")
        with self._lock:
            try:
                faiss.write_index(self._index, str(self._tmp))
                os.replace(self._tmp, self._path)
            except OSError as e:
                raise IndexWriteError(f"write failed: {e}") from e

    # ── Private ─────────────────────────────────────────────────────────────────

    def _migrate(self) -> None:
        assert self._index is not None
        n = self._index.ntotal
        vecs = np.zeros((n, self._dim), dtype=np.float32)
        for i in range(n):
            self._index.reconstruct(i, vecs[i])   # type: ignore[arg-type]
        quant = faiss.IndexFlatIP(self._dim)
        new = faiss.IndexIVFPQ(quant, self._dim, IVF_NLIST, PQ_M, PQ_NBITS)
        new.metric_type = faiss.METRIC_INNER_PRODUCT
        new.train(vecs)   # type: ignore[arg-type]
        new.add(vecs)     # type: ignore[arg-type]
        new.nprobe = 32
        self._index = new
        self._is_flat = False
        logger.info("Migrated FAISS → IVF+PQ", extra={"ntotal": n})


def _unit(v: list[float]) -> NDArray[np.float32]:
    arr = np.array(v, dtype=np.float32).reshape(1, -1)
    n = float(np.linalg.norm(arr))
    return arr if n < 1e-8 else arr / n


# Module-level singleton
_manager: FaissIndexManager | None = None


def init_faiss(index_dir: Path) -> FaissIndexManager:
    global _manager
    _manager = FaissIndexManager(index_dir)
    _manager.load_or_create()
    return _manager


def get_faiss() -> FaissIndexManager:
    if _manager is None:
        raise IndexNotInitialisedError("call init_faiss() first")
    return _manager
