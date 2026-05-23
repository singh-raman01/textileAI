"""Shared pytest fixtures for all Phase 1 tests."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import AppConfig, set_config
from app.services.embedder import MockEmbedder
from app.services.ocr import MockOcrService


# ─────────────────────────────────────────────────────────────────────────────
# Directories
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def tmp_data_dir() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope="session")
def app_config(tmp_data_dir: Path) -> AppConfig:
    args = argparse.Namespace(port=9998, data_dir=str(tmp_data_dir))
    cfg = AppConfig(args)
    set_config(cfg)
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_ready(app_config: AppConfig) -> bool:
    os.environ["TEXTILE_DB_URL"] = app_config.database_url

    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    alembic_cfg = AlembicConfig(str(Path(__file__).parent.parent / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location",
        str(Path(__file__).parent.parent / "migrations"),
    )
    alembic_cfg.set_main_option("sqlalchemy.url", app_config.database_url)
    alembic_command.upgrade(alembic_cfg, "head")

    from app.db.session import init_db
    init_db(app_config.database_url)
    return True


@pytest.fixture
def session(db_ready: bool) -> Generator[Session, None, None]:
    from app.db.session import get_session
    with get_session() as s:
        yield s


# ─────────────────────────────────────────────────────────────────────────────
# Mock services
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def mock_embedder() -> MockEmbedder:
    return MockEmbedder()


@pytest.fixture(scope="session")
def mock_ocr() -> MockOcrService:
    return MockOcrService()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI test client
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client(db_ready: bool, app_config: AppConfig) -> TestClient:
    os.environ["TEXTILE_USE_MOCK_ML"] = "true"

    from app.services.faiss_index import init_faiss
    from app.services.embedder import init_embedder
    from app.services.ocr import init_ocr
    from app.services.importer import init_importer
    from app.api.import_ import set_worker

    faiss = init_faiss(app_config.faiss_dir)
    emb   = init_embedder(use_mock=True)
    ocr   = init_ocr(use_mock=True)
    importer = init_importer(
        embedder=emb,
        ocr=ocr,
        faiss_index=faiss,
        thumbnail_dir=app_config.thumbnail_dir,
    )
    set_worker(importer)

    from app import create_app
    return TestClient(create_app())
