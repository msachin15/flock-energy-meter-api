"""A log line that contains a secret field name must not keep the value."""

import logging

from app.logging_config import SensitiveLogFilter


def test_filter_redacts_secrets_and_keeps_the_record():
    """password= and signingSecret= values are replaced, and the log record is kept."""

    record = logging.LogRecord(
        name="flock_energy",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="password=synthetic-password signingSecret=synthetic-secret",
        args=(),
        exc_info=None,
    )
    assert SensitiveLogFilter().filter(record) is True
    rendered = record.getMessage()
    assert "synthetic-password" not in rendered
    assert "synthetic-secret" not in rendered
    assert "<redacted>" in rendered
