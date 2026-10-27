"""Logging setup that refuses to emit credentials or signatures."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERN = re.compile(
    r"(?i)(password|signingsecret|signing_secret|session_token|x-signature|x-timestamp)"
    r"(\s*[:=]\s*)(\S+)"
)


class SensitiveLogFilter(logging.Filter):
    """Redact values that follow known secret field names."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the log record in place. Always returns True so the line is still emitted."""

        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def _redact(value: object) -> object:
    """Replace the value after a known secret field name. Non-strings are left alone."""

    if not isinstance(value, str):
        return value
    return _SECRET_PATTERN.sub(r"\1\2<redacted>", value)


def configure_logging() -> None:
    """Attach one handler to the flock_energy logger. A second call does nothing."""

    logger = logging.getLogger("flock_energy")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(SensitiveLogFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
