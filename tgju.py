import os
import re
import json
import logging
from decimal import Decimal
from datetime import datetime
from pathlib import Path

import jdatetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo


# =========================================================
# CONFIG
# =========================================================

TGJU_BASE_URL = "https://www.tgju.org/profile"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID1")

TIMEOUT = 30

# Timezone تهران
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# محل ذخیره آخرین قیمت‌ها
DATA_DIR = Path("data")
PRICE_FILE = DATA_DIR / "last_prices.json"


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
# PRICE HISTORY
# =========================================================

def load_previous_prices():
    """
    آخرین قیمت ذخیره‌شده را از فایل JSON می‌خواند.
    """

    if not PRICE_FILE.exists():
        logger.info(
            "No previous price file found. First run."
        )
        return None

    try:
        with PRICE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(data, dict):
            logger.warning(
                "Previous price file has invalid format."
            )
            return None

        prices = data.get("prices")

        if not isinstance(prices, dict):
            logger.warning(
                "Previous price file does not contain prices."
            )
            return None

        logger.info(
            "Previous prices loaded successfully."
        )

        return data

    except Exception as error:

        logger.warning(
            "Could not load previous prices: %s",
            error,
        )

        return None


def save_current_prices(prices):
    """
    قیمت‌های فعلی را در data/last_prices.json ذخیره می‌کند.

    این تابع فقط بعد از ارسال موفق تلگرام
    از main صدا زده می‌شود.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    tehran_now = datetime.now(
        TEHRAN_TZ
    )

    data = {
        "date": tehran_now.strftime(
            "%Y-%m-%d"
        ),
        "updated_at": tehran_now.isoformat(),
        "prices": {
            key: str(value)
            for key, value in prices.items()
        },
    }

    temp_file = PRICE_FILE.with_suffix(
        ".tmp"
    )

    try:

        with temp_file.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temp_file.replace(
            PRICE_FILE
        )

        logger.info(
            "Current prices saved to %s",
            PRICE_FILE,
        )

    except Exception:

        if temp_file.exists():
            temp_file.unlink()

        raise


# =========================================================
# PERCENTAGE CHANGE
# =========================================================

def calculate_percentage_change(
    current_price,
    previous_price,
):
    """
    محاسبه درصد تغییر:

    ((قیمت جدید - قیمت قبلی) / قیمت قبلی) * 100
    """

    if previous_price is None:
        return None

    try:

        current = Decimal(
            str(current_price)
        )

        previous = Decimal(
            str(previous_price)
        )

    except Exception:

        return None

    if previous == 0:
        return None

    return (
        (current - previous)
        / previous
    ) * Decimal("100")


def format_change(change):
    """
    فرمت درصد تغییر برای پیام تلگرام.
    """

    if change is None:
        return "➖ جدید"

    change = Decimal(
        str(change)
    )

    # تغییر بسیار کم / بدون تغییر
    if abs(change) < Decimal("0.005"):
        return "➖ 0.00%"

    if change > 0:
        return f"🔺 +{change:.2f}%"

    return f"🔻 {change:.2f}%"


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
    ابتدا صفحه اصلی نماد دریافت می‌شود.
    در صورت ناموفق بودن، /today نیز امتحان می‌شود.
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
    # جدول / DOM
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
    # data attributes
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
    # JavaScript
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

def build_message(
    prices,
    previous_data,
):

    # -----------------------------------------------------
    # زمان تهران
    # -----------------------------------------------------

    tehran_now = datetime.now(
        TEHRAN_TZ
    )

    # -----------------------------------------------------
    # تاریخ شمسی
    # -----------------------------------------------------

    jalali_now = jdatetime.datetime.fromgregorian(
        datetime=tehran_now
    )

    persian_date = jalali_now.strftime(
        "%Y/%m/%d"
    )

    # -----------------------------------------------------
    # قیمت‌های قبلی
    # -----------------------------------------------------

    previous_prices = {}

    if previous_data:

        previous_prices = previous_data.get(
            "prices",
            {}
        )

    # -----------------------------------------------------
    # درصد تغییرات
    # -----------------------------------------------------

    changes = {}

    for key, current_price in prices.items():

        previous_price = previous_prices.get(
            key
        )

        changes[key] = calculate_percentage_change(
            current_price,
            previous_price,
        )

    # -----------------------------------------------------
    # MESSAGE
    # -----------------------------------------------------

    return (
        "💱 <b>نرخ رسمی بازار ارز</b>"
        f" 📅 <b></b> {persian_date}\n"
        "\n"
        "------------"
        "\n"
        f"🪙 سکه امامی: "
        f"<b>{format_price(prices['coin'])} تومان</b> "
        f"{format_change(changes['coin'])}\n"
        "\n"
        f"🥇 طلا ۱۸ عیار: "
        f"<b>{format_price(prices['gold18'])} تومان</b> "
        f"{format_change(changes['gold18'])}\n"
        "\n"
        f"🇺🇸 دلار: "
        f"<b>{format_price(prices['usd'])} تومان</b> "
        f"{format_change(changes['usd'])}\n"
        "\n"
        f"🇪🇺 یورو: "
        f"<b>{format_price(prices['eur'])} تومان</b> "
        f"{format_change(changes['eur'])}\n"
        "\n"
        f"🥈 نقره: "
        f"<b>{format_price(prices['silver'])} تومان</b> "
        f"{format_change(changes['silver'])}\n"
        "\n"
        "------------"
        "\n"
        '🔗 <b>خرید و فروش آنلاین:</b> '
        '<a href="https://bitpin.ir/signup/?refcode=u9skcziwl8">bitpin</a>\n'
        
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

    # -----------------------------------------------------
    # 1. قیمت قبلی را بخوان
    # -----------------------------------------------------

    previous_data = load_previous_prices()

    # -----------------------------------------------------
    # 2. قیمت‌های جدید را دریافت کن
    # -----------------------------------------------------

    prices = fetch_all_prices()

    # -----------------------------------------------------
    # 3. پیام را با درصد تغییر بساز
    # -----------------------------------------------------

    message = build_message(
        prices,
        previous_data,
    )

    logger.info(
        "TGJU report generated."
    )

    # -----------------------------------------------------
    # 4. پیام را به تلگرام بفرست
    # -----------------------------------------------------

    send_telegram(
        message
    )

    # -----------------------------------------------------
    # 5. فقط بعد از ارسال موفق ذخیره کن
    # -----------------------------------------------------

    save_current_prices(
        prices
    )

    logger.info(
        "TGJU JOB COMPLETED SUCCESSFULLY."
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        logger.exception(
            "TGJU JOB FAILED: %s",
            error,
        )

        raise
