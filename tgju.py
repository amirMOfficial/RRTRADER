import os
import re
import logging
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

TGJU_PROFILE_URL = "https://www.tgju.org/profile"
TGJU_CURRENCY_URL = "https://www.tgju.org/currency"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID1")

REQUEST_TIMEOUT = 30


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# HTTP SESSION
# =========================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
)


# =========================================================
# TGJU SYMBOLS
# =========================================================

MARKETS = {
    "coin": {
        "symbol": "sekee",
        "name": "سکه امامی",
    },
    "gold18": {
        "symbol": "geram18",
        "name": "طلا ۱۸ عیار",
    },
    "silver": {
        "symbol": "silver_999",
        "name": "نقره",
    },
}


# =========================================================
# NUMBER HELPERS
# =========================================================

def normalize_digits(value):
    """Convert Persian and Arabic digits to English digits."""

    if value is None:
        return ""

    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )

    return str(value).translate(translation)


def clean_number(value):
    """Convert a number string to Decimal."""

    if value is None:
        raise ValueError("Empty number")

    value = normalize_digits(value)

    value = (
        value
        .replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
        .replace("\u200c", "")
        .replace("\xa0", "")
    )

    value = re.sub(r"[^\d.]", "", value)

    if not value:
        raise ValueError(
            f"Could not extract number from: {value!r}"
        )

    try:
        number = Decimal(value)

    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid number: {value}"
        ) from exc

    if number <= 0:
        raise ValueError(
            f"Invalid/non-positive number: {number}"
        )

    return number


def rial_to_toman(value):
    """TGJU domestic prices are reported in Rial."""

    return Decimal(value) / Decimal("10")


def format_price(value):
    """Format price as an integer with thousands
