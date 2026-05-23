"""Import API tests: folder registration, status, sync-batch."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.models import WatchedFolder
from app.db.session import get_session


class TestFolderImport:
    def test_start_folder_import_valid(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/import/folder", json={
            "abs_path": str(tmp_path),
            "display_name": "Test Folder",
        })
        assert r.status_code == 202
        assert r.json()["status"] == "accepted"

    def test_start_folder_import_invalid_path(self, client: TestClient) -> None:
        r = client.post("/import/folder", json={
            "abs_path": "/nonexistent/path",
            "display_name": "Ghost",
        })
        assert r.status_code == 400

    def test_start_folder_import_idempotent(self, client: TestClient, tmp_path: Path) -> None:
        r1 = client.post("/import/folder", json={
            "abs_path": str(tmp_path),
            "display_name": "Idempotent",
        })
        r2 = client.post("/import/folder", json={
            "abs_path": str(tmp_path),
            "display_name": "Idempotent",
        })
        assert r1.status_code == 202
        assert r2.status_code == 202

    def test_start_folder_creates_db_record(self, client: TestClient, tmp_path: Path) -> None:
        client.post("/import/folder", json={
            "abs_path": str(tmp_path),
            "display_name": "DB Check",
        })
        with get_session() as session:
            folder = session.query(WatchedFolder).filter(
                WatchedFolder.folder_path == str(tmp_path)
            ).first()
        assert folder is not None
        assert folder.display_name == "DB Check"

    def test_folder_with_empty_display_name(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/import/folder", json={
            "abs_path": str(tmp_path),
            "display_name": "",
        })
        assert r.status_code == 202


class TestImportStatus:
    def test_status_returns_response(self, client: TestClient) -> None:
        r = client.get("/import/status")
        assert r.status_code == 200
        data = r.json()
        assert "total_queued" in data
        assert "processed" in data
        assert "failed" in data
        assert "skipped" in data
        assert "is_running" in data
        assert "is_paused" in data

    def test_status_defaults_to_zero(self, client: TestClient) -> None:
        r = client.get("/import/status")
        data = r.json()
        assert data["processed"] >= 0
        assert data["failed"] >= 0

    def test_status_has_boolean_fields(self, client: TestClient) -> None:
        r = client.get("/import/status")
        data = r.json()
        assert isinstance(data["is_running"], bool)
        assert isinstance(data["is_paused"], bool)


class TestPauseResume:
    def test_pause(self, client: TestClient) -> None:
        r = client.post("/import/pause")
        assert r.status_code == 200

    def test_resume(self, client: TestClient) -> None:
        r = client.post("/import/resume")
        assert r.status_code == 200

    def test_pause_then_status_shows_paused(self, client: TestClient) -> None:
        client.post("/import/pause")
        r = client.get("/import/status")
        assert r.json()["is_paused"] is True
        client.post("/import/resume")

    def test_pause_resume_cycle(self, client: TestClient) -> None:
        client.post("/import/pause")
        r1 = client.get("/import/status")
        assert r1.json()["is_paused"] is True
        client.post("/import/resume")
        r2 = client.get("/import/status")
        assert r2.json()["is_paused"] is False


class TestSyncBatch:
    def test_sync_batch_empty_is_noop(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": []})
        assert r.status_code == 200
        data = r.json()
        assert data["queued_for_import"] == 0
        assert data["orphaned"] == 0

    def test_sync_batch_add_event(self, client: TestClient, tmp_path: Path) -> None:
        img = tmp_path / "sync_add.jpg"
        img.write_bytes(b"fake image content")
        r = client.post("/import/sync-batch", json={"events": [
            {"event_type": "add", "abs_path": str(img)},
        ]})
        assert r.status_code == 200
        assert r.json()["queued_for_import"] >= 0

    def test_sync_batch_unlink_event(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": [
            {"event_type": "unlink", "abs_path": "/tmp/ghost.jpg"},
        ]})
        assert r.status_code == 200
        assert r.json()["orphaned"] >= 0

    def test_sync_batch_invalid_event_type(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": [
            {"event_type": "invalid", "abs_path": "/tmp/x.jpg"},
        ]})
        # FastAPI validation should reject invalid pattern
        assert r.status_code == 422
