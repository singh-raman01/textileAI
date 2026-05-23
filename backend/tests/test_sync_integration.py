"""Sync integration tests: startup_sync and handle_batch with real files."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image as PilImage

from app.db.models import Image as ImageModel, WatchedFolder
from app.db.session import get_session
from app.services.sync import (
    startup_sync,
    handle_batch,
    compute_file_hash,
    _derive_folder_tag_names,
    derive_folder_tags,
    compute_md5,
)


def _make_image(directory: Path, name: str = "img.jpg") -> Path:
    p = directory / name
    img = PilImage.new("RGB", (32, 32), color=(64, 128, 255))
    img.save(p, format="JPEG")
    return p


def _register_folder(path: Path, name: str = "Test Folder") -> int:
    with get_session() as session:
        existing = session.query(WatchedFolder).filter(
            WatchedFolder.folder_path == str(path)
        ).first()
        if existing:
            return existing.id
        f = WatchedFolder(folder_path=str(path), display_name=name)
        session.add(f)
        session.flush()
        return f.id


class TestStartupSync:
    def test_sync_queues_new_files(self, db_ready: bool, tmp_path: Path) -> None:
        img = _make_image(tmp_path)
        _register_folder(tmp_path)
        result = startup_sync()
        assert result.new_queued >= 1

    def test_sync_on_empty_db_returns_no_errors(self, db_ready: bool) -> None:
        result = startup_sync()
        assert isinstance(result.checked, int)
        assert result.errors == []

    def test_sync_does_not_queue_duplicates(self, db_ready: bool, tmp_path: Path) -> None:
        img = _make_image(tmp_path)
        _register_folder(tmp_path)
        r1 = startup_sync()
        r2 = startup_sync()
        # Second run should not queue the same file again
        assert r2.new_queued == 0

    def test_sync_orphans_missing_file(self, db_ready: bool, tmp_path: Path) -> None:
        _register_folder(tmp_path)
        ghost_path = str(tmp_path / "ghost.jpg")
        with get_session() as session:
            session.add(ImageModel(
                file_path=ghost_path,
                filename="ghost.jpg",
                import_status="done",
                is_orphaned=False,
            ))
        result = startup_sync()
        assert result.orphaned >= 1


class TestHandleBatch:
    def test_add_queues_file(self, db_ready: bool, tmp_path: Path) -> None:
        img = _make_image(tmp_path)
        _register_folder(tmp_path)
        result = handle_batch(added=[str(img)], removed=[])
        assert result.queued >= 1

    def test_add_skips_unsupported_extension(self, db_ready: bool, tmp_path: Path) -> None:
        txt = tmp_path / "notes.txt"
        txt.write_text("hello")
        result = handle_batch(added=[str(txt)], removed=[])
        assert result.queued == 0

    def test_add_skips_known_files(self, db_ready: bool, tmp_path: Path) -> None:
        img = _make_image(tmp_path)
        _register_folder(tmp_path)
        handle_batch(added=[str(img)], removed=[])
        result = handle_batch(added=[str(img)], removed=[])
        assert result.queued == 0

    def test_remove_orphans_file(self, db_ready: bool, tmp_path: Path) -> None:
        path_str = str(tmp_path / "orphan_me.jpg")
        with get_session() as session:
            session.add(ImageModel(
                file_path=path_str,
                filename="orphan_me.jpg",
                import_status="done",
                is_orphaned=False,
                file_hash="abcd1234abcd1234abcd1234abcd1234",
            ))
        result = handle_batch(added=[], removed=[path_str])
        assert result.orphaned == 1

    def test_rename_detected_via_md5(self, db_ready: bool, tmp_path: Path) -> None:
        old_path = tmp_path / "old_name.jpg"
        new_path = tmp_path / "new_name.jpg"
        _make_image(tmp_path, "old_name.jpg")
        hash_val = compute_file_hash(old_path)
        with get_session() as session:
            session.add(ImageModel(
                file_path=str(old_path),
                filename="old_name.jpg",
                import_status="done",
                is_orphaned=False,
                file_hash=hash_val,
            ))
        # "Move" the file — old removed, new added
        old_path.rename(new_path)
        result = handle_batch(added=[str(new_path)], removed=[str(old_path)])
        assert result.renamed == 1
        assert result.orphaned == 0
        assert result.queued == 0

    def test_empty_batch_noop(self, db_ready: bool) -> None:
        result = handle_batch(added=[], removed=[])
        assert result.queued == 0
        assert result.orphaned == 0
        assert result.renamed == 0


class TestDeriveFolderTags:
    def test_single_level(self) -> None:
        tags = _derive_folder_tag_names(
            Path("/data/textiles/wool/item.jpg"),
            Path("/data/textiles"),
        )
        assert tags == ["wool"]

    def test_two_levels(self) -> None:
        tags = _derive_folder_tag_names(
            Path("/data/textiles/cotton/lightweight/item.jpg"),
            Path("/data/textiles"),
        )
        assert tags == ["cotton", "lightweight"]

    def test_three_levels(self) -> None:
        tags = _derive_folder_tag_names(
            Path("/data/textiles/nylon/supply-2024/woven/item.jpg"),
            Path("/data/textiles"),
        )
        assert tags == ["nylon", "supply-2024", "woven"]

    def test_file_in_root_no_tags(self) -> None:
        tags = _derive_folder_tag_names(
            Path("/data/textiles/item.jpg"),
            Path("/data/textiles"),
        )
        assert tags == []

    def test_unrelated_path(self) -> None:
        tags = _derive_folder_tag_names(
            Path("/outside/item.jpg"),
            Path("/data/textiles"),
        )
        assert tags == []


class TestComputeMd5:
    def test_same_file_same_hash(self, tmp_path: Path) -> None:
        a = _make_image(tmp_path, "a.jpg")
        assert compute_md5(a) == compute_md5(a)

    def test_different_files_different_hash(self, tmp_path: Path) -> None:
        a = _make_image(tmp_path, "a.jpg")
        b = tmp_path / "b.jpg"
        b.write_bytes(b"different content")
        ha = compute_md5(a)
        hb = compute_md5(b)
        assert ha is not None and hb is not None
        assert ha != hb

    def test_nonexistent_file_returns_none(self) -> None:
        assert compute_md5(Path("/nonexistent/file.jpg")) is None

    def test_hash_is_32_hex_chars(self, tmp_path: Path) -> None:
        img = _make_image(tmp_path)
        h = compute_md5(img)
        assert h is not None
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


class TestDeriveFolderTagsFunction:
    def test_simple(self) -> None:
        tags = derive_folder_tags("/Fabrics/Wool/shirt.jpg", "/Fabrics")
        assert tags == ["Wool"]

    def test_multi(self) -> None:
        tags = derive_folder_tags("/Fabrics/Winter/Wool/shirt.jpg", "/Fabrics")
        assert tags == ["Winter", "Wool"]

    def test_not_under_root(self) -> None:
        tags = derive_folder_tags("/Other/shirt.jpg", "/Fabrics")
        assert tags == []
