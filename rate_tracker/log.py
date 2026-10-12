"""Structured JSON-lines logging (stage 1 of: JSON -> Notion -> PostgreSQL/FileMaker)."""
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Anything passed via logger.info(..., extra={"ctx": {...}}) lands here
        if hasattr(record, "ctx"):
            entry["ctx"] = record.ctx
        return json.dumps(entry, default=str)


def get_logger(name: str = "rate_tracker") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:  # already configured
        return logger
    LOG_DIR.mkdir(exist_ok=True)
    handler = logging.FileHandler(LOG_DIR / "tracker.jsonl", encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger
