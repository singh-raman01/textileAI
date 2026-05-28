"""
TextileSearch — OCR Service

Production backend: RapidOCR running on ONNX Runtime.

Why RapidOCR (not PaddleOCR)?
  - Same underlying detection / recognition models (PP-OCRv4/v5)
  - Pure ONNX Runtime — no PaddlePaddle Python binding to segfault
  - Stable on Apple Silicon arm64 under heavy load
  - Optional CoreML execution provider on macOS = Neural Engine acceleration
  - ~10x smaller install footprint than paddlepaddle+paddleocr

Public interface is unchanged: `OcrService.load()` / `.extract(path)` returning
`OcrResult`. The legacy class name `PaddleOcrService` is kept as an alias so
existing imports/tests keep working.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image

from app.exceptions import OcrModelNotAvailableError, OcrProcessingError
from app.services.protocols import BoundingBox, OcrResult, OcrProtocol, TextRegion

logger = logging.getLogger(__name__)

OCR_LANG: Final[str] = "en"     # "ch" for Chinese labels
# Cap the longest side fed to the detector. RapidOCR auto-resizes; this just
# avoids spending memory on iPhone-sized 4032px photos.
MAX_OCR_SIDE: Final[int] = 1600


class RapidOcrService:
    """
    Production OCR using RapidOCR + ONNX Runtime.

    Lazy load: the OCR engine is constructed in `load()`; if RapidOCR isn't
    installed, raises `OcrModelNotAvailableError` and the importer pipeline
    gracefully falls back to mock OCR.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._engine: object | None = None
        self._loaded: bool = False

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load(self) -> None:
        try:
            from rapidocr import RapidOCR  # type: ignore[import-untyped]
        except ImportError as exc:
            raise OcrModelNotAvailableError(str(self._model_dir)) from exc

        try:
            self._engine = RapidOCR()
        except Exception as exc:
            raise OcrModelNotAvailableError(str(self._model_dir)) from exc

        self._loaded = True
        logger.info("RapidOCR loaded", extra={"lang": OCR_LANG})

    def extract(self, image_path: Path) -> OcrResult:
        if not self._loaded or self._engine is None:
            raise OcrModelNotAvailableError(str(self._model_dir))

        t0 = time.monotonic()
        try:
            # Pre-resize huge inputs so the detector pipeline doesn't waste
            # memory on full-res phone photos. RapidOCR accepts numpy arrays.
            img = _load_and_shrink(image_path, MAX_OCR_SIDE)
            raw = self._engine(img)  # type: ignore[misc]
        except Exception as exc:
            raise OcrProcessingError(str(image_path), str(exc)) from exc

        ms = (time.monotonic() - t0) * 1000
        return _build_result(str(image_path), raw, ms)


def _load_and_shrink(path: Path, max_side: int) -> object:
    """
    Open `path`, downscale if its longest side exceeds `max_side`, and
    return a numpy RGB array suitable for RapidOCR.
    """
    import numpy as np
    img = Image.open(path).convert("RGB")
    w, h = img.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return np.asarray(img)


def _build_result(image_path: str, raw: object, duration_ms: float) -> OcrResult:
    """
    Convert RapidOCR output (`RapidOCROutput` data class with
    `boxes`, `txts`, `scores`) into our internal OcrResult.
    """
    if raw is None:
        return _empty(image_path, duration_ms)

    boxes = getattr(raw, "boxes", None)
    txts  = getattr(raw, "txts", None)
    scores = getattr(raw, "scores", None)

    if boxes is None or txts is None or scores is None or len(txts) == 0:
        return _empty(image_path, duration_ms)

    regions: list[TextRegion] = []
    for box, text, score in zip(boxes, txts, scores, strict=False):
        try:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            bb = BoundingBox(
                x_min=min(xs), y_min=min(ys),
                x_max=max(xs), y_max=max(ys),
            )
            regions.append(
                TextRegion(text=str(text), confidence=float(score), bounding_box=bb),
            )
        except (IndexError, TypeError, ValueError) as exc:
            logger.debug("OCR line parse error", extra={"error": str(exc)})

    full_text = "\n".join(r.text for r in regions)
    mean_conf = sum(r.confidence for r in regions) / len(regions) if regions else 0.0

    return OcrResult(
        image_path=image_path,
        text_regions=regions,
        full_text=full_text,
        mean_confidence=mean_conf,
        has_text=bool(regions),
        duration_ms=duration_ms,
    )


def _empty(image_path: str, duration_ms: float) -> OcrResult:
    return OcrResult(
        image_path=image_path,
        text_regions=[],
        full_text="",
        mean_confidence=0.0,
        has_text=False,
        duration_ms=duration_ms,
    )


# Backwards-compatible alias — tests + main.py import `PaddleOcrService`.
PaddleOcrService = RapidOcrService


# ─────────────────────────────────────────────────────────────────────────────
# Mock OCR service
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _CannedResponse:
    text: str
    confidence: float


class MockOcrService:
    """
    Configurable test double. Returns canned text by path, or empty result.
    Supports set_default_text() for blanket fallback.
    """

    def __init__(self, canned_texts: dict[str, str] | None = None) -> None:
        self._canned: dict[str, str] = canned_texts or {}
        self._default: str = ""

    def set_default_text(self, text: str) -> None:
        self._default = text

    def add_text(self, path: str | Path, text: str) -> None:
        self._canned[str(path)] = text

    @property
    def is_ready(self) -> bool:
        return True

    def extract(self, image_path: Path) -> OcrResult:
        t0 = time.monotonic()
        text = self._canned.get(str(image_path), self._default)
        if not text:
            return OcrResult(
                image_path=str(image_path),
                text_regions=[],
                full_text="",
                mean_confidence=0.0,
                has_text=False,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        regions = [
            TextRegion(
                text=l, confidence=0.95,
                bounding_box=BoundingBox(0, i * 20.0, 400.0, (i + 1) * 20.0),
            )
            for i, l in enumerate(lines)
        ]
        return OcrResult(
            image_path=str(image_path),
            text_regions=regions,
            full_text=text,
            mean_confidence=0.95,
            has_text=True,
            duration_ms=(time.monotonic() - t0) * 1000,
        )


assert isinstance(MockOcrService(), OcrProtocol)


def init_ocr(model_dir: Path, use_mock: bool = False) -> RapidOcrService | MockOcrService:
    """
    Factory: returns MockOcrService when use_mock=True, otherwise a real
    RapidOcrService (engine loads via `.load()`).
    """
    if use_mock:
        logger.info("Using MockOcrService (no OCR model loaded)")
        return MockOcrService()
    logger.info("Initialising RapidOCR", extra={"model_dir": str(model_dir)})
    return RapidOcrService(model_dir=model_dir)
