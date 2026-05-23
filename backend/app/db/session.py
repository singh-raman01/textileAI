"""
TextileSearch — Database Session Management

Rules (strict):
  - Every caller uses `with get_session() as session:` — transactions are
    explicit and bounded. No session is ever left open or leaked.
  - commit() is called automatically on clean exit.
  - rollback() is called automatically on any exception.
  - `db_session()` is the FastAPI Depends provider; route handlers never
    call get_session() directly.
"""
from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import SessionNotInitialisedError

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(database_url: str, pool_size: int = 1) -> None:
    """
    Initialise the database engine and session factory.
    Must be called once at startup before any session is opened.
    """
    global _engine, _SessionLocal

    _engine = create_engine(
        database_url,
        connect_args={
            "check_same_thread": False,
            "timeout":           30,
        },
        pool_size=pool_size,
        max_overflow=0,
        pool_pre_ping=True,
    )

    @event.listens_for(_engine, "connect")
    def _set_pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA cache_size=-65536")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()

    _SessionLocal = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    logger.info("Database initialised", extra={"url": database_url})


def get_engine() -> Engine:
    if _engine is None:
        raise SessionNotInitialisedError("get_engine() called before init_db()")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager that yields a fully managed Session.

    Usage:
        with get_session() as session:
            session.add(obj)
        # commit happens automatically; session is closed

    On any exception: transaction is rolled back before re-raising.
    """
    if _SessionLocal is None:
        raise SessionNotInitialisedError("get_session() called before init_db()")
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Generator[Session, None, None]:
    """
    FastAPI Depends provider.

        def route(session: Session = Depends(db_session)) -> ...:
    """
    with get_session() as session:
        yield session
