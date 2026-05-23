"""Duplicates API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.models import Duplicate, Image
from app.db.session import get_session


_next_dup = 0

def _seed_duplicate_pair() -> int:
    """Create a duplicate pair and return its id."""
    global _next_dup
    _next_dup += 1
    with get_session() as session:
        img_a = Image(
            file_path=f"/tmp/dup_a_{_next_dup}.jpg",
            filename=f"dup_a_{_next_dup}.jpg",
            import_status="done",
        )
        img_b = Image(
            file_path=f"/tmp/dup_b_{_next_dup}.jpg",
            filename=f"dup_b_{_next_dup}.jpg",
            import_status="done",
        )
        session.add(img_a)
        session.add(img_b)
        session.flush()
        dup = Duplicate(
            image_id_a=img_a.id,
            image_id_b=img_b.id,
            similarity=0.99,
            match_type="visual",
            resolved=False,
        )
        session.add(dup)
        session.flush()
        return dup.id


class TestListDuplicates:
    def test_list_returns_pending_only(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        r = client.get("/duplicates")
        assert r.status_code == 200
        data = r.json()
        ids = [d["id"] for d in data]
        assert pair_id in ids

    def test_list_excludes_resolved(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        client.post(f"/duplicates/{pair_id}/resolve")
        r = client.get("/duplicates")
        ids = [d["id"] for d in r.json()]
        assert pair_id not in ids

    def test_list_includes_resolved_when_flag_set(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        client.post(f"/duplicates/{pair_id}/resolve")
        r = client.get("/duplicates?include_resolved=true")
        ids = [d["id"] for d in r.json()]
        assert pair_id in ids

    def test_list_response_shape(self, client: TestClient) -> None:
        _seed_duplicate_pair()
        r = client.get("/duplicates")
        data = r.json()
        if data:
            item = data[0]
            assert set(item.keys()) == {"id", "image_a", "image_b", "similarity", "match_type", "resolved"}
            assert set(item["image_a"].keys()) == {"id", "filename", "file_path", "thumbnail_path", "file_size_bytes", "date_added", "folder_name"}
            assert set(item["image_b"].keys()) == {"id", "filename", "file_path", "thumbnail_path", "file_size_bytes", "date_added", "folder_name"}


class TestResolveDuplicate:
    def test_resolve_pair(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        r = client.post(f"/duplicates/{pair_id}/resolve")
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"

    def test_resolve_nonexistent_returns_404(self, client: TestClient) -> None:
        r = client.post("/duplicates/99999/resolve")
        assert r.status_code == 404

    def test_resolve_is_idempotent(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        r1 = client.post(f"/duplicates/{pair_id}/resolve")
        r2 = client.post(f"/duplicates/{pair_id}/resolve")
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_resolve_all(self, client: TestClient) -> None:
        _seed_duplicate_pair()
        _seed_duplicate_pair()
        r = client.post("/duplicates/resolve-all")
        assert r.status_code == 200
        assert r.json()["resolved"] >= 2


class TestCountDuplicates:
    def test_count_returns_int(self, client: TestClient) -> None:
        r = client.get("/duplicates/count")
        assert r.status_code == 200
        assert isinstance(r.json()["pending"], int)

    def test_count_increases_after_new_pair(self, client: TestClient) -> None:
        before = client.get("/duplicates/count").json()["pending"]
        _seed_duplicate_pair()
        after = client.get("/duplicates/count").json()["pending"]
        assert after == before + 1

    def test_count_decreases_after_resolve(self, client: TestClient) -> None:
        pair_id = _seed_duplicate_pair()
        before = client.get("/duplicates/count").json()["pending"]
        client.post(f"/duplicates/{pair_id}/resolve")
        after = client.get("/duplicates/count").json()["pending"]
        assert after == before - 1
