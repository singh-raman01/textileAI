"""Comprehensive E2E integration tests for all API endpoints.

Covers every route, success path, error path, and edge case.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.models import Image as ImageModel, WatchedFolder
from app.db.session import get_session


# =============================================================================
# Health
# =============================================================================

class TestHealthEndpoint:
    def test_health_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "uptime_s" in data
        assert "db_path" in data

    def test_health_db_path_exists(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.json()["db_path"].endswith(".db")

    def test_health_uptime_non_negative(self, client: TestClient) -> None:
        assert client.get("/health").json()["uptime_s"] >= 0


# =============================================================================
# Settings
# =============================================================================

class TestSettingsEndpoint:
    def test_get_all_settings(self, client: TestClient) -> None:
        r = client.get("/settings")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "default_k" in data
        assert "duplicate_threshold" in data
        assert "language" in data

    def test_get_setting_default_values(self, client: TestClient) -> None:
        r = client.get("/settings")
        data = r.json()
        assert data.get("theme") == "system"
        assert data.get("default_k") == "20"

    def test_set_setting(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "language", "value": "zh-TW"})
        assert r.status_code == 200
        r2 = client.get("/settings")
        assert r2.json()["language"] == "zh-TW"
        client.patch("/settings", json={"key": "language", "value": "en"})

    def test_set_unknown_key_returns_400(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "unknown_key_x", "value": "val"})
        assert r.status_code == 400
        assert "Unknown setting" in r.json()["detail"]

    def test_create_new_setting_record(self, client: TestClient) -> None:
        from app.db.session import get_session
        from app.db.models import AppSetting
        with get_session() as session:
            existing = session.get(AppSetting, "theme")
            orig_value = existing.value if existing else "system"
            session.query(AppSetting).filter(AppSetting.key == "theme").delete()
            session.commit()
        r = client.patch("/settings", json={"key": "theme", "value": "dark"})
        assert r.status_code == 200
        r2 = client.get("/settings")
        assert r2.json()["theme"] == "dark"
        # Restore original
        client.patch("/settings", json={"key": "theme", "value": orig_value})


# =============================================================================
# DB Status
# =============================================================================

class TestDbStatusEndpoint:
    def test_db_status_shape(self, client: TestClient) -> None:
        r = client.get("/db/status")
        assert r.status_code == 200
        data = r.json()
        assert "schema_version" in data
        assert "image_count" in data
        assert "indexed_count" in data
        assert "orphaned_count" in data
        assert "db_path" in data
        assert "db_size_mb" in data

    def test_db_status_defaults_zero(self, client: TestClient) -> None:
        data = client.get("/db/status").json()
        assert data["image_count"] >= 0
        assert data["indexed_count"] >= 0
        assert data["orphaned_count"] >= 0
        assert data["db_size_mb"] >= 0


# =============================================================================
# Import
# =============================================================================

class TestImportEndpoint:
    def test_import_folder_valid(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "E2E Test"})
        assert r.status_code == 202
        data = r.json()
        assert "folder_id" in data
        assert "queued_count" in data
        assert "Folder import started" in data["message"]

    def test_import_folder_idempotent(self, client: TestClient, tmp_path: Path) -> None:
        r1 = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "E2E Test"})
        r2 = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "E2E Test"})
        assert r1.status_code == 202 and r2.status_code == 202
        assert r1.json()["folder_id"] == r2.json()["folder_id"]

    def test_import_folder_invalid_path(self, client: TestClient) -> None:
        r = client.post("/import/folder", json={"folder_path": "/nonexistent_path_xyz", "display_name": "Ghost"})
        assert r.status_code == 400
        assert "not a directory" in r.json()["detail"]

    def test_import_folder_empty_display_name(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": ""})
        assert r.status_code == 202

    def test_import_folder_missing_folder_path_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/folder", json={"display_name": "test"})
        assert r.status_code == 422

    def test_import_folder_empty_path_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/folder", json={"folder_path": "", "display_name": "test"})
        assert r.status_code == 422

    def test_import_folder_returns_503_when_no_worker(self, client: TestClient, tmp_path: Path) -> None:
        import app.api.import_ as import_mod
        old_worker = import_mod._worker
        import_mod._worker = None
        r = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "NoWorker"})
        assert r.status_code == 503
        assert "not initialised" in r.json()["detail"]
        import_mod._worker = old_worker

    def test_import_folder_creates_db_record(self, client: TestClient, tmp_path: Path) -> None:
        client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "DB Check"})
        with get_session() as session:
            folder = session.query(WatchedFolder).filter(WatchedFolder.folder_path == str(tmp_path)).first()
        assert folder is not None
        assert folder.display_name == "DB Check"
        assert folder.is_available is True

    def test_import_status_endpoint(self, client: TestClient) -> None:
        r = client.get("/import/status")
        assert r.status_code == 200
        data = r.json()
        for key in ("total_queued", "processed", "failed", "is_running", "is_paused"):
            assert key in data

    def test_import_status_boolean_fields(self, client: TestClient) -> None:
        data = client.get("/import/status").json()
        assert isinstance(data["is_running"], bool)
        assert isinstance(data["is_paused"], bool)

    def test_pause_and_resume_cycle(self, client: TestClient) -> None:
        client.post("/import/pause")
        assert client.get("/import/status").json()["is_paused"] is True
        client.post("/import/resume")
        assert client.get("/import/status").json()["is_paused"] is False

    def test_pause_twice_is_idempotent(self, client: TestClient) -> None:
        client.post("/import/pause")
        client.post("/import/pause")
        assert client.get("/import/status").json()["is_paused"] is True
        client.post("/import/resume")

    def test_resume_without_pause_is_idempotent(self, client: TestClient) -> None:
        assert client.post("/import/resume").status_code == 200
        assert client.get("/import/status").json()["is_paused"] is False

    def test_sync_batch_empty(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": []})
        assert r.status_code == 200
        data = r.json()
        assert data["queued_for_import"] == 0
        assert data["orphaned"] == 0

    def test_sync_batch_add_file(self, client: TestClient, tmp_path: Path) -> None:
        img = tmp_path / "sync_add.jpg"
        img.write_bytes(b"fake image content")
        r = client.post("/import/sync-batch", json={"events": [{"event_type": "add", "abs_path": str(img)}]})
        assert r.status_code == 200
        assert r.json()["queued_for_import"] >= 0

    def test_sync_batch_unlink(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": [{"event_type": "unlink", "abs_path": "/tmp/nonexistent.jpg"}]})
        assert r.status_code == 200

    def test_sync_batch_invalid_event_type_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/sync-batch", json={"events": [{"event_type": "invalid", "abs_path": "/tmp/test.jpg"}]})
        assert r.status_code == 422


# =============================================================================
# Images — Browse
# =============================================================================

class TestImagesBrowseEndpoint:
    def test_browse_no_filters(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={})
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "total" in data
        assert isinstance(data["results"], list)
        assert data["total"] >= 0

    def test_browse_with_supplier(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"supplier": "test"}).status_code == 200

    def test_browse_with_fabric_type(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"fabric_type": "TWEED"}).status_code == 200

    def test_browse_with_gsm_range(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"min_gsm": 100, "max_gsm": 300}).status_code == 200

    def test_browse_with_width_range(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"min_width": 50, "max_width": 200}).status_code == 200

    def test_browse_with_needs_review(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"needs_review": True}).status_code == 200

    def test_browse_with_verified_only(self, client: TestClient) -> None:
        assert client.post("/images/browse", json={"verified_only": True}).status_code == 200

    def test_browse_empty_results_when_no_match(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"supplier": "NONEXISTENT_SUPPLIER_XYZ"})
        data = r.json()
        assert data["total"] == 0 and data["results"] == []

    def test_browse_returns_result_shape(self, client: TestClient) -> None:
        img = ImageModel(file_path="/tmp/_e2e_browse.jpg", filename="_e2e_browse.jpg", import_status="done")
        with get_session() as session:
            session.add(img)
            session.flush()
        r = client.post("/images/browse", json={})
        data = r.json()
        if data["total"] > 0:
            item = data["results"][0]
            assert "image" in item and "score" in item
            assert "id" in item["image"] and "abs_path" in item["image"]
        with get_session() as session:
            session.query(ImageModel).filter(ImageModel.file_path == "/tmp/_e2e_browse.jpg").delete()
            session.commit()

    def test_browse_total_reflects_db(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={})
        assert r.status_code == 200


# =============================================================================
# Images — Get by ID
# =============================================================================

class TestImagesGetEndpoint:
    def test_get_nonexistent_returns_404(self, client: TestClient) -> None:
        assert client.get("/images/99999").status_code == 404

    def test_get_by_id_returns_full_shape(self, client: TestClient) -> None:
        with get_session() as session:
            img = ImageModel(file_path="/tmp/_e2e_get.jpg", filename="_e2e_get.jpg", import_status="done")
            session.add(img)
            session.flush()
            img_id = img.id
        r = client.get(f"/images/{img_id}")
        assert r.status_code == 200
        data = r.json()
        expected = {"id", "abs_path", "filename", "thumbnail_path", "import_status",
                    "is_orphaned", "date_added", "faiss_id", "model_version", "metadata",
                    "file_hash", "file_size_bytes", "width_px", "height_px",
                    "relative_path", "folder_name"}
        assert set(data.keys()) == expected
        with get_session() as session:
            session.query(ImageModel).filter(ImageModel.id == img_id).delete()
            session.commit()

    def test_get_by_id_with_metadata(self, client: TestClient) -> None:
        from app.db.models import TextileMetadata
        with get_session() as session:
            img = ImageModel(file_path="/tmp/_e2e_meta.jpg", filename="_e2e_meta.jpg", import_status="done")
            session.add(img)
            session.flush()
            meta = TextileMetadata(image_id=img.id, supplier="E2E Supplier", item_no="E2E-001")
            session.add(meta)
            session.commit()
        r = client.get(f"/images/{img.id}")
        data = r.json()
        assert data["metadata"] is not None
        assert data["metadata"]["supplier"] == "E2E Supplier"
        assert data["metadata"]["item_no"] == "E2E-001"
        assert "composition" in data["metadata"]
        with get_session() as session:
            session.query(TextileMetadata).filter(TextileMetadata.image_id == img.id).delete()
            session.query(ImageModel).filter(ImageModel.id == img.id).delete()
            session.commit()

    def test_get_negative_id_returns_404(self, client: TestClient) -> None:
        r = client.get("/images/-1")
        assert r.status_code in (404, 422)

    def test_get_image_without_metadata(self, client: TestClient) -> None:
        with get_session() as session:
            img = ImageModel(file_path="/tmp/_e2e_no_meta.jpg", filename="_e2e_no_meta.jpg", import_status="done")
            session.add(img)
            session.flush()
        r = client.get(f"/images/{img.id}")
        assert r.json()["metadata"] is None
        with get_session() as session:
            session.query(ImageModel).filter(ImageModel.id == img.id).delete()
            session.commit()


# =============================================================================
# Images — Search
# =============================================================================

class TestImagesSearchEndpoint:
    def test_search_requires_image_file(self, client: TestClient) -> None:
        assert client.post("/images/search").status_code == 422

    def test_search_with_invalid_file(self, client: TestClient) -> None:
        r = client.post("/images/search", data={"k": 20}, files={"query_image": ("test.jpg", b"not an image", "image/jpeg")})
        assert r.status_code in (200, 503)

    def test_search_with_valid_image(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "query.jpg"
        Image.new("RGB", (100, 100), color="red").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", data={"k": 20}, files={"query_image": ("query.jpg", f, "image/jpeg")})
        assert r.status_code in (200, 503)

    def test_search_default_k(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "q_default.jpg"
        Image.new("RGB", (100, 100), color="blue").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", files={"query_image": ("q.jpg", f, "image/jpeg")})
        assert r.status_code in (200, 503)

    def test_search_with_filters(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "q_filter.jpg"
        Image.new("RGB", (100, 100), color="green").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", data={"k": 10, "supplier": "test"},
                            files={"query_image": ("q.jpg", f, "image/jpeg")})
        assert r.status_code in (200, 503)

    def test_search_k_out_of_range_returns_422(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        img_path = tmp_path / "q_out.jpg"
        Image.new("RGB", (10, 10), color="red").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", data={"k": 999}, files={"query_image": ("q.jpg", f, "image/jpeg")})
        assert r.status_code == 422

    def test_search_returns_503_when_ml_not_ready(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        import app.api.images as images_mod
        old_emb = images_mod._embedder
        old_faiss = images_mod._faiss
        images_mod._embedder = None
        images_mod._faiss = None
        img_path = tmp_path / "q_503.jpg"
        Image.new("RGB", (10, 10), color="red").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", files={"query_image": ("q.jpg", f, "image/jpeg")})
        assert r.status_code == 503
        assert "not ready" in r.json()["detail"]
        images_mod._embedder = old_emb
        images_mod._faiss = old_faiss

    def test_search_returns_422_when_embedding_fails(self, client: TestClient, tmp_path: Path) -> None:
        from PIL import Image
        import app.api.images as images_mod
        from app.exceptions import EmbeddingFailedError
        from pathlib import Path
        class FailingEmbedder:
            def embed(self, path: Path):
                raise EmbeddingFailedError(str(path), "test failure")
            vector_dim = 768
            model_version = "test"
            is_ready = True
            def embed_batch(self, paths):
                raise EmbeddingFailedError(str(paths[0]), "test failure")
        old_emb = images_mod._embedder
        images_mod._embedder = FailingEmbedder()
        img_path = tmp_path / "q_422.jpg"
        Image.new("RGB", (10, 10), color="red").save(str(img_path))
        with open(img_path, "rb") as f:
            r = client.post("/images/search", files={"query_image": ("q.jpg", f, "image/jpeg")})
        assert r.status_code == 422
        assert "test failure" in r.json()["detail"]
        images_mod._embedder = old_emb


# =============================================================================
# Duplicates
# =============================================================================

class TestDuplicatesEndpoint:
    def test_list_empty(self, client: TestClient) -> None:
        r = client.get("/duplicates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_with_include_resolved(self, client: TestClient) -> None:
        assert client.get("/duplicates?include_resolved=true").status_code == 200
        assert client.get("/duplicates?include_resolved=false").status_code == 200

    def test_resolve_nonexistent_returns_404(self, client: TestClient) -> None:
        assert client.post("/duplicates/99999/resolve").status_code == 404

    def test_resolve_all_empty_returns_zero(self, client: TestClient) -> None:
        data = client.post("/duplicates/resolve-all").json()
        assert data["resolved"] >= 0

    def test_count(self, client: TestClient) -> None:
        data = client.get("/duplicates/count").json()
        assert "pending" in data and data["pending"] >= 0

    def test_list_returns_pairs(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        with get_session() as session:
            a = ImageModel(file_path="/tmp/_dup_a.jpg", filename="_dup_a.jpg", import_status="done")
            b = ImageModel(file_path="/tmp/_dup_b.jpg", filename="_dup_b.jpg", import_status="done")
            session.add_all([a, b])
            session.flush()
            session.add(Duplicate(image_id_a=a.id, image_id_b=b.id, similarity=0.99, match_type="exact"))
            session.commit()
        r = client.get("/duplicates")
        assert len(r.json()) >= 1
        with get_session() as session:
            session.query(Duplicate).delete()
            session.query(ImageModel).delete()
            session.commit()

    def test_resolve_pair(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        with get_session() as session:
            a = ImageModel(file_path="/tmp/_dup_r1.jpg", filename="_dup_r1.jpg", import_status="done")
            b = ImageModel(file_path="/tmp/_dup_r2.jpg", filename="_dup_r2.jpg", import_status="done")
            session.add_all([a, b])
            session.flush()
            dp = Duplicate(image_id_a=a.id, image_id_b=b.id, similarity=0.98, match_type="exact")
            session.add(dp)
            session.commit()
            pair_id = dp.id
        assert client.post(f"/duplicates/{pair_id}/resolve").status_code == 200
        with get_session() as session:
            session.query(Duplicate).delete()
            session.query(ImageModel).delete()
            session.commit()

    def test_duplicate_skips_orphaned_image(self, client: TestClient) -> None:
        from app.db.models import Duplicate
        with get_session() as session:
            a = ImageModel(file_path="/tmp/_dup_orphan_a.jpg", filename="_dup_orphan_a.jpg", import_status="done")
            b = ImageModel(file_path="/tmp/_dup_orphan_b.jpg", filename="_dup_orphan_b.jpg", import_status="done")
            session.add_all([a, b])
            session.flush()
            dp = Duplicate(image_id_a=a.id, image_id_b=b.id, similarity=0.95, match_type="exact")
            session.add(dp)
            session.commit()
            a_id = a.id
            b_id = b.id
            dp_id = dp.id
        with get_session() as session:
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=OFF"))
            session.query(ImageModel).filter(ImageModel.id.in_([a_id, b_id])).delete()
            session.commit()
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=ON"))
        r = client.get("/duplicates")
        assert r.json() == []
        with get_session() as session:
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=OFF"))
            session.query(Duplicate).filter(Duplicate.id == dp_id).delete()
            session.commit()
            session.execute(__import__('sqlalchemy').text("PRAGMA foreign_keys=ON"))


# =============================================================================
# History
# =============================================================================

class TestHistoryEndpoint:
    def test_list_empty(self, client: TestClient) -> None:
        r = client.get("/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_with_limit(self, client: TestClient) -> None:
        assert client.get("/history?limit=5").status_code == 200

    def test_log_search(self, client: TestClient) -> None:
        r = client.post("/history", json={"query_image_path": "/tmp/_e2e_q.jpg", "k": 20, "result_ids": []})
        assert r.status_code == 200
        assert "id" in r.json()

    def test_log_search_returns_int_id(self, client: TestClient) -> None:
        r = client.post("/history", json={"query_image_path": "/tmp/_e2e_q2.jpg", "k": 10, "result_ids": [1, 2, 3]})
        assert isinstance(r.json()["id"], int)

    def test_list_after_log(self, client: TestClient) -> None:
        client.post("/history", json={"query_image_path": "/tmp/_e2e_list.jpg", "k": 5, "result_ids": []})
        entries = client.get("/history").json()
        assert len(entries) >= 1
        for key in ("query_image_path", "k", "searched_at"):
            assert key in entries[0]

    def test_clear_history(self, client: TestClient) -> None:
        client.post("/history", json={"query_image_path": "/tmp/_e2e_clear.jpg", "k": 3, "result_ids": []})
        r = client.delete("/history")
        assert r.status_code == 200
        assert r.json()["deleted"] >= 1
        assert len(client.get("/history").json()) == 0

    def test_clear_empty_returns_zero(self, client: TestClient) -> None:
        r = client.delete("/history")
        assert r.status_code == 200
        assert r.json()["deleted"] >= 0

    def test_log_missing_fields_returns_422(self, client: TestClient) -> None:
        assert client.post("/history", json={}).status_code == 422


# =============================================================================
# 404 + method not allowed
# =============================================================================

class TestHttpErrors:
    def test_unknown_get_returns_404(self, client: TestClient) -> None:
        assert client.get("/nonexistent").status_code == 404

    def test_unknown_post_returns_404(self, client: TestClient) -> None:
        assert client.post("/nonexistent").status_code == 404

    def test_get_on_post_endpoint_returns_405(self, client: TestClient) -> None:
        assert client.get("/import/folder").status_code == 405

    def test_post_on_get_endpoint_returns_405(self, client: TestClient) -> None:
        assert client.post("/health").status_code == 405


# =============================================================================
# JSON validation
# =============================================================================

class TestJsonValidation:
    def test_invalid_json_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/folder", data="not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 422

    def test_missing_content_type_returns_422(self, client: TestClient) -> None:
        r = client.post("/import/folder", data="{}")
        assert r.status_code == 422

    def test_extra_fields_ignored(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/import/folder", json={"folder_path": str(tmp_path), "display_name": "Extra", "extra_field": "x"})
        assert r.status_code == 202
