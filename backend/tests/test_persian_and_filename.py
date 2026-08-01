from datetime import UTC, datetime

import pytest

from app.services.filename_parser import parse_issabel_filename
from app.services.persian import (
    find_phone,
    normalize_persian,
    normalize_phone,
    parse_amount,
    parse_relative_due,
)


def test_persian_normalization_and_entities():
    assert normalize_persian("  شركت\u200cهاي ياس ۱۲۳  ") == "شرکت های یاس 123"
    assert normalize_phone("+۹۸ ۹۱۲ ۱۲۳ ۴۵۶۷") == "09121234567"
    assert find_phone("شماره تماس من ۰۹۱۲۱۲۳۴۵۶۷ است") == "09121234567"
    amount, currency = parse_amount("بودجه ۱۲.۵ میلیون تومان")
    assert float(amount) == 12_500_000
    assert currency == "تومان"
    now = datetime(2026, 8, 1, 8, tzinfo=UTC)
    assert parse_relative_due("پس فردا تماس بگیرید", now=now) == datetime(2026, 8, 3, 8, tzinfo=UTC)
    assert parse_relative_due("یک تاریخی هماهنگ می‌کنیم", now=now) is None


@pytest.mark.parametrize(
    ("name", "direction", "caller", "destination", "started"),
    [
        (
            "in-09121234567-02188776655-20260801-141530-172251.wav",
            "inbound",
            "09121234567",
            "02188776655",
            datetime(2026, 8, 1, 14, 15, 30, tzinfo=UTC),
        ),
        (
            "outbound_09121234567_200_2026-08-01_14-15-30_uid.mp3",
            "outbound",
            "09121234567",
            "200",
            datetime(2026, 8, 1, 14, 15, 30, tzinfo=UTC),
        ),
    ],
)
def test_filename_parser_common_patterns(name, direction, caller, destination, started):
    result = parse_issabel_filename(name)
    assert result.direction == direction
    assert result.caller_number == caller
    assert result.destination_number == destination
    assert result.call_started_at == started
    assert result.parser_name == "asterisk-monitor"


def test_filename_queue_custom_and_fallback():
    queued = parse_issabel_filename("queue-sales-agent-204-09121234567-20260801-141530-uid.wav")
    assert queued.queue == "sales"
    assert queued.agent_extension == "204"
    assert queued.extension == "204"
    custom = parse_issabel_filename(
        "09120000000_301_20260801_120000.wav",
        r"(?P<caller>\d+)_(?P<agent>\d+)_(?P<date>\d{8})_(?P<time>\d{6})",
    )
    assert custom.parser_name == "custom"
    assert custom.agent_extension == "301"
    fallback = parse_issabel_filename("unrecognized-recording-name.gsm")
    assert fallback.parser_name == "fallback"
    assert fallback.unique_call_id == "unrecognized-recording-name"
    with pytest.raises(ValueError, match="invalid ISSABEL_FILENAME_PATTERN"):
        parse_issabel_filename("anything.wav", "(")
