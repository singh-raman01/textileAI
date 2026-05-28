"""
TextileSearch — Service Protocols

Every major service dependency is expressed as a Protocol.
This means:
  - FastAPI routes depend on protocols, not concrete classes
  - Tests inject mock implementations without subclassing
  - The real implementations can be swapped (e.g. FashionCLIP → newer model)
    by implementing the same protocol, changing zero calling code

No concrete class is imported by API route modules — only protocols.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
# Embedder
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EmbeddingVector:
    """A single image embedding result."""
    image_path: str
    vector: list[float]          # 768-dim for DINOv2-base
    duration_ms: float


@runtime_checkable
class EmbedderProtocol(Protocol):
    """
    Produces float32 embedding vectors from fabric images.
    Implementations: Dinov2Embedder (production), MockEmbedder (testing).
    """

    @property
    def vector_dim(self) -> int:
        """Dimensionality of produced vectors (768 for DINOv2-base)."""
        ...

    @property
    def model_version(self) -> str:
        """Canonical model version string stored alongside each embedding."""
        ...

    @property
    def is_ready(self) -> bool:
        """True if the model is loaded and ready to produce embeddings."""
        ...

    def embed(self, image_path: Path) -> EmbeddingVector:
        """
        Embed a single image.
        Raises EmbeddingFailedError if the image cannot be processed.
        Raises ModelNotAvailableError if weights are not present.
        """
        ...

    def embed_batch(self, image_paths: list[Path]) -> list[EmbeddingVector]:
        """
        Embed a batch of images.
        Processes all images — failed ones are logged individually
        and omitted from the returned list (never raises for individual failures).
        Raises ModelNotAvailableError if weights are not present.
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BoundingBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class TextRegion:
    text: str
    confidence: float            # 0.0–1.0
    bounding_box: BoundingBox


@dataclass(frozen=True)
class OcrResult:
    """
    Raw OCR output from a single image.
    `text_regions` preserves spatial layout.
    `full_text` is all regions joined for parser consumption.
    `mean_confidence` is the average over all regions (0.0 if no text found).
    `has_text` is False when the image contains no detectable text.
    """
    image_path: str
    text_regions: list[TextRegion]
    full_text: str
    mean_confidence: float
    has_text: bool
    duration_ms: float


@runtime_checkable
class OcrProtocol(Protocol):
    """
    Extracts text from fabric label images.
    Implementations: PaddleOcrService (production), MockOcrService (testing).
    """

    @property
    def is_ready(self) -> bool:
        """True if OCR model is loaded and ready."""
        ...

    def extract(self, image_path: Path) -> OcrResult:
        """
        Run OCR on the given image.
        Never raises for low-quality images — returns OcrResult with
        has_text=False and empty text_regions instead.
        Raises OcrModelNotAvailableError if models are not present.
        Raises OcrProcessingError for unrecoverable processing errors.
        """
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Thumbnail generator
# ─────────────────────────────────────────────────────────────────────────────

@runtime_checkable
class ThumbnailProtocol(Protocol):
    """Generates and caches thumbnail images."""

    def generate(
        self,
        image_path: Path,
        dest_path: Path,
        size: tuple[int, int] = (256, 256),
    ) -> Path:
        """
        Generate a thumbnail and write it to dest_path.
        Returns dest_path on success.
        Raises ImageReadError if the source image cannot be opened.
        """
        ...
