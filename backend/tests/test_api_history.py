"""Search history API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestLogSearch:
    def test_log_search_returns_entry(self, client: TestClient) -> None:
        r = client.post("/history", json={
            "query_image_path": "/tmp/query.jpg",
            "k": 20,
            "result_ids": [1, 2, 3],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["query_image_path"] == "/tmp/query.jpg"
        assert data["k"] == 20
        assert data["result_count"] == 3
        assert data["top_result_ids"] == [1, 2, 3]

    def test_log_search_assigns_id(self, client: TestClient) -> None:
        r = client.post("/history", json={
            "query_image_path": "/tmp/q.jpg",
            "k": 5,
            "result_ids": [10],
        })
        assert r.json()["id"] > 0

    def test_log_search_with_empty_results(self, client: TestClient) -> None:
        r = client.post("/history", json={
            "query_image_path": "/tmp/empty.jpg",
            "k": 10,
            "result_ids": [],
        })
        assert r.status_code == 200
        assert r.json()["result_count"] == 0
        assert r.json()["top_result_ids"] == []

    def test_log_search_truncates_to_20(self, client: TestClient) -> None:
        ids = list(range(50))
        r = client.post("/history", json={
            "query_image_path": "/tmp/trunc.jpg",
            "k": 10,
            "result_ids": ids,
        })
        assert len(r.json()["top_result_ids"]) == 20


class TestGetHistory:
    def test_get_history_returns_list(self, client: TestClient) -> None:
        r = client.get("/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_history_newest_first(self, client: TestClient) -> None:
        client.post("/history", json={
            "query_image_path": "/tmp/first.jpg",
            "k": 1,
            "result_ids": [1],
        })
        import time
        time.sleep(0.05)
        client.post("/history", json={
            "query_image_path": "/tmp/second.jpg",
            "k": 1,
            "result_ids": [2],
        })
        r = client.get("/history")
        entries = r.json()
        assert len(entries) >= 2
        assert entries[0]["query_image_path"] == "/tmp/second.jpg"

    def test_get_history_empty(self, client: TestClient) -> None:
        client.delete("/history")
        r = client.get("/history")
        assert r.json() == []


class TestDeleteHistory:
    def test_delete_single_entry(self, client: TestClient) -> None:
        r = client.post("/history", json={
            "query_image_path": "/tmp/del.jpg",
            "k": 1,
            "result_ids": [1],
        })
        entry_id = r.json()["id"]
        r = client.delete(f"/history/{entry_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_delete_nonexistent_entry_returns_404(self, client: TestClient) -> None:
        r = client.delete("/history/99999")
        assert r.status_code == 404

    def test_clear_all_history(self, client: TestClient) -> None:
        client.post("/history", json={
            "query_image_path": "/tmp/a.jpg",
            "k": 1,
            "result_ids": [1],
        })
        client.post("/history", json={
            "query_image_path": "/tmp/b.jpg",
            "k": 1,
            "result_ids": [2],
        })
        r = client.delete("/history")
        assert r.status_code == 200
        assert r.json()["deleted"] >= 2
        r2 = client.get("/history")
        assert r2.json() == []
