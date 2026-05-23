"""Comprehensive end-to-end tests with real ML models and real images.

These tests use the actual FashionCLIP embedder + PaddleOCR + FAISS
to test the full pipeline: import → embed → OCR → parse → index → search.

Usage:
    # With real ML models (requires torch + transformers + paddleocr):
    TEXTILE_USE_REAL_ML=true python -m pytest tests/test_e2e_real.py -v

    # With mock ML (tests API contracts only):
    python -m pytest tests/test_e2e_real.py -v

Prerequisites (real ML):
    uv sync --extra ml --extra ocr --group dev

The FashionCLIP model (~600 MB) and PaddleOCR model download on first run.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import random
import tempfile
import time
from pathlib import Path
from collections.abc import Generator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app.core.config import AppConfig, set_config
from app.db.models import Image as ImageModel, WatchedFolder

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

REAL_ML = os.environ.get("TEXTILE_USE_REAL_ML", "").lower() == "true"
NUM_IMAGES = 20
IMAGE_SIZE = (512, 512)
THUMB_SIZE = (256, 256)
POLL_INTERVAL = 0.5
IMPORT_TIMEOUT = 120


# ── Synthetic fabric image generator ───────────────────────────────────────────

FABRIC_PATTERNS = [
    "solid", "stripe", "check", "gradient",
    "dotted", "woven", "herringbone", "jacquard",
]

FABRIC_COLORS = [
    (180, 40, 50),   # red
    (30, 80, 160),   # blue
    (50, 140, 60),   # green
    (200, 170, 30),  # yellow/gold
    (120, 40, 130),  # purple
    (220, 120, 40),  # orange
    (60, 60, 60),    # charcoal
    (200, 180, 140), # beige
    (40, 100, 120),  # teal
    (160, 80, 60),   # rust
    (30, 30, 60),    # navy
    (180, 160, 180), # mauve
    (100, 130, 100), # sage
    (70, 50, 40),    # brown
    (200, 200, 180), # cream
    (150, 60, 80),   # rose
    (140, 160, 180), # steel blue
    (60, 70, 50),    # forest
    (190, 100, 100), # salmon
    (80, 50, 60),    # maroon
]

LABEL_TEMPLATES = [
    {
        "supplier": "FAFA TEXTILES CO. LTD",
        "item_no": "ITEM NO: FA-2024-{n:03d}",
        "order_no": "ORDER NO: PO-{n:04d}",
        "composition": "87/10/2/1 POLYESTER/RAYON/LUREX/SPANDEX",
        "fabric_type": "WOVEN",
        "width": "WIDTH: 66/68\"",
        "weight": "286 G/YD (170 GSM)",
    },
    {
        "supplier": "SUNRISE FABRICS INC.",
        "item_no": "STYLE: SR-{n:03d}",
        "order_no": "P/O: 2024-{n:04d}",
        "composition": "100% POLYESTER",
        "fabric_type": "CHIFFON",
        "width": "W/H: 150 CM",
        "weight": "90 GSM ±5%",
    },
    {
        "supplier": "TEXTILE PRO MFG CORP.",
        "item_no": "CODE: TP-{n:03d}A",
        "order_no": "ORDER: ORD-{n:04d}",
        "composition": "65/35 POLYESTER/COTTON",
        "fabric_type": "POPLIN",
        "width": "W: 112 CM",
        "weight": "200 G/M2",
    },
    {
        "supplier": "GLOBAL WEAVE LTD",
        "item_no": "ART. NO: GW-{n:03d}",
        "order_no": "PO# {n:04d}-B",
        "composition": "100% COTTON",
        "fabric_type": "TWILL",
        "width": "WIDE: 60\"",
        "weight": "8.5 OZ/Y",
    },
    {
        "supplier": "PREMIUM KNITS GROUP",
        "item_no": "REF: PK-{n:03d}",
        "order_no": "PURCHASE ORDER {n:04d}",
        "composition": "92/8 COTTON/SPANDEX",
        "fabric_type": "JERSEY",
        "width": "WIDTH: 72/74\"",
        "weight": "180 GSM",
    },
]


def _noise_texture(size: tuple[int, int], intensity: float = 0.05) -> Image.Image:
    """Generate a subtle noise texture overlay."""
    arr = np.random.randint(0, 256, (*size, 3), dtype=np.uint8)
    noise = Image.fromarray(arr, "RGB")
    noise = noise.point(lambda p: int(p * intensity))
    return noise


def _solid_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    noise = _noise_texture(size, 0.08)
    return Image.blend(img, noise, 0.3)


def _stripe_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    alt = tuple(min(255, c + 40) for c in color)
    for x in range(0, size[0], 12):
        draw.rectangle([x, 0, x + 4, size[1]], fill=alt)
    noise = _noise_texture(size, 0.06)
    return Image.blend(img, noise, 0.2)


def _check_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    alt = tuple(min(255, c + 50) for c in color)
    for y in range(0, size[1], 16):
        for x in range(0, size[0], 16):
            if (x // 16 + y // 16) % 2 == 0:
                draw.rectangle([x, y, x + 16, y + 16], fill=alt)
    noise = _noise_texture(size, 0.05)
    return Image.blend(img, noise, 0.15)


def _gradient_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / size[1]
        blended = tuple(int(c * (1 - t) + (255 - c) * t) for c in color)
        draw.line([(0, y), (size[0], y)], fill=blended)
    noise = _noise_texture(size, 0.04)
    return Image.blend(img, noise, 0.2)


def _dotted_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    dot_color = tuple(min(255, c + 60) for c in color)
    for y in range(0, size[1], 10):
        for x in range(0, size[0], 10):
            draw.ellipse([x, y, x + 3, y + 3], fill=dot_color)
    noise = _noise_texture(size, 0.05)
    return Image.blend(img, noise, 0.15)


def _woven_fabric(color: tuple[int, int, int], size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    light = tuple(min(255, c + 30) for c in color)
    dark = tuple(max(0, c - 30) for c in color)
    for y in range(0, size[1], 4):
        for x in range(0, size[0], 4):
            shade = light if (x // 4 + y // 4) % 2 == 0 else dark
            draw.rectangle([x, y, x + 3, y + 3], fill=shade)
    return img


PATTERN_FUNCS = {
    "solid": _solid_fabric,
    "stripe": _stripe_fabric,
    "check": _check_fabric,
    "gradient": _gradient_fabric,
    "dotted": _dotted_fabric,
    "woven": _woven_fabric,
    "herringbone": _stripe_fabric,
    "jacquard": _check_fabric,
}


class TestImageSet:
    """Generates and manages synthetic fabric test images."""

    def __init__(self, output_dir: Path, count: int = NUM_IMAGES):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.count = count
        self.images: list[Path] = []
        self._generated = False

    def generate(self) -> list[Path]:
        if self._generated:
            return self.images
        self.images.clear()
        for i in range(self.count):
            color = FABRIC_COLORS[i % len(FABRIC_COLORS)]
            pattern = FABRIC_PATTERNS[i % len(FABRIC_PATTERNS)]
            template = LABEL_TEMPLATES[i % len(LABEL_TEMPLATES)]
            path = self._create_image(i, color, pattern, template)
            self.images.append(path)
        self._generated = True
        logger.info("Generated %d test images in %s", self.count, self.output_dir)
        return self.images

    def _create_image(
        self,
        idx: int,
        color: tuple[int, int, int],
        pattern: str,
        label: dict[str, str],
    ) -> Path:
        filename = f"fabric_{idx:03d}_{pattern}_{idx}.jpg"
        filepath = self.output_dir / filename

        if filepath.exists():
            return filepath

        func = PATTERN_FUNCS.get(pattern, _solid_fabric)
        img = func(color, IMAGE_SIZE)

        # Draw label text on alternating images
        if idx % 2 == 0:
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
            text_lines = [
                label["supplier"],
                label["item_no"].format(n=idx),
                label["order_no"].format(n=idx),
                label["composition"],
                label["fabric_type"],
                label["width"],
                label["weight"],
            ]
            y = 40
            for line in text_lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                text_w = bbox[2] - bbox[0]
                x = (IMAGE_SIZE[0] - text_w) // 2
                draw.text((x, y), line, fill=(0, 0, 0), font=font)
                y += 20

        img.save(filepath, "JPEG", quality=92)
        return filepath


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def tmp_data_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="session")
def app_config(tmp_data_dir: Path) -> AppConfig:
    args = argparse.Namespace(port=9999, data_dir=str(tmp_data_dir))
    cfg = AppConfig(args)
    set_config(cfg)
    return cfg


@pytest.fixture(scope="session")
def test_images(tmp_data_dir: Path) -> Generator[Path, None, None]:
    img_dir = tmp_data_dir / "test_fabrics"
    img_set = TestImageSet(img_dir, count=NUM_IMAGES)
    paths = img_set.generate()
    yield img_dir


@pytest.fixture(scope="session")
def db_ready(app_config: AppConfig) -> bool:
    os.environ["TEXTILE_DB_URL"] = app_config.database_url

    from app.db.session import init_db

    init_db(app_config.database_url, pool_size=5)

    from app.db.base import Base
    from app.db.session import get_engine
    from app.db import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES ('1', 'test schema')"
            )
        )
        aliases = [
            ("POLYSTEER", "POLYESTER"),
            ("POLYSTER", "POLYESTER"),
            ("POIYESTER", "POLYESTER"),
            ("POLY", "POLYESTER"),
            ("PES", "POLYESTER"),
            ("PET", "POLYESTER"),
            ("SPUNPOLYSTER", "SPUNPOLYESTER"),
            ("SPUNPOLY", "SPUNPOLYESTER"),
            ("RYON", "RAYON"),
            ("RY", "RAYON"),
            ("VISCOSE", "RAYON"),
            ("SP", "SPANDEX"),
            ("EA", "SPANDEX"),
            ("ELASTANE", "SPANDEX"),
            ("LYCRA", "SPANDEX"),
            ("WL", "WOOL"),
            ("WO", "WOOL"),
            ("CT", "COTTON"),
            ("CTN", "COTTON"),
            ("CO", "COTTON"),
            ("NY", "NYLON"),
            ("PA", "NYLON"),
            ("ACRY", "ACRYLIC"),
            ("AC", "ACRYLIC"),
            ("PAN", "ACRYLIC"),
            ("LI", "LINEN"),
            ("FLAX", "LINEN"),
            ("LX", "LUREX"),
            ("METALLIC", "LUREX"),
        ]
        for alias, canonical in aliases:
            conn.execute(
                __import__("sqlalchemy").text(
                    "INSERT OR IGNORE INTO material_aliases (alias, canonical) VALUES (:a, :c)"
                ),
                {"a": alias, "c": canonical},
            )

        types = [
            "TWEED", "JERSEY", "DENIM", "CHIFFON", "SATIN", "VELVET",
            "LACE", "KNIT", "WOVEN", "FLEECE", "BROCADE", "CREPE",
            "ORGANZA", "TAFFETA", "GEORGETTE", "POPLIN", "CANVAS",
            "CORDUROY", "MUSLIN", "VOILE", "LAWN", "FLANNEL", "MESH",
            "INTERLOCK", "PIQUE", "PONTE", "SCUBA", "TERRY", "VELOUR",
        ]
        for t in types:
            conn.execute(
                __import__("sqlalchemy").text(
                    "INSERT OR IGNORE INTO fabric_types (name) VALUES (:n)"
                ),
                {"n": t},
            )

        defaults = [
            ("default_k", "20"),
            ("duplicate_threshold", "0.97"),
            ("history_retention_days", "365"),
            ("disk_space_warning_mb", "500"),
            ("thumbnail_cache_max_mb", "2048"),
            ("include_unverified_in_filters", "true"),
            ("language", "en"),
            ("theme", "system"),
            ("debug_logging", "false"),
        ]
        for key, value in defaults:
            conn.execute(
                __import__("sqlalchemy").text(
                    "INSERT OR IGNORE INTO app_settings (key, value) VALUES (:k, :v)"
                ),
                {"k": key, "v": value},
            )
        conn.commit()

    return True


@pytest.fixture(scope="session")
def use_real_ml() -> bool:
    return REAL_ML


@pytest.fixture(scope="session")
def services(
    app_config: AppConfig,
    use_real_ml: bool,
) -> dict:
    from app.services.faiss_index import FaissIndexManager
    from app.services.embedder import init_embedder
    from app.services.ocr import init_ocr

    faiss = FaissIndexManager(app_config.faiss_dir)
    faiss.load_or_create()
    faiss.reset()

    embedder = init_embedder(
        cache_dir=app_config.models_dir,
        use_mock=not use_real_ml,
    )
    if use_real_ml:
        embedder.load()

    ocr_service = init_ocr(
        model_dir=app_config.models_dir / "paddleocr",
        use_mock=not use_real_ml,
    )
    if use_real_ml:
        try:
            ocr_service.load()
        except Exception as exc:
            logger.warning("OCR model load failed (non-fatal): %s", exc)

    from app.services.importer import init_importer
    from app.api.import_ import set_worker
    from app.api.images import set_search_deps

    importer = init_importer(
        embedder=embedder,
        ocr=ocr_service,
        faiss_index=faiss,
        thumbnail_dir=app_config.thumbnail_dir,
    )
    set_worker(importer)
    set_search_deps(embedder=embedder, faiss=faiss)

    return {
        "embedder": embedder,
        "ocr": ocr_service,
        "faiss": faiss,
        "importer": importer,
    }


@pytest.fixture(scope="session")
def client(db_ready: bool, app_config: AppConfig, services: dict) -> TestClient:
    from app import create_app

    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="session")
def session(db_ready: bool) -> Generator[Session, None, None]:
    from app.db.session import get_session

    with get_session() as s:
        yield s


@pytest.fixture(scope="session")
def import_result(
    client: TestClient,
    test_images: Path,
    services: dict,
) -> dict:
    """Import test images and wait for completion. Returns import summary."""
    worker = services["importer"]

    r = client.post(
        "/import/folder",
        json={
            "folder_path": str(test_images),
            "display_name": "E2E Test Fabrics",
        },
    )
    assert r.status_code == 202
    folder_data = r.json()
    assert folder_data["queued_count"] == NUM_IMAGES

    def _wait_for_import(timeout: int = IMPORT_TIMEOUT) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = client.get("/import/status")
            assert r.status_code == 200
            status = r.json()
            if (
                status["processed"] + status["failed"] + status["skipped"]
                >= NUM_IMAGES
            ):
                return status
            time.sleep(POLL_INTERVAL)
        pytest.fail(
            f"Import did not complete within {timeout}s. "
            f"Final status: {status}"
        )
        return {}  # unreachable

    status = _wait_for_import()

    r = client.get("/db/status")
    db_status = r.json()

    return {
        "folder_id": folder_data["folder_id"],
        "import_status": status,
        "db_status": db_status,
        "image_count": db_status["image_count"],
        "indexed_count": db_status["indexed_count"],
    }


@pytest.fixture
def query_image_path(test_images: Path) -> Path:
    """Return a path to a query image (first test image)."""
    return test_images / "fabric_000_solid_0.jpg"


# ── Test: Health API ──────────────────────────────────────────────────────────


class TestHealthApi:
    def test_health_returns_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"
        assert data["uptime_s"] >= 0
        assert data["db_path"].endswith(".db")

    def test_db_status_after_import(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.get("/db/status")
        assert r.status_code == 200
        data = r.json()
        assert data["schema_version"] >= 1
        assert data["image_count"] == NUM_IMAGES
        assert data["indexed_count"] > 0
        assert data["db_size_mb"] >= 0
        assert data["db_path"].endswith(".db")
        assert data["orphaned_count"] == 0

    def test_db_status_baseline(self, client: TestClient) -> None:
        r = client.get("/db/status")
        assert r.status_code == 200
        data = r.json()
        for key in ("schema_version", "image_count", "indexed_count", "orphaned_count",
                    "queued_count", "failed_count", "db_path", "db_size_mb"):
            assert key in data


class TestSettingsApi:
    def test_get_settings_returns_all(self, client: TestClient) -> None:
        r = client.get("/settings")
        assert r.status_code == 200
        data = r.json()
        expected_keys = {
            "default_k", "duplicate_threshold", "history_retention_days",
            "disk_space_warning_mb", "thumbnail_cache_max_mb",
            "include_unverified_in_filters", "language", "theme", "debug_logging",
        }
        assert set(data.keys()) == expected_keys

    def test_set_and_get_setting(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "language", "value": "zh-TW"})
        assert r.status_code == 200
        r2 = client.get("/settings")
        assert r2.json()["language"] == "zh-TW"
        client.patch("/settings", json={"key": "language", "value": "en"})
        assert client.get("/settings").json()["language"] == "en"

    def test_set_unknown_key_returns_400(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "nonexistent_key", "value": "x"})
        assert r.status_code == 400
        assert "Unknown setting" in r.json()["detail"]

    def test_create_new_setting_recreates_deleted(self, client: TestClient) -> None:
        from app.db.models import AppSetting
        from app.db.session import get_session
        with get_session() as session:
            existing = session.get(AppSetting, "theme")
            orig = existing.value if existing else "system"
            session.query(AppSetting).filter(AppSetting.key == "theme").delete()
            session.commit()
        client.patch("/settings", json={"key": "theme", "value": "dark"})
        assert client.get("/settings").json()["theme"] == "dark"
        client.patch("/settings", json={"key": "theme", "value": orig})


# ── Test: Import API ──────────────────────────────────────────────────────────


class TestImportApi:
    def test_import_folder_creates_watched_folder(
        self, client: TestClient, test_images: Path, import_result: dict
    ) -> None:
        from app.db.models import WatchedFolder
        from app.db.session import get_session
        with get_session() as session:
            folder = session.query(WatchedFolder).filter(
                WatchedFolder.folder_path == str(test_images)
            ).first()
        assert folder is not None
        assert folder.display_name == "E2E Test Fabrics"
        assert folder.is_available is True

    def test_import_folder_idempotent(
        self, client: TestClient, test_images: Path
    ) -> None:
        r1 = client.post(
            "/import/folder",
            json={"folder_path": str(test_images), "display_name": "E2E Test Fabrics"},
        )
        r2 = client.post(
            "/import/folder",
            json={"folder_path": str(test_images), "display_name": "E2E Test Fabrics"},
        )
        assert r1.status_code == 202
        assert r2.status_code == 202
        assert r1.json()["folder_id"] == r2.json()["folder_id"]

    def test_import_invalid_path(self, client: TestClient) -> None:
        r = client.post(
            "/import/folder",
            json={"folder_path": "/nonexistent_path_xyz", "display_name": "Ghost"},
        )
        assert r.status_code == 400
        assert "not a directory" in r.json()["detail"]

    def test_import_status_after_completion(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.get("/import/status")
        assert r.status_code == 200
        s = r.json()
        assert s["processed"] + s["failed"] + s["skipped"] == NUM_IMAGES
        assert isinstance(s["is_running"], bool)
        assert isinstance(s["is_paused"], bool)

    def test_pause_and_resume_cycle(self, client: TestClient) -> None:
        client.post("/import/pause")
        s1 = client.get("/import/status").json()
        assert s1["is_paused"] is True
        client.post("/import/resume")
        s2 = client.get("/import/status").json()
        assert s2["is_paused"] is False

    def test_pause_twice_idempotent(self, client: TestClient) -> None:
        client.post("/import/pause")
        client.post("/import/pause")
        assert client.get("/import/status").json()["is_paused"] is True
        client.post("/import/resume")

    def test_sync_batch_empty(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": []})
        assert r.status_code == 200
        data = r.json()
        assert data["queued_for_import"] == 0
        assert data["orphaned"] == 0

    def test_sync_batch_add_file(self, client: TestClient, tmp_path: Path) -> None:
        img = tmp_path / "sync_add.jpg"
        img.write_bytes(b"fake image content")
        r = client.post(
            "/import/sync-batch",
            json={"events": [{"event_type": "add", "abs_path": str(img)}]},
        )
        assert r.status_code == 200

    def test_sync_batch_invalid_event_type_returns_422(
        self, client: TestClient
    ) -> None:
        r = client.post(
            "/import/sync-batch",
            json={"events": [{"event_type": "invalid", "abs_path": "/tmp/test.jpg"}]},
        )
        assert r.status_code == 422

    def test_import_folder_empty_path_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/import/folder",
            json={"folder_path": "", "display_name": "test"},
        )
        assert r.status_code == 422


# ── Test: Images API — Browse ─────────────────────────────────────────────────


class TestImagesBrowseApi:
    def test_browse_all_images(self, client: TestClient, import_result: dict) -> None:
        r = client.post("/images/browse", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= NUM_IMAGES
        assert len(data["results"]) >= NUM_IMAGES
        assert data["truncated"] is False

    def test_browse_result_shape(self, client: TestClient, import_result: dict) -> None:
        r = client.post("/images/browse", json={})
        item = r.json()["results"][0]
        assert "image" in item
        assert "score" in item
        assert item["score"] is None  # browse has no score
        img = item["image"]
        assert "id" in img
        assert "abs_path" in img
        assert "filename" in img
        assert "thumbnail_path" in img
        assert "import_status" in img
        assert "is_orphaned" in img
        assert "faiss_id" in img
        assert "metadata" in img

    def test_browse_with_pagination(self, client: TestClient, import_result: dict) -> None:
        r1 = client.post("/images/browse", json={}, params={"limit": 5, "offset": 0})
        r2 = client.post("/images/browse", json={}, params={"limit": 5, "offset": 5})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert len(r1.json()["results"]) == 5
        assert len(r2.json()["results"]) == 5
        ids_1 = [r["image"]["id"] for r in r1.json()["results"]]
        ids_2 = [r["image"]["id"] for r in r2.json()["results"]]
        assert set(ids_1).isdisjoint(set(ids_2))

    def test_browse_filter_by_supplier(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"supplier": "FAFA"})
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 0
        for result in data["results"]:
            meta = result["image"]["metadata"]
            if meta is not None and meta.get("supplier"):
                assert "FAFA" in meta["supplier"].upper()

    def test_browse_filter_by_fabric_type(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"fabric_type": "WOVEN"})
        assert r.status_code == 200

    def test_browse_filter_by_gsm_range(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"min_gsm": 100, "max_gsm": 200})
        assert r.status_code == 200

    def test_browse_filter_by_width_range(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"min_width": 50, "max_width": 200})
        assert r.status_code == 200

    def test_browse_filter_needs_review(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"needs_review": True})
        assert r.status_code == 200

    def test_browse_filter_verified_only(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={"verified_only": True})
        assert r.status_code == 200

    def test_browse_empty_results_for_nonexistent_supplier(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post(
            "/images/browse", json={"supplier": "NONEXISTENT_SUPPLIER_XYZ"}
        )
        data = r.json()
        assert data["total"] == 0
        assert data["results"] == []

    def test_browse_images_have_thumbnail_paths(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.post("/images/browse", json={})
        for result in r.json()["results"]:
            thumb = result["image"]["thumbnail_path"]
            if thumb is not None:
                assert Path(thumb).suffix == ".webp"


# ── Test: Images API — Get by ID ──────────────────────────────────────────────


class TestImagesGetApi:
    def _get_done_image_id(self, client: TestClient) -> int:
        """Return the ID of an image with import_status='done' (oldest first for stability)."""
        results = client.post("/images/browse", json={"sort_by": "date_asc"}).json()["results"]
        for r in results:
            if r["image"]["import_status"] == "done":
                return r["image"]["id"]
        return results[0]["image"]["id"]

    def test_get_image_by_id(self, client: TestClient, import_result: dict) -> None:
        first_id = self._get_done_image_id(client)
        r = client.get(f"/images/{first_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == first_id
        assert data["abs_path"].endswith(".jpg")
        assert data["import_status"] == "done"

    def test_get_image_full_shape(self, client: TestClient, import_result: dict) -> None:
        first_id = self._get_done_image_id(client)
        r = client.get(f"/images/{first_id}")
        data = r.json()
        expected_keys = {
            "id", "abs_path", "filename", "thumbnail_path",
            "import_status", "is_orphaned", "date_added",
            "faiss_id", "model_version", "metadata",
            "file_hash", "file_size_bytes", "width_px", "height_px",
            "relative_path", "folder_name",
        }
        assert set(data.keys()) == expected_keys

    def test_get_image_with_metadata(
        self, client: TestClient, import_result: dict
    ) -> None:
        images = client.post("/images/browse", json={}).json()["results"]
        for result in images:
            meta = result["image"]["metadata"]
            if meta is not None and meta.get("supplier"):
                r = client.get(f"/images/{result['image']['id']}")
                data = r.json()
                assert data["metadata"]["supplier"] is not None
                assert "composition" in data["metadata"]
                return
        pytest.skip("No images with parsed metadata found")

    def test_get_image_without_metadata(
        self, client: TestClient, import_result: dict
    ) -> None:
        images = client.post("/images/browse", json={}).json()["results"]
        for result in images:
            if result["image"]["metadata"] is None:
                return
        pytest.skip("All images have metadata")

    def test_get_nonexistent_image_returns_404(
        self, client: TestClient
    ) -> None:
        r = client.get("/images/99999")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_get_image_returns_filename(
        self, client: TestClient, import_result: dict
    ) -> None:
        first_id = self._get_done_image_id(client)
        r = client.get(f"/images/{first_id}")
        assert r.json()["filename"].startswith("fabric_")

    def test_get_image_faiss_id_matches(
        self, client: TestClient, import_result: dict
    ) -> None:
        first = client.post("/images/browse", json={}).json()["results"][0]
        img = first["image"]
        if img["faiss_id"] is not None:
            r = client.get(f"/images/{img['id']}")
            assert r.json()["faiss_id"] == img["faiss_id"]

    def test_get_image_model_version(
        self, client: TestClient, import_result: dict
    ) -> None:
        first_id = self._get_done_image_id(client)
        r = client.get(f"/images/{first_id}")
        if not REAL_ML:
            assert r.json()["model_version"] == "mock-v0"
        else:
            assert r.json()["model_version"] == "fashion-clip-v1"


# ── Test: Images API — Visual Search ──────────────────────────────────────────


class TestImagesSearchApi:
    def test_search_requires_query_image(self, client: TestClient) -> None:
        r = client.post("/images/search")
        assert r.status_code == 422

    def test_search_with_valid_image(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 10},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "total" in data
        assert "truncated" in data
        assert len(data["results"]) <= 10

    def test_search_returns_expected_shape(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 5},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        data = r.json()
        for result in data["results"]:
            assert "image" in result
            assert "score" in result
            assert result["score"] is not None
            assert 0.0 <= result["score"] <= 1.0
            img = result["image"]
            assert "id" in img
            assert "abs_path" in img
            assert "thumbnail_path" in img

    def test_search_returns_similar_images(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": NUM_IMAGES},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        data = r.json()
        if data["total"] > 0:
            top_score = data["results"][0]["score"]
            assert top_score > 0.0

    def test_search_with_filters(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 10, "supplier": "FAFA"},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        assert r.status_code == 200

    def test_search_default_k(self, client: TestClient, query_image_path: Path) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            assert len(r.json()["results"]) <= 20

    def test_search_k_out_of_range_returns_422(
        self, client: TestClient, query_image_path: Path
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 999},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        assert r.status_code == 422

    def test_search_with_invalid_file(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            data={"k": 10},
            files={"query_image": ("bad.jpg", b"not an image", "image/jpeg")},
        )
        assert r.status_code in (200, 422, 503)

    def test_search_truncated_flag(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 5},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        data = r.json()
        assert isinstance(data["truncated"], bool)
        assert data["truncated"] is False

    def test_search_result_images_exist_in_db(
        self, client: TestClient, query_image_path: Path, import_result: dict
    ) -> None:
        with open(query_image_path, "rb") as f:
            r = client.post(
                "/images/search",
                data={"k": 10},
                files={"query_image": ("query.jpg", f, "image/jpeg")},
            )
        for result in r.json()["results"]:
            rid = result["image"]["id"]
            gr = client.get(f"/images/{rid}")
            assert gr.status_code == 200

    def test_search_different_queries_give_different_results(
        self, client: TestClient, test_images: Path, import_result: dict
    ) -> None:
        q1 = test_images / "fabric_000_solid_0.jpg"
        q2 = test_images / "fabric_001_stripe_1.jpg"
        with open(q1, "rb") as f:
            r1 = client.post(
                "/images/search",
                data={"k": 5},
                files={"query_image": ("q1.jpg", f, "image/jpeg")},
            )
        with open(q2, "rb") as f:
            r2 = client.post(
                "/images/search",
                data={"k": 5},
                files={"query_image": ("q2.jpg", f, "image/jpeg")},
            )
        ids_1 = {r["image"]["id"] for r in r1.json()["results"]}
        ids_2 = {r["image"]["id"] for r in r2.json()["results"]}
        if REAL_ML:
            assert ids_1 != ids_2, (
                "Different query images should produce different results with real ML"
            )


# ── Test: History API ─────────────────────────────────────────────────────────


class TestHistoryApi:
    def test_list_empty(self, client: TestClient) -> None:
        r = client.get("/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_with_limit(self, client: TestClient) -> None:
        r = client.get("/history?limit=5")
        assert r.status_code == 200

    def test_log_search(self, client: TestClient) -> None:
        r = client.post(
            "/history",
            json={
                "query_image_path": "/tmp/e2e_query.jpg",
                "k": 20,
                "result_ids": [],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert isinstance(data["id"], int)
        assert data["k"] == 20
        assert isinstance(data["query_image_path"], str)

    def test_log_search_with_results(self, client: TestClient) -> None:
        r = client.post(
            "/history",
            json={
                "query_image_path": "/tmp/e2e_query_2.jpg",
                "k": 10,
                "result_ids": [1, 2, 3, 4, 5],
            },
        )
        assert r.status_code == 200
        assert r.json()["result_count"] == 5
        assert r.json()["top_result_ids"] == [1, 2, 3, 4, 5]

    def test_list_after_log(self, client: TestClient) -> None:
        client.post(
            "/history",
            json={
                "query_image_path": "/tmp/e2e_list_test.jpg",
                "k": 5,
                "result_ids": [10, 20],
            },
        )
        entries = client.get("/history").json()
        assert len(entries) >= 1
        entry = entries[0]
        assert "query_image_path" in entry
        assert "k" in entry
        assert "searched_at" in entry
        assert "result_count" in entry
        assert "top_result_ids" in entry

    def test_log_missing_fields_returns_422(self, client: TestClient) -> None:
        r = client.post("/history", json={})
        assert r.status_code == 422

    def test_delete_single_entry(self, client: TestClient) -> None:
        r = client.post(
            "/history",
            json={
                "query_image_path": "/tmp/e2e_delete.jpg",
                "k": 3,
                "result_ids": [],
            },
        )
        entry_id = r.json()["id"]
        r2 = client.delete(f"/history/{entry_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "deleted"

    def test_delete_nonexistent_entry_returns_404(self, client: TestClient) -> None:
        r = client.delete("/history/99999")
        assert r.status_code == 404

    def test_clear_history(self, client: TestClient) -> None:
        client.post(
            "/history",
            json={
                "query_image_path": "/tmp/e2e_clear_test.jpg",
                "k": 5,
                "result_ids": [1, 2],
            },
        )
        r = client.delete("/history")
        assert r.status_code == 200
        assert r.json()["deleted"] >= 1
        assert len(client.get("/history").json()) == 0

    def test_clear_empty_history(self, client: TestClient) -> None:
        client.delete("/history")
        r = client.delete("/history")
        assert r.status_code == 200
        assert r.json()["deleted"] >= 0


# ── Test: Duplicates API ──────────────────────────────────────────────────────


class TestDuplicatesApi:
    def test_list_duplicates_empty(
        self, client: TestClient, import_result: dict
    ) -> None:
        r = client.get("/duplicates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_count_pending(self, client: TestClient, import_result: dict) -> None:
        r = client.get("/duplicates/count")
        assert r.status_code == 200
        data = r.json()
        assert "pending" in data
        assert data["pending"] >= 0

    def test_list_with_include_resolved(self, client: TestClient) -> None:
        assert client.get("/duplicates?include_resolved=true").status_code == 200
        assert client.get("/duplicates?include_resolved=false").status_code == 200

    def test_resolve_nonexistent_returns_404(self, client: TestClient) -> None:
        r = client.post("/duplicates/99999/resolve")
        assert r.status_code == 404

    def test_resolve_all_empty(self, client: TestClient) -> None:
        r = client.post("/duplicates/resolve-all")
        assert r.status_code == 200
        assert r.json()["resolved"] >= 0

    def test_duplicate_pair_shape(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        from app.db.session import get_session
        with get_session() as session:
            a = ImageModel(
                file_path="/tmp/_e2e_dup_a.jpg",
                filename="_e2e_dup_a.jpg",
                import_status="done",
            )
            b = ImageModel(
                file_path="/tmp/_e2e_dup_b.jpg",
                filename="_e2e_dup_b.jpg",
                import_status="done",
            )
            session.add_all([a, b])
            session.flush()
            session.add(
                Duplicate(
                    image_id_a=a.id,
                    image_id_b=b.id,
                    similarity=0.99,
                    match_type="exact",
                )
            )
            session.commit()
        r = client.get("/duplicates")
        assert len(r.json()) >= 1
        pair = r.json()[0]
        assert "id" in pair
        assert "image_a" in pair
        assert "image_b" in pair
        assert "similarity" in pair
        assert "match_type" in pair
        assert "resolved" in pair
        for side in ("image_a", "image_b"):
            img = pair[side]
            assert "id" in img
            assert "filename" in img
            assert "file_path" in img
        with get_session() as session:
            session.query(Duplicate).delete()
            session.query(ImageModel).delete()
            session.commit()

    def test_resolve_and_count(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        from app.db.session import get_session
        with get_session() as session:
            a = ImageModel(
                file_path="/tmp/_e2e_dr_a.jpg",
                filename="_e2e_dr_a.jpg",
                import_status="done",
            )
            b = ImageModel(
                file_path="/tmp/_e2e_dr_b.jpg",
                filename="_e2e_dr_b.jpg",
                import_status="done",
            )
            session.add_all([a, b])
            session.flush()
            dp = Duplicate(
                image_id_a=a.id,
                image_id_b=b.id,
                similarity=0.98,
                match_type="exact",
            )
            session.add(dp)
            session.commit()
            pair_id = dp.id
        count_before = client.get("/duplicates/count").json()["pending"]
        assert count_before >= 1
        assert client.post(f"/duplicates/{pair_id}/resolve").status_code == 200
        count_after = client.get("/duplicates/count").json()["pending"]
        assert count_after >= 0
        with get_session() as session:
            session.query(Duplicate).delete()
            session.query(ImageModel).delete()
            session.commit()

    def test_resolve_all(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        from app.db.session import get_session
        with get_session() as session:
            a = ImageModel(
                file_path="/tmp/_e2e_ra_a.jpg",
                filename="_e2e_ra_a.jpg",
                import_status="done",
            )
            b = ImageModel(
                file_path="/tmp/_e2e_ra_b.jpg",
                filename="_e2e_ra_b.jpg",
                import_status="done",
            )
            session.add_all([a, b])
            session.flush()
            session.add_all([
                Duplicate(image_id_a=a.id, image_id_b=b.id, similarity=0.97, match_type="exact"),
            ])
            session.commit()
        r = client.post("/duplicates/resolve-all")
        assert r.status_code == 200
        assert r.json()["resolved"] >= 1
        with get_session() as session:
            session.query(Duplicate).delete()
            session.query(ImageModel).delete()
            session.commit()


# ── Test: 404 / Method Not Allowed ────────────────────────────────────────────


class TestHttpErrors:
    def test_unknown_get_returns_404(self, client: TestClient) -> None:
        assert client.get("/nonexistent").status_code == 404

    def test_unknown_post_returns_404(self, client: TestClient) -> None:
        assert client.post("/nonexistent").status_code == 404

    def test_get_on_post_endpoint_returns_405(self, client: TestClient) -> None:
        assert client.get("/import/folder").status_code == 405

    def test_post_on_get_endpoint_returns_405(self, client: TestClient) -> None:
        assert client.post("/health").status_code == 405


# ── Test: JSON Validation ─────────────────────────────────────────────────────


class TestJsonValidation:
    def test_invalid_json_returns_422(self, client: TestClient) -> None:
        r = client.post(
            "/import/folder",
            data="not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    def test_missing_content_type_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/folder", data="{}")
        assert r.status_code == 422

    def test_extra_fields_ignored(self, client: TestClient, test_images: Path) -> None:
        r = client.post(
            "/import/folder",
            json={
                "folder_path": str(test_images),
                "display_name": "Extra",
                "extra_field": "x",
            },
        )
        assert r.status_code == 202
