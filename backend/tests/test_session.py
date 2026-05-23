"""Unit tests for DB session module — edge cases."""
from __future__ import annotations

import os
from unittest.mock import patch


class TestSessionEdgeCases:
    def test_get_session_rolls_back_on_error(self, db_ready: bool) -> None:
        """Verify that get_session rolls back when an exception occurs."""
        from app.db.session import get_session
        from app.db.models import AppSetting
        with get_session() as session:
            count_before = session.query(AppSetting).count()
        try:
            with get_session() as session:
                session.add(AppSetting(key="__rollback_test__", value="x"))
                1 / 0  # trigger exception
        except ZeroDivisionError:
            pass
        with get_session() as session:
            count_after = session.query(AppSetting).count()
        assert count_before == count_after

    def test_init_db_called_twice_is_idempotent(self, app_config) -> None:
        from app.db.session import init_db
        init_db(app_config.database_url, pool_size=5)
        init_db(app_config.database_url, pool_size=5)
