import os
import re
import logging
from decimal import Decimal, InvalidOperation

import requests


# =========================
# CONFIG
# =========================

TGJU_BASE_URL = "https://www.tgju.org/profile"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

REQUEST_TIMEOUT = 20


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


# =========================
# HTTP
# =========================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
})


# =========================
# TGJU SYMBOLS
# =========================

TGJU_MARKETS = {
    "coin": "sekee",
    "gold18": "tgju_gold_irg18",
    "usd": "price_dollar_rl",
    "eur": "price_eur",
    "silver": "silver_999",
}


# =========================
# HELPERS
# =========================

def clean_number(value):
    """Convert TGJU number text to Decimal."""

    if value is None:
        raise ValueError("Empty price")

    value = str(value)

    # Remove commas and spaces
    value = value.replace(",", "")
    value = value.replace("٬", "")
    value = value.replace(" ", "")
    value = value.replace("\u200c", "")

    # Persian digits -> English digits
    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹",
        "0123456789"
    )

    value = value.translate(translation)

    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"Invalid price: {value}")

    if number <= 0:
        raise ValueError(f"Invalid/non-positive price: {number}")

    return number


def rial_to_toman(value):
    """TGJU reports domestic prices in Rial."""

    return Decimal(value) / Decimal("10")


def format_price(value):
    """Format price in تومان."""

    value = Decimal(str(value))

    return f"{value:,.0f}"


# =========================
# TGJU
# =========================

def get_tgju_price(symbol):
    """
    Get current price from TGJU profile page.

    TGJU page contains:
    نرخ فعلی:: PRICE
    """

    url = f"{TGJU_BASE_URL}/{symbol}"

    logger.info("Fetching TGJU: %s", url)

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    html = response.text

    # Normalize Persian/Arabic punctuation
    html = html.replace("٬", ",")
    html = html.replace("٫", ".")

    patterns = [
        r"نرخ\s*فعلی\s*::?\s*([0-9۰-۹,٬]+)",
        r"نرخ\s*فعلی\s*:\s*([0-9۰-۹,٬]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html,
            re.IGNORECASE
        )

        if match:
            price = clean_number(match.group(1))

            logger.info(
                "TGJU %s = %s Rial",
                symbol,
                price
            )

            return price

    raise RuntimeError(
        f"Could not find current price for TGJU symbol: {symbol}"
    )


def fetch_all_prices():

    prices = {}

    for name, symbol in TGJU_MARKETS.items():

        rial_price = get_tgju_price(symbol)

        toman_price = rial_to_toman(
            rial_price
        )

        prices[name] = toman_price

    logger.info(
        "TGJU prices loaded successfully: %s",
        prices
    )

    return prices


# =========================
# TELEGRAM MESSAGE
# =========================

def build_message(prices):

    message = f"""
💱 <b>قیمت‌های اصلی بازار</b>

🪙 سکه امامی: <b>{format_price(prices["coin"])} تومان</b>

🥇 طلا ۱۸ عیار: <b>{format_price(prices["gold18"])} تومان</b>

🇺🇸 دلار: <b>{format_price(prices["usd"])} تومان</b>

🇪🇺 یورو: <b>{format_price(prices["eur"])} تومان</b>

🥈 نقره: <b>{format_price(prices["silver"])} تومان</b>

🕐 <b>بروزرسانی:</b> ۱۱:۳۰ به وقت تهران
📌 <b>منبع:</b> TGJU
""".strip()

    return message


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is not configured"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = session.post(
        url,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {result}"
        )

    logger.info(
        "TGJU Telegram message sent successfully."
    )


# =========================
# MAIN
# =========================

def main():

    logger.info(
        "Starting TGJU market job..."
    )

    prices = fetch_all_prices()

    message = build_message(
        prices
    )

    logger.info(
        "Generated TGJU message:\n%s",
        message
    )

    send_telegram(message)

    logger.info(
        "TGJU job completed successfully."
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        logger.exception(
            "TGJU JOB FAILED: %s",
            exc
        )

        raise
