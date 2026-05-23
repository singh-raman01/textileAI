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

    from app.db.session import init_db
    init_db(app_config.database_url, pool_size=5)

    from app.db.base import Base
    from app.db.session import get_engine
    from app.db import models  # noqa: F401 — register all models

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Seed material aliases
    with engine.connect() as conn:
        aliases = [
            ('POLYSTEER',    'POLYESTER'), ('POLYSTER',     'POLYESTER'),
            ('POIYESTER',    'POLYESTER'), ('POLY',         'POLYESTER'),
            ('PES',          'POLYESTER'), ('PET',          'POLYESTER'),
            ('SPUNPOLYSTER', 'SPUNPOLYESTER'), ('SPUNPOLY', 'SPUNPOLYESTER'),
            ('RYON',         'RAYON'),     ('RY',           'RAYON'),
            ('VISCOSE',      'RAYON'),
            ('SP',           'SPANDEX'),   ('EA',           'SPANDEX'),
            ('ELASTANE',     'SPANDEX'),   ('LYCRA',        'SPANDEX'),
            ('WL',           'WOOL'),      ('WO',           'WOOL'),
            ('CT',           'COTTON'),    ('CTN',          'COTTON'),
            ('CO',           'COTTON'),
            ('NY',           'NYLON'),     ('PA',           'NYLON'),
            ('ACRY',         'ACRYLIC'),   ('AC',           'ACRYLIC'),
            ('PAN',          'ACRYLIC'),
            ('LI',           'LINEN'),     ('FLAX',         'LINEN'),
            ('LX',           'LUREX'),     ('METALLIC',     'LUREX'),
        ]
        for alias, canonical in aliases:
            conn.execute(
                __import__('sqlalchemy').text(
                    "INSERT OR IGNORE INTO material_aliases (alias, canonical) VALUES (:a, :c)"
                ), {"a": alias, "c": canonical}
            )

        types = [
            'TWEED', 'JERSEY', 'DENIM', 'CHIFFON', 'SATIN', 'VELVET',
            'LACE', 'KNIT', 'WOVEN', 'FLEECE', 'BROCADE', 'CREPE',
            'ORGANZA', 'TAFFETA', 'GEORGETTE', 'POPLIN', 'CANVAS',
            'CORDUROY', 'MUSLIN', 'VOILE', 'LAWN', 'FLANNEL', 'MESH',
            'INTERLOCK', 'PIQUE', 'PONTE', 'SCUBA', 'TERRY', 'VELOUR',
        ]
        for t in types:
            conn.execute(
                __import__('sqlalchemy').text(
                    "INSERT OR IGNORE INTO fabric_types (name) VALUES (:n)"
                ), {"n": t}
            )

        defaults = [
            ('default_k',                    '20'),
            ('duplicate_threshold',          '0.97'),
            ('history_retention_days',       '365'),
            ('disk_space_warning_mb',        '500'),
            ('thumbnail_cache_max_mb',       '2048'),
            ('include_unverified_in_filters','true'),
            ('language',                     'en'),
            ('theme',                        'system'),
            ('debug_logging',                'false'),
        ]
        for key, value in defaults:
            conn.execute(
                __import__('sqlalchemy').text(
                    "INSERT OR IGNORE INTO app_settings (key, value) VALUES (:k, :v)"
                ), {"k": key, "v": value}
            )
        conn.commit()

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
    from app.services.importer import init_importer
    from app.api.import_ import set_worker
    from app.api.images import set_search_deps

    faiss = init_faiss(app_config.faiss_dir)
    emb = MockEmbedder()
    ocr = MockOcrService()

    importer = init_importer(
        embedder=emb,
        ocr=ocr,
        faiss_index=faiss,
        thumbnail_dir=app_config.thumbnail_dir,
    )
    set_worker(importer)
    set_search_deps(embedder=emb, faiss=faiss)

    from app import create_app
    return TestClient(create_app())

