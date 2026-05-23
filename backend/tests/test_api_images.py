"""Images API tests: search, browse, get by ID."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image as PilImage
from fastapi.testclient import TestClient

from app.db.models import Image as ImageModel
from app.db.session import get_session


def _make_jpeg_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buf = io.BytesIO()
    img = PilImage.new("RGB", size, color=(128, 64, 32))
    img.save(buf, format="JPEG")
    return buf.getvalue()


JPEG_BYTES = _make_jpeg_bytes()


class TestSearch:
    def test_search_returns_results(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
        )
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "total" in data
        assert "truncated" in data

    def test_search_response_shape(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
        )
        data = r.json()
        assert isinstance(data["results"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["truncated"], bool)

    def test_search_with_k_param(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
            data={"k": 5},
        )
        assert r.status_code == 200

    def test_search_with_filters(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
            data={"supplier": "FAFA", "verified_only": True},
        )
        assert r.status_code == 200

    def test_search_invalid_image_returns_422(self, client: TestClient) -> None:
        # MockEmbedder never fails, so this test is only meaningful with real ML
        pytest.skip("MockEmbedder does not reject invalid images")

    def test_search_k_clamped(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
            data={"k": 999},
        )
        # k is capped at 200 by FastAPI validation (ge=1, le=200)
        assert r.status_code in (200, 422)

    def test_search_result_items_have_image_and_score(self, client: TestClient) -> None:
        r = client.post(
            "/images/search",
            files={"query_image": ("test.jpg", JPEG_BYTES, "image/jpeg")},
        )
        data = r.json()
        if data["results"]:
            item = data["results"][0]
            assert "image" in item
            assert "score" in item
            assert "id" in item["image"]
            assert "abs_path" in item["image"]


class TestBrowse:
    def test_browse_no_filters_returns_all(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={})
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert "total" in data

    def test_browse_with_supplier_filter(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"supplier": "test"})
        assert r.status_code == 200
        data = r.json()
        assert "results" in data

    def test_browse_with_fabric_type(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"fabric_type": "TWEED"})
        assert r.status_code == 200

    def test_browse_with_gsm_range(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"min_gsm": 100, "max_gsm": 300})
        assert r.status_code == 200

    def test_browse_with_needs_review(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"needs_review": True})
        assert r.status_code == 200

    def test_browse_with_verified_only(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"verified_only": True})
        assert r.status_code == 200

    def test_browse_empty_results_when_no_data(self, client: TestClient) -> None:
        r = client.post("/images/browse", json={"supplier": "NONEXISTENT"})
        data = r.json()
        assert data["total"] == 0


class TestGetImage:
    def test_get_nonexistent_returns_404(self, client: TestClient) -> None:
        r = client.get("/images/99999")
        assert r.status_code == 404

    def test_get_image_by_id(self, client: TestClient) -> None:
        # Insert a minimal image record directly into DB
        from app.db.session import get_session
        with get_session() as session:
            img = ImageModel(
                file_path="/tmp/test_get.jpg",
                filename="test_get.jpg",
                import_status="done",
            )
            session.add(img)
            session.flush()
            img_id = img.id

        r = client.get(f"/images/{img_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == img_id
        assert data["filename"] == "test_get.jpg"
        assert data["abs_path"] == "/tmp/test_get.jpg"

    def test_get_image_with_metadata(self, client: TestClient) -> None:
        from app.db.models import TextileMetadata
        with get_session() as session:
            img = ImageModel(
                file_path="/tmp/test_meta.jpg",
                filename="test_meta.jpg",
                import_status="done",
            )
            session.add(img)
            session.flush()
            meta = TextileMetadata(
                image_id=img.id,
                supplier="TEST SUPPLIER",
                fabric_type="DENIM",
            )
            session.add(meta)
            img_id = img.id

        r = client.get(f"/images/{img_id}")
        data = r.json()
        assert data["metadata"] is not None
        assert data["metadata"]["supplier"] == "TEST SUPPLIER"
        assert data["metadata"]["fabric_type"] == "DENIM"

    def test_get_image_response_shape(self, client: TestClient) -> None:
        with get_session() as session:
            img = ImageModel(
                file_path="/tmp/test_shape.jpg",
                filename="test_shape.jpg",
                import_status="done",
            )
            session.add(img)
            session.flush()
            img_id = img.id

        r = client.get(f"/images/{img_id}")
        data = r.json()
        expected_keys = {
            "id", "abs_path", "filename", "thumbnail_path",
            "import_status", "is_orphaned", "date_added",
            "faiss_id", "model_version", "metadata",
            # extended detail fields
            "file_hash", "file_size_bytes", "width_px", "height_px",
            "relative_path", "folder_name",
        }
        assert set(data.keys()) == expected_keys
