import os
import re
import logging
from decimal import Decimal

import requests
from bs4 import BeautifulSoup


TGJU_URL = "https://www.tgju.org/profile"

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
    "coin": ("sekee", "سکه امامی"),
    "gold18": ("geram18", "طلا ۱۸ عیار"),
    "usd": ("price_dollar_rl", "دلار"),
    "eur": ("price_eur", "یورو"),
    "silver": ("silver_999", "نقره"),
}


def normalize_digits(value):
    table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )
    return str(value).translate(table)


def number_from_text(value):
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

    number = Decimal(value)

    if number <= 0:
        return None

    return number


def rial_to_toman(value):
    return value / Decimal("10")


def format_price(value):
    return f"{value:,.0f}"


def get_page(symbol):
    url = f"{TGJU_URL}/{symbol}/today"

    logger.info(
        "Fetching TGJU: %s",
        url
    )

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

    for tag in soup.find_all(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

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

            price = number_from_text(
                match.group(1)
            )

            if price:

                logger.info(
                    "Found %s price: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

    for element in soup.find_all(
        string=re.compile("نرخ")
    ):

        parent = element.parent

        if parent is None:
            continue

        container = parent.parent

        if container is None:
            container = parent

        nearby = container.get_text(
            " ",
            strip=True
        )

        nearby = normalize_digits(
            nearby
        )

        numbers = re.findall(
            r"\d[\d,]{3,}",
            nearby
        )

        for item in numbers:

            price = number_from_text(
                item
            )

            if price:

                logger.info(
                    "Found %s price using DOM: %s Rial",
                    symbol,
                    format_price(price)
                )

                return price

    raise RuntimeError(
        f"Could not find current price for {symbol}"
    )


def get_price(symbol):

    html = get_page(symbol)

    return extract_price(
        html,
        symbol
    )


def fetch_all_prices():

    prices = {}

    for key, data in MARKETS.items():

        symbol = data[0]
        name = data[1]

        rial = get_price(symbol)

        toman = rial_to_toman(
            rial
        )

        prices[key] = toman

        logger.info(
            "%s = %s تومان",
            name,
            format_price(toman)
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
            "Telegram API error: "
            + str(result)
        )

    logger.info(
        "TGJU Telegram message sent successfully."
    )


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
