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

TIMEOUT = 30


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
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Connection": "keep-alive",
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

    value = re.sub(r"[^\d]", "", value)

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
# FETCH PAGE
# =========================================================

def fetch_url(url):
    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        logger.info(
            "HTTP %s | %d bytes | %s",
            response.status_code,
            len(response.content),
            response.url,
        )

        if response.status_code != 200:
            return None

        if not response.content:
            return None

        return response.text

    except requests.RequestException as error:
        logger.warning(
            "Request failed: %s",
            error,
        )

        return None


def fetch_symbol_page(symbol):
    """
    مهم:
    برای قیمت اصلی از صفحه /profile/SYMBOL استفاده می‌کنیم.
    بعضی endpoint های /today در GitHub Actions ممکن است 0 bytes برگردانند.
    """

    urls = [
        f"{TGJU_BASE_URL}/{symbol}",
        f"{TGJU_BASE_URL}/{symbol}/today",
    ]

    for url in urls:

        logger.info(
            "Trying TGJU URL: %s",
            url,
        )

        html = fetch_url(url)

        if html and len(html) > 1000:

            logger.info(
                "Valid TGJU page received: %d bytes",
                len(html),
            )

            return html

        logger.warning(
            "Empty or invalid response from: %s",
            url,
        )

    raise RuntimeError(
        f"Could not download TGJU page for {symbol}"
    )


# =========================================================
# EXTRACT PRICE
# =========================================================

def extract_price(html, symbol):

    logger.info(
        "Extracting price for %s",
        symbol,
    )

    # -----------------------------------------------------
    # RAW HTML
    # -----------------------------------------------------

    raw = normalize_digits(html)

    raw = (
        raw
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    # -----------------------------------------------------
    # روش 1
    # نرخ فعلی
    # -----------------------------------------------------

    patterns = [
        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی.{0,120}?([0-9][0-9,]{4,})",
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            raw,
            flags=re.DOTALL,
        )

        for match in matches:

            price = parse_number(match)

            if price:

                logger.info(
                    "Found %s price: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # BEAUTIFULSOUP
    # -----------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # -----------------------------------------------------
    # روش 2: متن صفحه
    # -----------------------------------------------------

    clean_soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in clean_soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    text = clean_soup.get_text(
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

        matches = re.findall(
            pattern,
            text,
            flags=re.DOTALL,
        )

        for match in matches:

            price = parse_number(match)

            if price:

                logger.info(
                    "Found %s price in visible text: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # روش 3: جدول / DOM
    # -----------------------------------------------------

    for element in soup.find_all(
        ["tr", "div", "li", "span"]
    ):

        element_text = element.get_text(
            " ",
            strip=True,
        )

        element_text = normalize_digits(
            element_text
        )

        if "نرخ فعلی" not in element_text:
            continue

        numbers = re.findall(
            r"\d[\d,]{4,}",
            element_text,
        )

        for item in numbers:

            price = parse_number(item)

            if price:

                logger.info(
                    "Found %s price in DOM: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # روش 4: data attributes
    # -----------------------------------------------------

    attributes = [
        "data-price",
        "data-value",
        "data-current",
        "data-last",
        "data-last-price",
    ]

    for element in soup.find_all():

        for attribute in attributes:

            value = element.get(attribute)

            if value is None:
                continue

            price = parse_number(value)

            if price:

                logger.info(
                    "Found %s price in %s: %s Rial",
                    symbol,
                    attribute,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # روش 5: JavaScript
    # -----------------------------------------------------

    javascript_patterns = [
        r'"price"\s*:\s*"([0-9,]+)"',
        r'"price"\s*:\s*([0-9]+)',
        r'"last"\s*:\s*"([0-9,]+)"',
        r'"last"\s*:\s*([0-9]+)',
        r'"current"\s*:\s*"([0-9,]+)"',
        r'"current"\s*:\s*([0-9]+)',
    ]

    for pattern in javascript_patterns:

        matches = re.findall(
            pattern,
            raw,
            flags=re.IGNORECASE,
        )

        for match in matches:

            price = parse_number(match)

            if price:

                logger.info(
                    "Found %s price in JavaScript: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # FAILED
    # -----------------------------------------------------

    logger.error(
        "Price extraction failed for %s",
        symbol,
    )

    raise RuntimeError(
        f"Could not find current price for TGJU symbol: {symbol}"
    )


# =========================================================
# GET PRICE
# =========================================================

def get_price(symbol):

    html = fetch_symbol_page(
        symbol
    )

    return extract_price(
        html,
        symbol,
    )


# =========================================================
# FETCH ALL PRICES
# =========================================================

def fetch_all_prices():

    prices = {}

    for market in MARKETS:

        key = market["key"]
        symbol = market["symbol"]
        name = market["name"]

        logger.info(
            "Processing %s (%s)",
            name,
            symbol,
        )

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
        "🕐 <b>زمان گزارش:</b> ۱۱:۳۰ به وقت تهران\n"
        "📌 <b>منبع:</b> TGJU"
    )


# =========================================================
# TELEGRAM
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
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram API error: "
            + str(result)
        )

    logger.info(
        "Telegram message sent successfully."
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
        "TGJU report generated."
    )

    send_telegram(
        message
    )

    logger.info(
        "TGJU JOB COMPLETED SUCCESSFULLY."
    )


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        logger.exception(
            "TGJU JOB FAILED: %s",
            error,
        )

        raise
