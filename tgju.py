import os
import re
import logging
from decimal import Decimal

import requests
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

TGJU_BASE_URL = "https://www.tgju.org/profile"

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

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
})


# =========================================================
# MARKETS
# =========================================================

MARKETS = [
    {
        "key": "coin",
        "symbol": "sekee",
        "name": "سکه امامی",
    },
    {
        "key": "gold18",
        "symbol": "geram18",
        "name": "طلا ۱۸ عیار",
    },
    {
        "key": "usd",
        "symbol": "price_dollar_rl",
        "name": "دلار",
    },
    {
        "key": "eur",
        "symbol": "price_eur",
        "name": "یورو",
    },
    {
        "key": "silver",
        "symbol": "silver_999",
        "name": "نقره",
    },
]


# =========================================================
# NUMBER HELPERS
# =========================================================

def normalize_digits(value):

    if value is None:
        return ""

    table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )

    return str(value).translate(table)


def parse_number(value):

    value = normalize_digits(value)

    value = (
        value
        .replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
        .replace("\u200c", "")
        .replace("\xa0", "")
    )

    value = re.sub(
        r"[^\d]",
        "",
        value,
    )

    if not value:
        return None

    try:
        number = Decimal(value)
    except Exception:
        return None

    if number <= 0:
        return None

    return number


def rial_to_toman(value):
    return value / Decimal("10")


def format_price(value):
    return f"{Decimal(value):,.0f}"


# =========================================================
# DOWNLOAD TGJU
# =========================================================

def fetch_page(symbol):

    url = (
        f"{TGJU_BASE_URL}/"
        f"{symbol}/today"
    )

    logger.info(
        "Fetching TGJU: %s",
        url,
    )

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    logger.info(
        "TGJU response: %s (%d bytes)",
        response.status_code,
        len(response.content),
    )

    return response.text


# =========================================================
# EXTRACT PRICE
# =========================================================

def extract_price(html, symbol):

    logger.info(
        "Searching current price for %s",
        symbol,
    )

    # -----------------------------------------------------
    # 1. Raw HTML
    # -----------------------------------------------------

    raw = normalize_digits(html)

    raw = (
        raw
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    # -----------------------------------------------------
    # Exact TGJU phrase
    #
    # نرخ فعلی:: 1,878,000
    # نرخ فعلی: 1,878,000
    # -----------------------------------------------------

    patterns = [

        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,]*)",

        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,]*)",

        r"نرخ\s*فعلی.{0,80}?([0-9][0-9,]{4,})",

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            raw,
            flags=re.DOTALL,
        )

        if match:

            price = parse_number(
                match.group(1)
            )

            if price:

                logger.info(
                    "Found %s price from raw HTML: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # 2. Visible page text
    # -----------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    text = soup.get_text(
        " ",
        strip=True,
    )

    text = normalize_digits(text)

    text = (
        text
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.DOTALL,
        )

        if match:

            price = parse_number(
                match.group(1)
            )

            if price:

                logger.info(
                    "Found %s price from visible text: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # 3. Look for table row containing نرخ فعلی
    # -----------------------------------------------------

    for row in soup.find_all(
        ["tr", "div", "li"]
    ):

        row_text = row.get_text(
            " ",
            strip=True,
        )

        row_text = normalize_digits(
            row_text
        )

        if "نرخ" not in row_text:
            continue

        if "فعلی" not in row_text:
            continue

        numbers = re.findall(
            r"\d[\d,]{4,}",
            row_text,
        )

        for number in numbers:

            price = parse_number(
                number
            )

            if price:

                logger.info(
                    "Found %s price from DOM: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # 4. Search known TGJU data attributes
    # -----------------------------------------------------

    attributes = [
        "data-price",
        "data-value",
        "data-current",
        "data-last",
        "data-last-price",
    ]

    for tag in soup.find_all():

        for attribute in attributes:

            value = tag.get(
                attribute
            )

            if value is None:
                continue

            price = parse_number(
                value
            )

            if price:

                logger.info(
                    "Found %s price from %s: %s Rial",
                    symbol,
                    attribute,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # 5. Search JavaScript/data structures
    # -----------------------------------------------------

    js_patterns = [

        r'"price"\s*:\s*"([0-9,]+)"',

        r'"price"\s*:\s*([0-9]+)',

        r'"last"\s*:\s*"([0-9,]+)"',

        r'"last"\s*:\s*([0-9]+)',

        r'"current"\s*:\s*"([0-9,]+)"',

        r'"current"\s*:\s*([0-9]+)',

    ]

    for pattern in js_patterns:

        match = re.search(
            pattern,
            raw,
            flags=re.IGNORECASE,
        )

        if match:

            price = parse_number(
                match.group(1)
            )

            if price:

                logger.info(
                    "Found %s price from data: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # FAILED
    # -----------------------------------------------------

    logger.error(
        "Could not extract price for %s",
        symbol,
    )

    raise RuntimeError(
        f"Could not find current price for TGJU symbol: {symbol}"
    )


# =========================================================
# GET ONE PRICE
# =========================================================

def get_price(symbol):

    html = fetch_page(
        symbol
    )

    return extract_price(
        html,
        symbol,
    )


# =========================================================
# FETCH ALL MARKETS
# =========================================================

def fetch_all_prices():

    prices = {}

    for market in MARKETS:

        key = market["key"]
        symbol = market["symbol"]
        name = market["name"]

        rial_price = get_price(
            symbol
        )

        toman_price = rial_to_toman(
            rial_price
        )

        prices[key] = toman_price

        logger.info(
            "%s = %s تومان",
            name,
            format_price(toman_price),
        )

    return prices


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

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


# =========================================================
# SEND TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID1 is missing"
        )

    url = (
        "https://api.telegram.org/"
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
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram API error: "
            + str(result)
        )

    logger.info(
        "TGJU Telegram message sent successfully."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info(
        "Starting TGJU market job..."
    )

    prices = fetch_all_prices()

    message = build_message(
        prices
    )

    logger.info(
        "TGJU report generated successfully."
    )

    send_telegram(
        message
    )

    logger.info(
        "TGJU job completed successfully."
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logger.exception(
            "TGJU JOB FAILED: %s",
            error
        )

        raise
