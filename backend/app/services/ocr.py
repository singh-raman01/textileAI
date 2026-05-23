"""
TextileSearch — OCR Service

Wraps PaddleOCR v3 for offline label text extraction.
Handles rotated labels, English + Traditional Chinese text.

Lazy loading — same pattern as embedder.py.
MockOcrService provides canned responses for testing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.exceptions import OcrModelNotAvailableError, OcrProcessingError
from app.services.protocols import BoundingBox, OcrResult, OcrProtocol, TextRegion

logger = logging.getLogger(__name__)

PADDLE_LANG: Final[str] = "en"     # "ch" for Chinese labels
PADDLE_USE_GPU: Final[bool] = False


class PaddleOcrService:
    """
    Production OCR using PaddleOCR v3.
    Auto-rotation is enabled (rotate=True) to handle upside-down labels.
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._ocr: object | None = None
        self._loaded: bool = False

    @property
    def is_ready(self) -> bool:
        return self._loaded

    def load(self) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]
        except ImportError as exc:
            raise OcrModelNotAvailableError(str(self._model_dir)) from exc

        try:
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang=PADDLE_LANG,
                use_gpu=PADDLE_USE_GPU,
                show_log=False,
            )
        except Exception as exc:
            raise OcrModelNotAvailableError(str(self._model_dir)) from exc

        self._loaded = True
        logger.info("PaddleOCR loaded", extra={"lang": PADDLE_LANG})

    def extract(self, image_path: Path) -> OcrResult:
        if not self._loaded or self._ocr is None:
            raise OcrModelNotAvailableError(str(self._model_dir))

        t0 = time.monotonic()
        try:
            raw = self._ocr.ocr(str(image_path), cls=True)
        except Exception as exc:
            raise OcrProcessingError(str(image_path), str(exc)) from exc

        ms = (time.monotonic() - t0) * 1000
        return _build_result(str(image_path), raw, ms)


def _build_result(image_path: str, raw: list[object], duration_ms: float) -> OcrResult:
    """Convert PaddleOCR raw output to OcrResult."""
    regions: list[TextRegion] = []

    if not raw or raw[0] is None:
        return OcrResult(
            image_path=image_path,
            text_regions=[],
            full_text="",
            mean_confidence=0.0,
            has_text=False,
            duration_ms=duration_ms,
        )

    for line in raw[0]:  # PaddleOCR: list of [bbox, (text, score)]
        try:
            bbox_pts = line[0]
            text: str = line[1][0]
            conf: float = float(line[1][1])
            xs = [float(p[0]) for p in bbox_pts]
            ys = [float(p[1]) for p in bbox_pts]
            bb = BoundingBox(
                x_min=min(xs), y_min=min(ys),
                x_max=max(xs), y_max=max(ys),
            )
            regions.append(TextRegion(text=text, confidence=conf, bounding_box=bb))
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
        import time
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
