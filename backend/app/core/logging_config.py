import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from pythonjsonlogger import jsonlogger


# ─────────────────────────────────────────────────────────────────────────────
# Logging Setup
# Outputs newline-delimited JSON to daily rotating files.
# Console output is human-readable (useful when running sidecar directly).
#
# Privacy rule: NEVER log textile metadata values (supplier names, item
# numbers, OCR text) — these are business-sensitive. Log filenames and
# component names only.
# ─────────────────────────────────────────────────────────────────────────────

LOG_RETENTION_DAYS = 30


class _UTCJsonFormatter(jsonlogger.JsonFormatter):
    """Adds ISO-8601 UTC timestamp and enforces field order."""

    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record['ts']        = datetime.now(timezone.utc).isoformat()
        log_record['level']     = record.levelname
        log_record['component'] = record.name
        # Remove fields we don't want in the JSON output
        log_record.pop('levelname', None)
        log_record.pop('name',      None)


def setup_logging(log_dir: Path, debug: bool = False) -> None:
    """
    Call once at startup. Configures the root logger with:
    - A timed rotating file handler (daily, 30-day retention)
    - A stream handler for human-readable console output
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # ── File handler: JSON, daily rotation ────────────────────────────────────
    log_file = log_dir / f'backend-{datetime.now().strftime("%Y-%m-%d")}.log'
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename   = str(log_file),
        when       = 'midnight',
        interval   = 1,
        backupCount= LOG_RETENTION_DAYS,
        encoding   = 'utf-8',
        utc        = True,
    )
    file_handler.setFormatter(_UTCJsonFormatter())
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)

    # ── Console handler: human-readable ───────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('[%(levelname)s] %(name)s › %(message)s')
    )
    console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info(
        'Logging initialised',
        extra={'log_dir': str(log_dir), 'debug': debug, 'retention_days': LOG_RETENTION_DAYS}
    )
