"""Health / settings / DB status API tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestHealth:
    def test_health_returns_ok(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_returns_version(self, client: TestClient) -> None:
        r = client.get("/health")
        assert "version" in r.json()

    def test_health_uptime_increases(self, client: TestClient) -> None:
        import time
        r1 = client.get("/health")
        time.sleep(0.1)
        r2 = client.get("/health")
        assert r2.json()["uptime_s"] >= r1.json()["uptime_s"]


class TestDbStatus:
    def test_db_status_returns_schema_version(self, client: TestClient) -> None:
        r = client.get("/db/status")
        assert r.status_code == 200
        assert "schema_version" in r.json()

    def test_db_status_counts_are_non_negative(self, client: TestClient) -> None:
        r = client.get("/db/status")
        data = r.json()
        assert data["image_count"] >= 0
        assert data["indexed_count"] >= 0
        assert data["orphaned_count"] >= 0

    def test_db_status_returns_db_path(self, client: TestClient) -> None:
        r = client.get("/db/status")
        assert r.json()["db_path"].endswith("textile.db")


class TestSettings:
    def test_get_settings_returns_defaults(self, client: TestClient) -> None:
        r = client.get("/settings")
        assert r.status_code == 200
        data = r.json()
        assert data["default_k"] == "20"
        assert data["language"] == "en"
        assert data["theme"] == "system"

    def test_update_setting(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "language", "value": "zh-TW"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_updated_setting_persists(self, client: TestClient) -> None:
        client.patch("/settings", json={"key": "default_k", "value": "50"})
        r = client.get("/settings")
        assert r.json()["default_k"] == "50"

    def test_update_unknown_setting_returns_400(self, client: TestClient) -> None:
        r = client.patch("/settings", json={"key": "nonexistent", "value": "val"})
        assert r.status_code == 400

    def test_settings_include_defaults_when_unset(self, client: TestClient) -> None:
        r = client.get("/settings")
        data = r.json()
        assert data["duplicate_threshold"] == "0.97"
        assert data["history_retention_days"] == "365"
        assert data["debug_logging"] == "false"

    def test_update_and_revert(self, client: TestClient) -> None:
        client.patch("/settings", json={"key": "theme", "value": "dark"})
        r1 = client.get("/settings")
        assert r1.json()["theme"] == "dark"
        client.patch("/settings", json={"key": "theme", "value": "system"})
        r2 = client.get("/settings")
        assert r2.json()["theme"] == "system"
