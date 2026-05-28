"""
TextileSearch — DINOv2 Image Embedder

Wraps Meta's DINOv2 (facebook/dinov2-base) to produce 768-dim vectors that
capture visual texture & structure — well-suited to fabric similarity search.

Why DINOv2 over FashionCLIP?
  - Self-supervised on 142M images: stronger generic visual features.
  - Markedly better at texture & material discrimination — exactly what
    fabric similarity needs.
  - Stable across HuggingFace transformers releases (CLIP processor got
    breaking changes in transformers 5).
  - Pure vision: no text tokenizer overhead at startup.

Hardware acceleration:
  - Auto-detects CUDA / MPS / CPU.
  - Uses fp16 on GPU/MPS, fp32 on CPU.

Lazy loading: `load()` must be called explicitly from the startup thread.
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

DINOV2_MODEL: Final[str] = "facebook/dinov2-base"
VECTOR_DIM: Final[int] = 768                          # DINOv2-base hidden size
MODEL_VERSION: Final[str] = "dinov2-base-v1"


# ─────────────────────────────────────────────────────────────────────────────
# Production embedder
# ─────────────────────────────────────────────────────────────────────────────

class Dinov2Embedder:
    """
    Production embedder using DINOv2-base.

    `embed_batch` runs a single forward pass for up to N images at a time —
    per-call kernel-launch overhead dominates on GPU/MPS for small batches,
    so true batching gives much higher throughput than per-image calls.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._model: object | None = None
        self._processor: object | None = None
        self._loaded: bool = False
        self._device: str = "cpu"
        self._dtype: object | None = None  # populated after torch import

    @property
    def vector_dim(self) -> int:
        return VECTOR_DIM

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    @property
    def is_ready(self) -> bool:
        return self._loaded

    @property
    def device(self) -> str:
        return self._device

    def load(self) -> None:
        """
        Load model weights. Call once from the startup thread.
        Raises ModelNotAvailableError if dependencies are missing or the
        download fails.

        Production safeguards:
          - Uses bf16 on Apple Silicon (HF official recommendation; more
            numerically stable than fp16 on MPS).
          - Runs a warmup forward pass to surface MPS-incompatible ops or
            kernel-load segfaults at startup instead of mid-import.
        """
        try:
            import torch  # type: ignore[import-untyped]
            from transformers import AutoModel, AutoImageProcessor  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ModelNotAvailableError(str(self._model_dir)) from exc

        # Device + dtype selection — per Hugging Face Apple Silicon docs:
        # bf16 is preferred over fp16 on MPS (macOS 14+) for numerical
        # stability with attention layers.
        if torch.cuda.is_available():
            self._device = "cuda"
            self._dtype = torch.float16
        elif torch.backends.mps.is_available():
            self._device = "mps"
            self._dtype = torch.bfloat16
        else:
            self._device = "cpu"
            self._dtype = torch.float32

        model_path = str(self._model_dir) if self._model_dir.exists() else DINOV2_MODEL
        if not self._model_dir.exists():
            logger.warning(
                "Model dir not found — downloading from HuggingFace Hub",
                extra={"model": DINOV2_MODEL},
            )

        try:
            self._processor = AutoImageProcessor.from_pretrained(model_path)
            model = AutoModel.from_pretrained(
                model_path,
                dtype=self._dtype,
            )
            model = model.to(self._device)
            model.eval()
            self._model = model
        except Exception as exc:
            raise ModelNotAvailableError(str(self._model_dir)) from exc

        # Warmup forward pass — does one tiny inference on a synthetic input
        # so any MPS kernel-compile crash happens NOW (at startup, where
        # main.py's fallback to MockEmbedder catches it) instead of inside
        # the import worker thread.
        try:
            dummy = torch.zeros(1, 3, 224, 224, device=self._device, dtype=self._dtype)
            with torch.inference_mode():
                _ = self._model(pixel_values=dummy)
        except Exception as exc:
            self._loaded = False
            self._model = None
            raise ModelNotAvailableError(str(self._model_dir)) from exc

        self._loaded = True
        logger.info(
            "DINOv2 model loaded",
            extra={"dim": VECTOR_DIM, "device": self._device, "dtype": str(self._dtype)},
        )

    def embed(self, image_path: Path) -> EmbeddingVector:
        """Embed a single image."""
        results = self.embed_batch([image_path])
        if not results:
            raise EmbeddingFailedError(str(image_path), "embedding produced no result")
        return results[0]

    def embed_batch(self, image_paths: list[Path]) -> list[EmbeddingVector]:
        """
        Embed N images in a single forward pass. Returns one EmbeddingVector
        per image whose load+forward succeeded. Failures are logged + skipped.
        """
        if not self._loaded or self._model is None or self._processor is None:
            raise ModelNotAvailableError(str(self._model_dir))
        if not image_paths:
            return []

        import torch  # type: ignore[import-untyped]
        from PIL import Image  # type: ignore[import-untyped]

        # Step 1: open all images.
        good_paths: list[Path] = []
        good_images: list[object] = []
        for p in image_paths:
            try:
                good_images.append(Image.open(p).convert("RGB"))
                good_paths.append(p)
            except Exception as exc:
                logger.warning(
                    "Embedding failed — could not open image",
                    extra={"path": str(p), "reason": str(exc)},
                )
        if not good_paths:
            return []

        # Step 2: single batched forward.
        t0 = time.monotonic()
        try:
            inputs = self._processor(images=good_images, return_tensors="pt")
            # Move tensors to the model's device + dtype. Float tensors get
            # cast to the model's compute dtype (bf16/fp16/fp32); integer
            # tensors (e.g. attention masks) keep their original dtype.
            inputs = {
                k: (v.to(device=self._device, dtype=self._dtype)
                    if v.is_floating_point() else v.to(self._device))
                for k, v in inputs.items()
            }
            with torch.inference_mode():
                out = self._model(**inputs)
                features = _pooled_features(out)
                features = features / features.norm(dim=-1, keepdim=True)
            # Always return float32 vectors regardless of compute dtype.
            features_cpu = features.detach().to(device="cpu", dtype=torch.float32).numpy()
        except Exception as exc:
            raise EmbeddingFailedError(str(good_paths[0]), str(exc)) from exc

        batch_ms = (time.monotonic() - t0) * 1000
        per_img_ms = batch_ms / len(good_paths)

        return [
            EmbeddingVector(image_path=str(p), vector=features_cpu[i].tolist(), duration_ms=per_img_ms)
            for i, p in enumerate(good_paths)
        ]


def _pooled_features(model_output: object) -> object:
    """
    Return the image embedding from a DINOv2 forward output.

    Per the official DINOv2 model card: "the last hidden state of the [CLS]
    token can be seen as a representation of an entire image." So we use the
    CLS token directly (the first position of `last_hidden_state`).

    HF transformers also exposes `pooler_output`, which for DINOv2 is the
    same CLS token after a layernorm — using it gives equivalent retrieval
    results. We prefer `last_hidden_state[:, 0, :]` to match the model card
    exactly.
    """
    last_hidden = getattr(model_output, "last_hidden_state", None)
    if last_hidden is not None:
        return last_hidden[:, 0, :]
    pooled = getattr(model_output, "pooler_output", None)
    if pooled is not None:
        return pooled
    raise EmbeddingFailedError("<batch>", "model output has neither last_hidden_state nor pooler_output")


# Backwards-compatible alias — tests + main.py import `FashionClipEmbedder`.
FashionClipEmbedder = Dinov2Embedder


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
        seed = int.from_bytes(digest, "little") % (2**32)
        rng = np.random.default_rng(seed)
        vec: npt.NDArray[np.float32] = rng.random(VECTOR_DIM).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return (vec / norm).tolist()


assert isinstance(MockEmbedder(), EmbedderProtocol)


def init_embedder(cache_dir: Path, use_mock: bool = False) -> Dinov2Embedder | MockEmbedder:
    """
    Factory: returns MockEmbedder when use_mock=True, otherwise a real
    Dinov2Embedder (call `.load()` before first use).
    """
    if use_mock:
        logger.info("Using MockEmbedder (no ML model loaded)")
        return MockEmbedder()
    logger.info("Initialising DINOv2 embedder", extra={"cache_dir": str(cache_dir)})
    return Dinov2Embedder(model_dir=cache_dir)
