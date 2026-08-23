import os
import re
import json
import logging
from decimal import Decimal
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import jdatetime
import requests
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

TGJU_BASE_URL = "https://www.tgju.org/profile"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID1")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

CMC_BTC_URL = (
    "https://pro-api.coinmarketcap.com/v3/"
    "cryptocurrency/quotes/latest"
)

TIMEOUT = 30

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

CHANGE_THRESHOLD = Decimal("2")

STATE_DIR = Path("data")
STATE_FILE = STATE_DIR / "last_prices.json"


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
# DATE
# =========================================================

def get_tehran_now():
    return datetime.now(TEHRAN_TZ)


def get_persian_date():
    now = get_tehran_now()

    jalali = jdatetime.datetime.fromgregorian(
        datetime=now
    )

    return jalali.strftime("%Y/%m/%d")


# =========================================================
# STATE
# =========================================================

def load_state():
    if not STATE_FILE.exists():
        logger.info("No previous price state found.")
        return None

    try:
        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            return None

        prices = data.get("prices")

        if not isinstance(prices, dict):
            return None

        logger.info(
            "Previous sent prices loaded."
        )

        return data

    except Exception as error:
        logger.warning(
            "Could not load state: %s",
            error,
        )

        return None


def save_state(prices):
    STATE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = get_tehran_now()

    data = {
        "updated_at": now.isoformat(),
        "prices": {
            key: str(value)
            for key, value in prices.items()
        },
    }

    temp_file = STATE_FILE.with_suffix(".tmp")

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

        temp_file.replace(STATE_FILE)

        logger.info(
            "Price state saved."
        )

    except Exception:
        if temp_file.exists():
            temp_file.unlink()

        raise


# =========================================================
# PERCENT CHANGE
# =========================================================

def calculate_change(
    current,
    previous,
):
    if current is None or previous is None:
        return None

    try:
        current = Decimal(str(current))
        previous = Decimal(str(previous))
    except Exception:
        return None

    if previous == 0:
        return None

    return (
        (current - previous)
        / previous
        * Decimal("100")
    )


def format_change(change):
    if change is None:
        return "➖"

    if abs(change) < Decimal("0.005"):
        return "➖ 0.00%"

    if change > 0:
        return f"🔺 +{change:.2f}%"

    return f"🔻 {change:.2f}%"


# =========================================================
# CHECK SIGNIFICANT CHANGE
# =========================================================

def has_significant_change(
    prices,
    previous_state,
):
    if not previous_state:
        return False

    previous_prices = previous_state.get(
        "prices",
        {},
    )

    for market in MARKETS:

        key = market["key"]

        current = prices.get(key)
        previous = previous_prices.get(key)

        change = calculate_change(
            current,
            previous,
        )

        if change is None:
            continue

        logger.info(
            "%s change: %.4f%%",
            market["name"],
            change,
        )

        if abs(change) >= CHANGE_THRESHOLD:

            logger.info(
                "2%% threshold reached: %s",
                market["name"],
            )

            return True
def get_bitcoin_price():
    logger.info("Fetching Bitcoin price from CoinMarketCap...")

    if not COINMARKETCAP_API_KEY:
        raise RuntimeError(
            "COINMARKETCAP_API_KEY is missing"
        )

    headers = {
        "Accept": "application/json",
        "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY,
    }

    params = {
        "symbol": "BTC",
        "convert": "USD",
    }

    try:
        response = session.get(
            CMC_BTC_URL,
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )

        logger.info(
            "CoinMarketCap HTTP %s",
            response.status_code,
        )

        response.raise_for_status()

        data = response.json()

        market_data = data.get("data")

        logger.info(
            "CoinMarketCap data type: %s",
            type(market_data).__name__,
        )

        # -------------------------------------------------
        # CoinMarketCap may return:
        #
        # data = [
        #     {...}
        # ]
        #
        # OR:
        #
        # data = {
        #     "BTC": {...}
        # }
        # -------------------------------------------------

        if isinstance(market_data, list):

            if len(market_data) == 0:
                raise RuntimeError(
                    "CoinMarketCap returned empty Bitcoin data"
                )

            bitcoin_data = market_data[0]

        elif isinstance(market_data, dict):

            bitcoin_data = (
                market_data.get("BTC")
                or market_data.get("1")
            )

            if bitcoin_data is None:
                raise RuntimeError(
                    "BTC data not found in CoinMarketCap response"
                )

        else:

            raise RuntimeError(
                "Unexpected CoinMarketCap data format"
            )

        # -------------------------------------------------
        # Make absolutely sure bitcoin_data is a dict
        # -------------------------------------------------

        if not isinstance(bitcoin_data, dict):

            raise RuntimeError(
                "Invalid Bitcoin data structure"
            )

        quote = bitcoin_data.get("quote")

        if not isinstance(quote, dict):

            raise RuntimeError(
                "Bitcoin quote data is invalid"
            )

        usd = quote.get("USD")

        if not isinstance(usd, dict):

            raise RuntimeError(
                "Bitcoin USD quote is invalid"
            )

        raw_price = usd.get("price")

        if raw_price is None:

            raise RuntimeError(
                "Bitcoin price not found"
            )

        price = Decimal(
            str(raw_price)
        )

        if price <= 0:

            raise RuntimeError(
                "Invalid Bitcoin price"
            )

        logger.info(
            "Bitcoin = %s USD",
            format_price(price),
        )

        return price

    except Exception as error:

        logger.error(
            "CoinMarketCap Bitcoin fetch failed: %s",
            error,
        )

        raise RuntimeError(
            "Could not fetch Bitcoin price from CoinMarketCap"
        ) from error
        
        


# =========================================================
# TGJU FETCH
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

    raise RuntimeError(
        f"Could not download TGJU page for {symbol}"
    )


# =========================================================
# PRICE EXTRACTION
# =========================================================

def extract_price(html, symbol):

    logger.info(
        "Extracting price for %s",
        symbol,
    )

    raw = normalize_digits(html)

    raw = (
        raw
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    patterns = [
        r"نرخ\s*فعلی\s*[:：]+\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی\s*[:：]?\s*([0-9][0-9,]*)",
        r"نرخ\s*فعلی.{0,120}?([0-9][0-9,]{4,})",
    ]

    # -----------------------------------------------------
    # RAW HTML
    # -----------------------------------------------------

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
    # BEAUTIFULSOUP TEXT
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
                    "Found %s price in text: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -----------------------------------------------------
    # DOM
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
    # DATA ATTRIBUTES
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
    # JAVASCRIPT
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

    raise RuntimeError(
        f"Could not find current price for TGJU symbol: {symbol}"
    )


def get_price(symbol):

    html = fetch_symbol_page(
        symbol
    )

    return extract_price(
        html,
        symbol,
    )


# =========================================================
# ALL PRICES
# =========================================================
def get_bitcoin_price():
    logger.info(
        "Fetching Bitcoin price from CoinMarketCap..."
    )

    if not COINMARKETCAP_API_KEY:
        raise RuntimeError(
            "COINMARKETCAP_API_KEY is missing"
        )

    headers = {
        "Accept": "application/json",
        "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY,
    }

    params = {
        "id": "1",
        "convert": "USD",
    }

    try:
        response = session.get(
            CMC_BTC_URL,
            headers=headers,
            params=params,
            timeout=TIMEOUT,
        )

        logger.info(
            "CoinMarketCap HTTP %s",
            response.status_code,
        )

        response.raise_for_status()

        data = response.json()
        market_data = data.get("data")

        if isinstance(market_data, list):

            if not market_data:
                raise RuntimeError(
                    "CoinMarketCap returned empty data"
                )

            bitcoin_data = market_data[0]

        elif isinstance(market_data, dict):

            bitcoin_data = (
                market_data.get("1")
                or market_data.get("BTC")
            )

            if not bitcoin_data:
                raise RuntimeError(
                    "Bitcoin data not found"
                )

        else:
            raise RuntimeError(
                "Invalid CoinMarketCap data format"
            )

        price = Decimal(
            str(
                bitcoin_data["quote"]["USD"]["price"]
            )
        )

        if price <= 0:
            raise RuntimeError(
                "Invalid Bitcoin price"
            )

        logger.info(
            "Bitcoin = %s USD",
            format_price(price),
        )

        return price

    except Exception as error:

        logger.error(
            "CoinMarketCap Bitcoin fetch failed: %s",
            error,
        )

        raise RuntimeError(
            "Could not fetch Bitcoin price from CoinMarketCap"
        ) from error

    
        
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
    prices["bitcoin"] = 
    get_bitcoin_price()
        
        logger.info(
            "بیت‌کوین = %s USD",
            format_price(prices["bitcoin"]),
        )
    return prices


# =========================================================
# MESSAGE
# =========================================================

def build_message(
    prices,
    previous_state,
):

    previous_prices = {}

    if previous_state:
        previous_prices = previous_state.get(
            "prices",
            {},
        )

    changes = {}

    for key in prices:

        changes[key] = calculate_change(
            prices[key],
            previous_prices.get(key),
        )

    persian_date = get_persian_date()

    return (
        "💱 <b> نرخ رسمی بازار ارز</b>"
        f"📅 <b></b> {persian_date}\n"
        "\n"
        "<b>——————————</b>"
        f"🪙 سکه امامی: "
        f"<b>{format_price(prices['coin'])} تومان</b> "
        f"{format_change(changes['coin'])}\n"
        "\n"
        f"🥇 طلا ۱۸ عیار: "
        f"<b>{format_price(prices['gold18'])} تومان</b> "
        f"{format_change(changes['gold18'])}\n"
        "\n"
        f"₿ بیت‌کوین: "
        f"<b>{format_price(prices['bitcoin'])} دلار</b> "
        f"{format_change(changes['bitcoin'])}\n"
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
        "<b>——————————</b>"
        "\n"
        '🔗 <b>خرید و فروش آنلاین:</b> '
        '<a href="https://bitpin.ir/signup/?ref=oDdSXxtY">bitpin</a>\n'
        
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
# DAILY REPORT CHECK
# =========================================================

def is_daily_report_time():

    now = get_tehran_now()

    return (
        now.hour == 11
        and now.minute in (30, 31)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    logger.info(
        "Starting TGJU market job..."
    )

    now = get_tehran_now()

    logger.info(
        "Tehran time: %s",
        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )

    previous_state = load_state()

    prices = fetch_all_prices()

    daily_report = is_daily_report_time()

    significant_change = has_significant_change(
        prices,
        previous_state,
    )

    logger.info(
        "Daily report = %s",
        daily_report,
    )

    logger.info(
        "Significant change = %s",
        significant_change,
    )

    # -----------------------------------------------------
    # اولین اجرا
    # -----------------------------------------------------

    if previous_state is None:

        if not daily_report:

            logger.info(
                "First run and not daily report time."
            )

            logger.info(
                "Saving initial baseline."
            )

            save_state(prices)

            return

    # -----------------------------------------------------
    # تصمیم ارسال
    # -----------------------------------------------------

    should_send = (
        daily_report
        or significant_change
    )

    if not should_send:

        logger.info(
            "No significant change. "
            "No Telegram message will be sent."
        )

        return

    # -----------------------------------------------------
    # ساخت پیام
    # -----------------------------------------------------

    message = build_message(
        prices,
        previous_state,
    )

    # -----------------------------------------------------
    # ارسال
    # -----------------------------------------------------

    send_telegram(
        message
    )

    # -----------------------------------------------------
    # فقط بعد از ارسال موفق ذخیره شود
    # -----------------------------------------------------

    save_state(
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
