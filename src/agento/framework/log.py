from __future__ import annotations

import json
import logging
import os
from pathlib import Path

LOG_DIR = "/app/logs"

_JSON_EXTRA_FIELDS = ("job_id", "reference_id", "type", "attempt", "status", "duration_ms", "result_summary")


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = f"[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}] [{record.levelname}] {record.getMessage()}"
        extras = {k: getattr(record, k) for k in _JSON_EXTRA_FIELDS if getattr(record, k, None) is not None}
        if extras:
            pairs = " ".join(f"{k}={v}" for k, v in extras.items())
            msg = f"{msg} | {pairs}"
        if record.exc_info:
            msg = f"{msg}\n{self.formatException(record.exc_info)}"
        return msg


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for the consumer."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _JSON_EXTRA_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[1]:
            entry["error"] = str(record.exc_info[1])
            entry["error_class"] = record.exc_info[1].__class__.__name__
        return json.dumps(entry, ensure_ascii=False)


def get_logger(name: str, log_file: str | None = None, *, stderr: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    fmt = _Formatter()

    if stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)

    if log_file:
        path = Path(log_file)
        os.makedirs(path.parent, exist_ok=True)
        fh = logging.FileHandler(str(path))
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
