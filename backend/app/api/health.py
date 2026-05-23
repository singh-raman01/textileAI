import logging
import os
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel
from ..db.session import get_session, get_engine
from ..db.models import AppSetting, SchemaVersion, Image
from ..core.config import get_config
from sqlalchemy import func, text

logger   = logging.getLogger(__name__)
router   = APIRouter()
START_TS = datetime.now(timezone.utc)


# ── Response models ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status:    str
    version:   str
    db_path:   str
    uptime_s:  float


class DbStatusResponse(BaseModel):
    schema_version: int
    image_count:    int
    indexed_count:  int
    orphaned_count: int
    queued_count:   int
    failed_count:   int
    db_path:        str
    db_size_mb:     float


class SettingsResponse(BaseModel):
    default_k:                     str
    duplicate_threshold:           str
    history_retention_days:        str
    disk_space_warning_mb:         str
    thumbnail_cache_max_mb:        str
    include_unverified_in_filters:  str
    language:                      str
    theme:                         str
    debug_logging:                 str


class SettingsPatch(BaseModel):
    key:   str
    value: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get('/health', response_model=HealthResponse)
def health() -> HealthResponse:
    cfg     = get_config()
    uptime  = (datetime.now(timezone.utc) - START_TS).total_seconds()
    return HealthResponse(
        status   = 'ok',
        version  = cfg.app_version,
        db_path  = str(cfg.db_path),
        uptime_s = round(uptime, 1),
    )


@router.get('/db/status', response_model=DbStatusResponse)
def db_status() -> DbStatusResponse:
    cfg = get_config()
    with get_session() as session:
        schema_v = session.query(func.max(SchemaVersion.version)).scalar() or 0
        total    = session.query(func.count(Image.id)).scalar() or 0
        indexed  = session.query(func.count(Image.id)).filter(
                       Image.faiss_id.isnot(None),
                       Image.is_orphaned == False  # noqa: E712
                   ).scalar() or 0
        orphaned = session.query(func.count(Image.id)).filter(
                       Image.is_orphaned == True   # noqa: E712
                   ).scalar() or 0
        queued   = session.query(func.count(Image.id)).filter(
                       Image.import_status == "queued"
                   ).scalar() or 0
        failed   = session.query(func.count(Image.id)).filter(
                       Image.import_status == "failed"
                   ).scalar() or 0

    db_size = cfg.db_path.stat().st_size / (1024 * 1024) if cfg.db_path.exists() else 0.0

    return DbStatusResponse(
        schema_version = schema_v,
        image_count    = total,
        indexed_count  = indexed,
        orphaned_count = orphaned,
        queued_count   = queued,
        failed_count   = failed,
        db_path        = str(cfg.db_path),
        db_size_mb     = round(db_size, 2),
    )


@router.get('/settings', response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    defaults = _default_settings()
    with get_session() as session:
        rows = session.query(AppSetting).all()
        stored = {row.key: row.value for row in rows}
    merged = {**defaults, **stored}
    return SettingsResponse(**merged)


@router.patch('/settings')
def update_setting(body: SettingsPatch) -> dict:
    allowed_keys = set(_default_settings().keys())
    if body.key not in allowed_keys:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f'Unknown setting key: {body.key}')

    with get_session() as session:
        existing = session.get(AppSetting, body.key)
        if existing:
            existing.value = body.value
        else:
            session.add(AppSetting(key=body.key, value=body.value))
        session.commit()
    logger.info('Setting updated', extra={'key': body.key})
    return {'ok': True}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _default_settings() -> dict:
    return {
        'default_k':                    '20',
        'duplicate_threshold':          '0.97',
        'history_retention_days':       '365',
        'disk_space_warning_mb':        '500',
        'thumbnail_cache_max_mb':       '2048',
        'include_unverified_in_filters':'true',
        'language':                     'en',
        'theme':                        'system',
        'debug_logging':                'false',
    }
