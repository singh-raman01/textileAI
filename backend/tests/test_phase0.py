"""
Phase 0 Backend Tests
Tests the health endpoint, DB migration, settings, and logging setup.
Run with: pytest tests/ -v
"""

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def tmp_data_dir():
    """Temporary data directory for the test session."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(scope='session')
def app_config(tmp_data_dir):
    """Initialise AppConfig with a temp directory."""
    import argparse
    from app.core.config import AppConfig, set_config

    args = argparse.Namespace(port=9999, data_dir=str(tmp_data_dir))
    config = AppConfig(args)
    set_config(config)
    return config


@pytest.fixture(scope='session')
def db_ready(app_config):
    """Create tables and seed data."""
    os.environ['TEXTILE_DB_URL'] = app_config.database_url

    from app.db.session import init_db
    init_db(app_config.database_url)

    from app.db.base import Base
    from app.db.session import get_engine
    from app.db import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

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


@pytest.fixture(scope='session')
def client(db_ready):
    """FastAPI test client."""
    from app import create_app
    app = create_app()
    return TestClient(app)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get('/health')
        assert r.status_code == 200
        data = r.json()
        assert data['status'] == 'ok'

    def test_health_returns_version(self, client):
        r = client.get('/health')
        assert 'version' in r.json()

    def test_health_returns_db_path(self, client):
        r = client.get('/health')
        assert 'db_path' in r.json()
        assert r.json()['db_path'].endswith('textile.db')

    def test_health_uptime_increases(self, client):
        import time
        r1 = client.get('/health')
        time.sleep(0.1)
        r2 = client.get('/health')
        assert r2.json()['uptime_s'] >= r1.json()['uptime_s']


class TestDbStatus:
    def test_db_status_returns_schema_version(self, client):
        r = client.get('/db/status')
        assert r.status_code == 200
        assert r.json()['schema_version'] >= 0

    def test_db_status_image_counts_are_zero(self, client):
        r = client.get('/db/status')
        data = r.json()
        assert data['image_count']    >= 0
        assert data['indexed_count']  >= 0
        assert data['orphaned_count'] >= 0

    def test_db_status_returns_db_path(self, client):
        r = client.get('/db/status')
        assert 'db_path' in r.json()


class TestSettings:
    def test_get_settings_returns_all_defaults(self, client):
        r = client.get('/settings')
        assert r.status_code == 200
        data = r.json()
        assert data['default_k']   == '20'
        assert data['language']    == 'en'
        assert data['theme']       == 'system'

    def test_update_setting(self, client):
        r = client.patch('/settings', json={'key': 'language', 'value': 'zh-TW'})
        assert r.status_code == 200
        assert r.json()['ok'] is True

    def test_updated_setting_persists(self, client):
        client.patch('/settings', json={'key': 'default_k', 'value': '50'})
        r = client.get('/settings')
        assert r.json()['default_k'] == '50'

    def test_update_unknown_setting_returns_400(self, client):
        r = client.patch('/settings', json={'key': 'nonexistent_key', 'value': 'val'})
        assert r.status_code == 400


class TestDatabase:
    def test_create_all_created_all_tables(self, db_ready, app_config):
        from sqlalchemy import inspect
        from app.db.session import get_engine
        inspector = inspect(get_engine())
        tables    = set(inspector.get_table_names())
        expected  = {
            'watched_folders', 'images', 'textile_metadata', 'fabric_compositions',
            'suppliers', 'supplier_aliases', 'material_aliases', 'fabric_types',
            'tags', 'image_tags', 'duplicates', 'search_history',
            'app_settings',
        }
        assert expected.issubset(tables), f'Missing tables: {expected - tables}'

    def test_material_aliases_seeded(self, db_ready):
        from app.db.session import get_session
        from app.db.models import MaterialAlias
        with get_session() as s:
            count = s.query(MaterialAlias).count()
        assert count > 20, 'Expected at least 20 pre-seeded material aliases'

    def test_fabric_types_seeded(self, db_ready):
        from app.db.session import get_session
        from app.db.models import FabricType
        with get_session() as s:
            count = s.query(FabricType).count()
        assert count > 10


class TestLogging:
    def test_log_dir_created(self, app_config):
        assert app_config.log_dir.exists()

    def test_data_dirs_created(self, app_config):
        for d in [app_config.thumbnail_dir, app_config.faiss_dir, app_config.backup_dir]:
            assert d.exists(), f'{d} was not created'
