"""Unit tests for AppConfig."""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest


class TestAppConfig:
    def test_custom_data_dir(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig
        d = str(tmp_path / "custom")
        args = argparse.Namespace(port=9999, data_dir=d)
        cfg = AppConfig(args)
        assert cfg.data_dir == Path(d)

    def test_repr(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig
        args = argparse.Namespace(port=8765, data_dir=str(tmp_path))
        cfg = AppConfig(args)
        r = repr(cfg)
        assert "port=8765" in r
        assert "AppConfig(" in r

    def test_database_url(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig
        args = argparse.Namespace(port=9999, data_dir=str(tmp_path))
        cfg = AppConfig(args)
        assert cfg.database_url.startswith("sqlite:///")
        assert cfg.database_url.endswith(".db")

    def test_faiss_dir(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig
        args = argparse.Namespace(port=9999, data_dir=str(tmp_path))
        cfg = AppConfig(args)
        assert "faiss" in str(cfg.faiss_dir)

    def test_thumbnail_dir(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig
        args = argparse.Namespace(port=9999, data_dir=str(tmp_path))
        cfg = AppConfig(args)
        assert "thumbnails" in str(cfg.thumbnail_dir)

    def test_set_and_get_config(self, tmp_path: Path) -> None:
        from app.core.config import AppConfig, get_config, set_config
        args = argparse.Namespace(port=7777, data_dir=str(tmp_path))
        cfg = AppConfig(args)
        set_config(cfg)
        assert get_config().port == 7777
