"""
TextileSearch — Custom Exception Hierarchy

All exceptions raised by the backend inherit from TextileSearchError.
This makes error handling explicit: callers catch specific types, not broad
Exception or BaseException. No bare `except:` is ever used in this codebase.

Usage:
    from app.exceptions import EmbedderNotReadyError, ParseError
    raise ParseError("Composition percentages do not sum to 100%", raw_text=raw)
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# Root
# ─────────────────────────────────────────────────────────────────────────────

class TextileSearchError(Exception):
    """Base class for all application-level errors."""


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

class ConfigError(TextileSearchError):
    """Raised when app configuration is missing or invalid."""


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

class DatabaseError(TextileSearchError):
    """Base class for database-related errors."""


class MigrationError(DatabaseError):
    """Raised when a database migration fails."""


class SessionNotInitialisedError(DatabaseError):
    """Raised when get_session() is called before init_db()."""


# ─────────────────────────────────────────────────────────────────────────────
# ML / Embedder
# ─────────────────────────────────────────────────────────────────────────────

class EmbedderError(TextileSearchError):
    """Base class for embedding errors."""


class ModelNotAvailableError(EmbedderError):
    """
    Raised when the FashionCLIP model weights are not present on disk.
    The app continues operating — affected images are queued for later indexing.
    """

    def __init__(self, model_path: str) -> None:
        super().__init__(
            f"Model weights not found at '{model_path}'. "
            f"Install them with: python scripts/download_models.py"
        )
        self.model_path = model_path


class EmbeddingFailedError(EmbedderError):
    """Raised when embedding an image fails (corrupted file, unsupported format)."""

    def __init__(self, image_path: str, reason: str) -> None:
        super().__init__(f"Failed to embed '{image_path}': {reason}")
        self.image_path = image_path
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

class OcrError(TextileSearchError):
    """Base class for OCR errors."""


class OcrModelNotAvailableError(OcrError):
    """Raised when PaddleOCR model files are not present."""

    def __init__(self, model_path: str) -> None:
        super().__init__(
            f"PaddleOCR model not found at '{model_path}'. "
            f"Install with: pip install paddlepaddle paddleocr"
        )
        self.model_path = model_path


class OcrProcessingError(OcrError):
    """Raised when OCR processing fails for a specific image."""

    def __init__(self, image_path: str, reason: str) -> None:
        super().__init__(f"OCR failed for '{image_path}': {reason}")
        self.image_path = image_path
        self.reason = reason


# ─────────────────────────────────────────────────────────────────────────────
# FAISS Index
# ─────────────────────────────────────────────────────────────────────────────

class FaissError(TextileSearchError):
    """Base class for FAISS index errors."""


class IndexNotInitialisedError(FaissError):
    """Raised when the FAISS index is used before being initialised."""


class IndexCorruptedError(FaissError):
    """Raised when the FAISS index file fails its integrity check on load."""

    def __init__(self, index_path: str) -> None:
        super().__init__(
            f"FAISS index at '{index_path}' is corrupted. "
            f"It will be rebuilt from the database automatically."
        )
        self.index_path = index_path


class IndexWriteError(FaissError):
    """Raised when writing the FAISS index to disk fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Field Parser
# ─────────────────────────────────────────────────────────────────────────────

class ParseError(TextileSearchError):
    """Raised when a label field cannot be parsed and no fallback is possible."""

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class CompositionSumError(ParseError):
    """
    Raised when parsed composition percentages do not sum to 100% (±2% tolerance).
    Always forces the composition result to Tier 2 — requires user confirmation.
    """

    def __init__(self, actual_sum: float, raw_text: str) -> None:
        super().__init__(
            f"Composition percentages sum to {actual_sum:.1f}%, expected 100% (±2%).",
            raw_text=raw_text,
        )
        self.actual_sum = actual_sum


# ─────────────────────────────────────────────────────────────────────────────
# Import pipeline
# ─────────────────────────────────────────────────────────────────────────────

class ImportError(TextileSearchError):
    """Base class for import pipeline errors."""


class UnsupportedFileTypeError(ImportError):
    """Raised when an image format is not in the supported whitelist."""

    def __init__(self, file_path: str, extension: str) -> None:
        super().__init__(f"Unsupported file type '{extension}' for '{file_path}'")
        self.file_path = file_path
        self.extension = extension


class ImageReadError(ImportError):
    """Raised when an image file cannot be opened (corrupted, truncated, locked)."""

    def __init__(self, file_path: str, reason: str) -> None:
        super().__init__(f"Cannot read image '{file_path}': {reason}")
        self.file_path = file_path
        self.reason = reason


class DiskSpaceError(ImportError):
    """Raised when free disk space falls below the configured threshold."""

    def __init__(self, free_mb: float, threshold_mb: float) -> None:
        super().__init__(
            f"Disk space critically low: {free_mb:.0f} MB free, "
            f"threshold is {threshold_mb:.0f} MB."
        )
        self.free_mb = free_mb
        self.threshold_mb = threshold_mb


# ─────────────────────────────────────────────────────────────────────────────
# File System Sync
# ─────────────────────────────────────────────────────────────────────────────

class SyncError(TextileSearchError):
    """Base class for file system sync errors."""


class FolderNotWatchedError(SyncError):
    """Raised when an operation references a folder not in watched_folders."""

    def __init__(self, folder_path: str) -> None:
        super().__init__(f"Folder '{folder_path}' is not in the watched folder list.")
        self.folder_path = folder_path


class FolderUnavailableError(SyncError):
    """
    Raised when a watched folder is no longer accessible on disk
    (drive disconnected, folder deleted, permissions revoked).
    Import is paused — not failed — for this folder.
    """

    def __init__(self, folder_path: str) -> None:
        super().__init__(
            f"Folder '{folder_path}' is no longer accessible. "
            f"Import paused. Reconnect the drive and sync to resume."
        )
        self.folder_path = folder_path
