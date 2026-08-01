"""Persian text and entity normalization used by search and validation."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

_CHAR_MAP = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ئ": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "أ": "ا",
        "إ": "ا",
        "ٱ": "ا",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)
_SPACE_RE = re.compile(r"[\s\u200c\u200d]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+98|0098|98|0)?9\d{9}(?!\d)")
_AMOUNT_RE = re.compile(
    r"(?P<number>\d[\d,\. ]*)\s*(?P<unit>میلیارد|میلیون|هزار)?\s*(?P<currency>تومان|ریال)?"
)


def normalize_persian(value: str | None, *, keep_punctuation: bool = True) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).translate(_CHAR_MAP)
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    if not keep_punctuation:
        value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return _SPACE_RE.sub(" ", value).strip()


def normalize_phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", normalize_persian(value))
    if digits.startswith("0098"):
        digits = "0" + digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits if re.fullmatch(r"09\d{9}", digits) else None


def find_phone(value: str | None) -> str | None:
    normalized = normalize_persian(value)
    match = _PHONE_RE.search(normalized)
    return normalize_phone(match.group(0)) if match else None


def parse_amount(value: str | None) -> tuple[Decimal | None, str | None]:
    normalized = normalize_persian(value)
    match = _AMOUNT_RE.search(normalized)
    if not match:
        return None, None
    number_text = match.group("number").replace(",", "").replace(" ", "")
    try:
        number = Decimal(number_text)
    except InvalidOperation:
        return None, None
    multiplier = {"هزار": 1_000, "میلیون": 1_000_000, "میلیارد": 1_000_000_000}.get(
        match.group("unit"), 1
    )
    currency = match.group("currency") or None
    return number * multiplier, currency


def parse_relative_due(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """Parse only unambiguous relative Persian dates; never invent a calendar date."""

    normalized = normalize_persian(value, keep_punctuation=False)
    if not normalized:
        return None
    now = now or datetime.now(UTC)
    if "پس فردا" in normalized:
        return now + timedelta(days=2)
    if "فردا" in normalized:
        return now + timedelta(days=1)
    if "هفته بعد" in normalized:
        return now + timedelta(days=7)
    return None
