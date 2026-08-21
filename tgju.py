import os
import re
import logging
from decimal import Decimal

import requests
from bs4 import BeautifulSoup


TGJU_PROFILE_URL = "https://www.tgju.org/profile"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID1")

TIMEOUT = 30


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)


session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
})


MARKETS = {
    "coin": "sekee",
    "gold18": "geram18",
    "usd": "price_dollar_rl",
    "eur": "price_eur",
    "silver": "silver_999",
}


def normalize_digits(value):
    table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )

    return str(value).translate(table)


def clean_number(value):

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
        raise ValueError("Empty number")

    number = Decimal(value)

    if number <= 0:
        raise ValueError("Invalid price")

    return number


def rial_to_toman(value):
    return value / Decimal("10")


def format_price(value):
    return f"{Decimal(value):,.0f}"


def get_page(url):

    logger.info("Fetching TGJU: %s", url)

    response = session.get(
        url,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    return response.text


def extract_price(html, symbol):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for item in soup.find_all(
        ["script", "style", "noscript"]
    ):
        item.decompose()

    text = soup.get_text(
        " ",
        strip=True
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
        text
    )

    logger.info(
        "Searching current price for %s",
        symbol
    )

    patterns = [
        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی.{0,100}?([0-9][0-9,]{3,})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            try:

                price = clean_number(
                    match.group(1)
                )

                logger.info(
                    "Found %s price: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

            except Exception:
                pass

    for element in soup.find_all(
        string=re.compile("نرخ")
    ):

        nearby = element.parent

        if nearby is None:
            continue

        container = nearby.parent

        if container is None:
            container = nearby

        nearby_text = container.get_text(
            " ",
            strip=True
        )

        nearby_text = normalize_digits(
            nearby_text
        )

        numbers = re.findall(
            r"\d[\d,]{3,}",
            nearby_text
        )

        for number in numbers:

            try:

                price = clean_number(
                    number
                )

                logger.info(
                    "Found %s price using DOM: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

            except Exception:
                pass

    raise RuntimeError(
        f"Could not find current price for {symbol}"
    )


def get_profile_price(symbol):

    url = (
        f"{TGJU_PROFILE_URL}/"
        f"{symbol}/today"
    )

    html = get_page(url)

    return extract_price(
        html,
        symbol
    )


def get_currency_price(symbol):

    url = (
        f"{TGJU_PROFILE_URL}/"
        f"{symbol}/today"
    )

    html = get_page(url)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for item in soup.find_all(
        ["script", "style", "noscript"]
    ):
        item.decompose()

    text = soup.get_text(
        " ",
        strip=True
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
        text
    )

    logger.info(
        "Searching currency price for %s",
        symbol
    )

    # First try نرخ فعلی
    patterns = [
        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,]*)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            try:

                price = clean_number(
                    match.group(1)
                )

                logger.info(
                    "Found %s price: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

            except Exception:
                pass

    # Then search HTML
    html_text = normalize_digits(html)

    html_text = (
        html_text
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    patterns = [
        r"نرخ\s*فعلی.{0,300}?([0-9][0-9,]{3,})",
        r"price.{0,300}?([0-9][0-9,]{3,})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            html_text,
            flags=re.IGNORECASE
        )

        if match:

            try:

                price = clean_number(
                    match.group(1)
                )

                logger.info(
                    "Found %s price using HTML: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

            except Exception:
                pass

    raise RuntimeError(
        f"Could not find currency price for {symbol}"
    )


def fetch_all_prices():

    prices = {}

    # -------------------------
    # Coin
    # -------------------------

    value = get_profile_price(
        MARKETS["coin"]
    )

    prices["coin"] = rial_to_toman(
        value
    )

    logger.info(
        "سکه امامی = %s تومان",
        format_price(prices["coin"])
    )

    # -------------------------
    # Gold 18
    # -------------------------

    value = get_profile_price(
        MARKETS["gold18"]
    )

    prices["gold18"] = rial_to_toman(
        value
    )

    logger.info(
        "طلا ۱۸ عیار = %s تومان",
        format_price(prices["gold18"])
    )

    # -------------------------
    # Dollar
    # -------------------------

    value = get_currency_price(
        MARKETS["usd"]
    )

    prices["usd"] = rial_to_toman(
        value
    )

    logger.info(
        "دلار = %s تومان",
        format_price(prices["usd"])
    )

    # -------------------------
    # Euro
    # -------------------------

    value = get_currency_price(
        MARKETS["eur"]
    )

    prices["eur"] = rial_to_toman(
        value
    )

    logger.info(
        "یورو = %s تومان",
        format_price(prices["eur"])
    )

    # -------------------------
    # Silver
    # -------------------------

    value = get_profile_price(
        MARKETS["silver"]
    )

    prices["silver"] = rial_to_toman(
        value
    )

    logger.info(
        "نقره = %s تومان",
        format_price(prices["silver"])
    )

    return prices


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
        timeout=TIMEOUT
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            f"Telegram error: {result
