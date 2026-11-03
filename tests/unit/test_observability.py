"""M11.1: log masking."""

import json
import logging

from khataiq.observability import REDACTED, configure_logging, mask_processor, mask_text


def test_long_digit_runs_keep_only_the_last_four():
    assert mask_text("a/c 50100123456789 ok") == "a/c XXXX6789 ok"
    assert mask_text("card 4111111111111111") == "card XXXX1111"
    assert mask_text("upload 1234 of 2026") == "upload 1234 of 2026"  # short numbers untouched


def test_sensitive_keys_are_redacted_wherever_they_are():
    event = {"event": "x", "password": "hunter2", "extra": {"narration": "UPI/RAMESH",
                                                           "Authorization": "Bearer abc"}}
    masked = mask_processor(None, "info", event)
    assert masked["password"] == REDACTED
    assert masked["extra"] == {"narration": REDACTED, "Authorization": REDACTED}


def test_stdlib_logs_come_out_as_masked_json(capsys):
    configure_logging("INFO")
    logging.getLogger("test").warning("account 123456789012 failed", extra={"token": "secret"})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "account XXXX9012 failed"
    assert record["token"] == REDACTED and record["level"] == "warning"
