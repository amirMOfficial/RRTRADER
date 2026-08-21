import os
import re
import logging
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup


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
})


# =========================
# TGJU SYMBOLS
# =========================

TGJU_MARKETS = {
    "coin": {
        "symbol": "sekee",
        "name": "سکه امامی",
    },

    "gold18": {
        "symbol": "geram18",
        "name": "طلا ۱۸ عیار",
    },

    "usd": {
        "symbol": "price_dollar_rl",
        "name": "دلار",
    },

    "eur": {
        "symbol": "price_eur",
        "name": "یورو",
    },

    "silver": {
        "symbol": "silver_999",
        "name": "نقره",
    },
}


# =========================
# NUMBER HELPERS
# =========================

def normalize_digits(value):
    """Convert Persian/Arabic digits to English digits."""

    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )

    return str(value).translate(translation)


def clean_number(value):
    """Convert a TGJU number string to Decimal."""

    if value is None:
        raise ValueError("Empty price")

    value = normalize_digits(value)

    value = (
        value
        .replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
        .replace("\u200c", "")
        .replace("\xa0", "")
    )

    # Keep only digits and decimal point
    value = re.sub(r"[^\d.]", "", value)

    if not value:
        raise ValueError(
            f"Could not extract number from: {value!r}"
        )

    try:
        number = Decimal(value)

    except InvalidOperation:
        raise ValueError(
            f"Invalid price: {value}"
        )

    if number <= 0:
        raise ValueError(
            f"Invalid price: {number}"
        )

    return number


def rial_to_toman(value):
    """TGJU domestic prices are in Rial."""

    return Decimal(value) / Decimal("10")


def format_price(value):
    value = Decimal(str(value))

    return f"{value:,.0f}"


# =========================
# TGJU PRICE EXTRACTION
# =========================

def extract_current_price(html, symbol):
    """
    Extract the current price from TGJU HTML.

    The visible TGJU page contains:
        نرخ فعلی:: PRICE

    We first convert the HTML to plain text,
    then search around the 'نرخ فعلی' label.
    """

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Remove elements that can contain unrelated numbers
    for element in soup(
        ["script", "style", "noscript"]
    ):
        element.decompose()

    text = soup.get_text(
        " ",
        strip=True
    )

    text = normalize_digits(text)

    # Normalize whitespace
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    logger.info(
        "Searching current price for %s",
        symbol
    )

    # Main pattern
    patterns = [
        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,٬]*)",
        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,٬]*)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            raw_price = match.group(1)

            logger.info(
                "Found %s price: %s Rial",
                symbol,
                raw_price
            )

            return clean_number(
                raw_price
            )

    # Fallback:
    # Find "نرخ فعلی" and inspect nearby text.
    index = text.find("نرخ فعلی")

    if index != -1:

        nearby = text[
            index:index + 150
        ]

        logger.info(
            "TGJU fallback text for %s: %s",
            symbol,
            nearby
        )

        numbers = re.findall(
            r"\d[\d,٬]*",
            nearby
        )

        for number in numbers:

            try:
                price = clean_number(
                    number
                )

                if price > 0:

                    logger.info(
                        "Fallback price for %s: %s Rial",
                        symbol,
                        price
                    )

                    return price

            except ValueError:
                continue

    raise RuntimeError(
        f"Could not find current price "
        f"for TGJU symbol: {symbol}"
    )


# =========================
# FETCH TGJU
# =========================

def get_tgju_price(symbol):

    url = (
        f"{TGJU_BASE_URL}/"
        f"{symbol}/today"
    )

    logger.info(
        "Fetching TGJU: %s",
        url
    )

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return extract_current_price(
        response.text,
        symbol
    )


def fetch_all_prices():

    prices = {}

    for key, market in TGJU_MARKETS.items():

        symbol = market["symbol"]

        rial_price = get_tgju_price(
            symbol
        )

        toman_price = rial_to_toman(
            rial_price
        )

        prices[key] = toman_price

        logger.info(
            "%s = %s تومان",
            market["name"],
            format_price(toman_price)
        )

    return prices


# =========================
# MESSAGE
# =========================

def build_message(prices):

    return (
        "💱 <b>قیمت‌های اصلی بازار</b>\n"
        "\n"
        f"🪙 سکه امامی: "
        f"<b>{format_price(prices['coin'])} تومان</b>\n"
        "\n"
        f"🥇 طلا ۱۸ عیار: "
        f"<b>{format_price(prices['gold18'])} تومان</b>\n"
        "\n"
        f"🇺🇸 دلار: "
        f"<b>{format_price(prices['usd'])} تومان</b>\n"
        "\n"
        f"🇪🇺 یورو: "
        f"<b>{format_price(prices['eur'])} تومان</b>\n"
        "\n"
        f"🥈 نقره: "
        f"<b>{format_price(prices['silver'])} تومان</b>\n"
        "\n"
        "🕐 <b>بروزرسانی:</b> ۱۱:۳۰ به وقت تهران\n"
        "📌 <b>منبع:</b> TGJU"
    )


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
