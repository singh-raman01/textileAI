"""
TextileSearch — FashionCLIP Embedder

Wraps patrickjohncyh/fashion-clip (ViT-B/32) to produce 512-dim vectors.

Lazy loading: the model is NOT loaded at import time. It is loaded on the first
call to embed() or embed_batch(). This means the FastAPI process starts quickly
and the ML model is only loaded once the import pipeline actually begins.

Mock implementation for testing: MockEmbedder produces deterministic vectors
without any model files — seeded from the image path hash.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt

from app.exceptions import EmbeddingFailedError, ModelNotAvailableError
from app.services.protocols import EmbeddingVector, EmbedderProtocol

logger = logging.getLogger(__name__)

FASHION_CLIP_MODEL: Final[str] = "patrickjohncyh/fashion-clip"
VECTOR_DIM: Final[int] = 512
MODEL_VERSION: Final[str] = "fashion-clip-v1"


# ─────────────────────────────────────────────────────────────────────────────
# Production embedder
# ─────────────────────────────────────────────────────────────────────────────

class FashionClipEmbedder:
    """
    Production embedder using FashionCLIP ViT-B/32.

    Model is loaded lazily on first use. Thread-safe after initialisation
    (transformers models are not thread-safe during loading — the caller
    must ensure load() is called from a single thread at startup).
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._model: object | None = None
        self._processor: object | None = None
        self._loaded: bool = False

    @property
    def vector_dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """
        Explicitly load model weights. Call once from the startup thread.
        Raises ModelNotAvailableError if weights are absent.
        """
        try:
            from transformers import CLIPProcessor, CLIPModel  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ModelNotAvailableError(str(self._model_dir)) from exc

        model_path = str(self._model_dir) if self._model_dir.exists() else FASHION_CLIP_MODEL
        if not self._model_dir.exists():
            logger.warning(
                "Model dir not found — downloading from HuggingFace Hub",
                extra={"model": FASHION_CLIP_MODEL},
            )

        try:
            self._processor = CLIPProcessor.from_pretrained(model_path)
            self._model = CLIPModel.from_pretrained(model_path)
        except Exception as exc:
            raise ModelNotAvailableError(str(self._model_dir)) from exc

        self._loaded = True
        logger.info("FashionCLIP model loaded", extra={"dim": VECTOR_DIM})

    def embed(self, image_path: Path) -> EmbeddingVector:
        """
        Embed a single image. Raises ModelNotAvailableError, EmbeddingFailedError.
        """
        results = self.embed_batch([image_path])
        if not results:
            raise EmbeddingFailedError(str(image_path), "unknown processing error")
        return results[0]

    def embed_batch(self, image_paths: list[Path]) -> list[EmbeddingVector]:
        """
        Embed a batch. Individual failures are logged and skipped.
        Raises ModelNotAvailableError if not loaded.
        """
        if not self._loaded or self._model is None or self._processor is None:
            raise ModelNotAvailableError(str(self._model_dir))

        import torch  # type: ignore[import-untyped]
        from PIL import Image  # type: ignore[import-untyped]

        results: list[EmbeddingVector] = []
        for path in image_paths:
            t0 = time.monotonic()
            try:
                image = Image.open(path).convert("RGB")
                inputs = self._processor(images=image, return_tensors="pt", padding=True)
                with torch.no_grad():
                    features = self._model.get_image_features(**inputs)
                    features = features / features.norm(dim=-1, keepdim=True)
                vector = features.squeeze(0).cpu().numpy().tolist()
                ms = (time.monotonic() - t0) * 1000
                results.append(EmbeddingVector(image_path=str(path), vector=vector, duration_ms=ms))
            except Exception as exc:
                logger.warning(
                    "Embedding failed — skipping",
                    extra={"path": str(path), "error": str(exc)},
                )
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Mock embedder (testing / CI)
# ─────────────────────────────────────────────────────────────────────────────

class MockEmbedder:
    """
    Deterministic mock embedder for testing.
    Vectors are seeded from the MD5 of the image path — same path always
    produces the same vector. No model files required.
    """

    @property
    def vector_dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_version(self) -> str:
        return "mock-v0"

    @property
    def is_ready(self) -> bool:
        return True

    def embed(self, image_path: Path) -> EmbeddingVector:
        t0 = time.monotonic()
        vector = self._path_to_vector(image_path)
        ms = (time.monotonic() - t0) * 1000
        return EmbeddingVector(image_path=str(image_path), vector=vector, duration_ms=ms)

    def embed_batch(self, image_paths: list[Path]) -> list[EmbeddingVector]:
        return [self.embed(p) for p in image_paths]

    def _path_to_vector(self, path: Path) -> list[float]:
        digest = hashlib.md5(str(path).encode()).digest()
        # Use the 16-byte digest as a seed for a reproducible random vector
        seed = int.from_bytes(digest, "little") % (2**32)
        rng = np.random.default_rng(seed)
        vec: npt.NDArray[np.float32] = rng.random(VECTOR_DIM).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return (vec / norm).tolist()


# Runtime check: both classes satisfy the protocol
assert isinstance(MockEmbedder(), EmbedderProtocol)


def init_embedder(cache_dir: Path, use_mock: bool = False) -> FashionClipEmbedder | MockEmbedder:
    """
    Factory: returns a MockEmbedder when use_mock=True, otherwise a real
    FashionClipEmbedder (model loads lazily on first embed call).
    """
    if use_mock:
        logger.info("Using MockEmbedder (no ML model loaded)")
        return MockEmbedder()
    logger.info("Initialising FashionCLIP embedder", extra={"cache_dir": str(cache_dir)})
    return FashionClipEmbedder(model_dir=cache_dir)
