import os
import re
import json
import logging

from decimal import Decimal
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime
import requests
from bs4 import BeautifulSoup


# =========================================================
# CONFIG
# =========================================================

TGJU_BASE_URL = "https://www.tgju.org/profile"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID1")

COINMARKETCAP_API_KEY = os.getenv(
    "COINMARKETCAP_API_KEY"
)

TIMEOUT = 30

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

CHANGE_THRESHOLD = Decimal("1")

STATE_DIR = Path("data")
STATE_FILE = STATE_DIR / "last_prices.json"

CMC_URL = (
    "https://pro-api.coinmarketcap.com/"
    "v3/cryptocurrency/quotes/latest"
)


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
        "application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
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
# DATE
# =========================================================

def get_tehran_now():

    return datetime.now(
        TEHRAN_TZ
    )


def get_persian_date():

    jalali = jdatetime.datetime.fromgregorian(
        datetime=get_tehran_now()
    )

    return jalali.strftime(
        "%Y/%m/%d"
    )


# =========================================================
# STATE
# =========================================================

def load_state():

    if not STATE_FILE.exists():

        logger.info(
            "No previous price state found."
        )

        return None

    try:

        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(
            data,
            dict,
        ):
            return None

        prices = data.get(
            "prices"
        )

        if not isinstance(
            prices,
            dict,
        ):
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

    data = {
        "updated_at": get_tehran_now().isoformat(),
        "prices": {
            key: str(value)
            for key, value in prices.items()
        },
    }

    temp_file = STATE_FILE.with_suffix(
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
            STATE_FILE
        )

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

    if current is None:
        return None

    if previous is None:
        return None

    try:

        current = Decimal(
            str(current)
        )

        previous = Decimal(
            str(previous)
        )

    except Exception:

        return None

    if previous == 0:
        return None

    return (
        (
            current - previous
        )
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
# SIGNIFICANT CHANGE
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

    # -------------------------
    # TGJU markets
    # -------------------------

    for market in MARKETS:

        key = market["key"]

        current = prices.get(
            key
        )

        previous = previous_prices.get(
            key
        )

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
                "1%% threshold reached: %s",
                market["name"],
            )

            return True

    # -------------------------
    # Bitcoin
    # -------------------------

    current_btc = prices.get(
        "bitcoin"
    )

    previous_btc = previous_prices.get(
        "bitcoin"
    )

    btc_change = calculate_change(
        current_btc,
        previous_btc,
    )

    if btc_change is not None:

        logger.info(
            "بیت‌کوین change: %.4f%%",
            btc_change,
        )

        if abs(btc_change) >= CHANGE_THRESHOLD:

            logger.info(
                "1%% threshold reached: بیت‌کوین"
            )

            return True

    return False


# =========================================================
# TGJU HTTP
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
# TGJU PRICE EXTRACTION
# =========================================================

def extract_price(
    html,
    symbol,
):

    logger.info(
        "Extracting price for %s",
        symbol,
    )

    raw = normalize_digits(
        html
    )

    raw = (
        raw
        .replace("٬", ",")
        .replace("\u200c", " ")
        .replace("\xa0", " ")
    )

    patterns = [

        r"نرخ\s*فعلی\s*[:：]+\s*"
        r"([0-9][0-9,]*)",

        r"نرخ\s*فعلی\s*[:：]?\s*"
        r"([0-9][0-9,]*)",

        r"نرخ\s*فعلی.{0,120}?"
        r"([0-9][0-9,]{4,})",
    ]

    # -------------------------
    # RAW HTML
    # -------------------------

    for pattern in patterns:

        matches = re.findall(
            pattern,
            raw,
            flags=re.DOTALL,
        )

        for match in matches:

            price = parse_number(
                match
            )

            if price:

                logger.info(
                    "Found %s price: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -------------------------
    # BEAUTIFULSOUP
    # -------------------------

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    clean_soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in clean_soup.find_all(
        [
            "script",
            "style",
            "noscript",
        ]
    ):

        tag.decompose()

    text = clean_soup.get_text(
        " ",
        strip=True,
    )

    text = normalize_digits(
        text
    )

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

            price = parse_number(
                match
            )

            if price:

                logger.info(
                    "Found %s price in visible text: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -------------------------
    # DOM
    # -------------------------

    for element in soup.find_all(
        [
            "tr",
            "div",
            "li",
            "span",
        ]
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

            price = parse_number(
                item
            )

            if price:

                logger.info(
                    "Found %s price in DOM: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    # -------------------------
    # DATA ATTRIBUTES
    # -------------------------

    attributes = [
        "data-price",
        "data-value",
        "data-current",
        "data-last",
        "data-last-price",
    ]

    for element in soup.find_all():

        for attribute in attributes:

            value = element.get(
                attribute
            )

            if value is None:
                continue

            price = parse_number(
                value
            )

            if price:

                logger.info(
                    "Found %s price in %s: %s Rial",
                    symbol,
                    attribute,
                    format_price(price),
                )

                return price

    # -------------------------
    # JAVASCRIPT
    # -------------------------

    javascript_patterns = [

        r'"price"\s*:\s*"'
        r'([0-9,]+)"',

        r'"price"\s*:\s*'
        r'([0-9]+)',

        r'"last"\s*:\s*"'
        r'([0-9,]+)"',

        r'"last"\s*:\s*'
        r'([0-9]+)',

        r'"current"\s*:\s*"'
        r'([0-9,]+)"',

        r'"current"\s*:\s*'
        r'([0-9]+)',
    ]

    for pattern in javascript_patterns:

        matches = re.findall(
            pattern,
            raw,
            flags=re.IGNORECASE,
        )

        for match in matches:

            price = parse_number(
                match
            )

            if price:

                logger.info(
                    "Found %s price in JavaScript: %s Rial",
                    symbol,
                    format_price(price),
                )

                return price

    raise RuntimeError(
        "Could not find current price "
        f"for TGJU symbol: {symbol}"
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
# COINMARKETCAP
# =========================================================

def extract_cmc_error(data):

    if not isinstance(
        data,
        dict,
    ):
        return "Invalid JSON response"

    status = data.get(
        "status"
    )

    if not isinstance(
        status,
        dict,
    ):
        return None

    error_code = status.get(
        "error_code"
    )

    # مهم‌ترین اصلاح:
    # 0 و "0" هر دو موفق هستند.
    if error_code is None:
        return None

    if str(error_code) == "0":
        return None

    return (
        f"CoinMarketCap API error "
        f"{error_code}: "
        f"{status.get('error_message') or ''}"
    )


def extract_bitcoin_from_cmc(data):

    bitcoin_data = data.get(
        "data"
    )

    if bitcoin_data is None:
        raise RuntimeError(
            "CoinMarketCap returned no data"
        )

    # -------------------------
    # data = dict
    # -------------------------

    if isinstance(
        bitcoin_data,
        dict,
    ):

        bitcoin = bitcoin_data.get(
            "1"
        )

        if bitcoin is None:

            bitcoin = bitcoin_data.get(
                "BTC"
            )

        if bitcoin is None:

            values = list(
                bitcoin_data.values()
            )

            if len(values) == 1:
                bitcoin = values[0]

    # -------------------------
    # data = list
    # -------------------------

    elif isinstance(
        bitcoin_data,
        list,
    ):

        if not bitcoin_data:
            raise RuntimeError(
                "Bitcoin data list is empty"
            )

        bitcoin = bitcoin_data[0]

    else:

        raise RuntimeError(
            "Unknown CoinMarketCap data format"
        )

    if not isinstance(
        bitcoin,
        dict,
    ):

        raise RuntimeError(
            "Could not locate Bitcoin data"
        )

    quote = bitcoin.get(
        "quote"
    )

    # -------------------------
    # quote = dict
    # -------------------------

    if isinstance(
        quote,
        dict,
    ):

        usd_quote = quote.get(
            "USD"
        )

    # -------------------------
    # quote = list
    # -------------------------

    elif isinstance(
        quote,
        list,
    ):

        usd_quote = None

        for item in quote:

            if not isinstance(
                item,
                dict,
            ):
                continue

            if item.get(
                "symbol"
            ) == "USD":

                usd_quote = item
                break

        if (
            usd_quote is None
            and len(quote) == 1
        ):

            usd_quote = quote[0]

    else:

        raise RuntimeError(
            "Bitcoin quote format is invalid"
        )

    if not isinstance(
        usd_quote,
        dict,
    ):

        raise RuntimeError(
            "USD quote not found"
        )

    price = usd_quote.get(
        "price"
    )

    if price is None:

        raise RuntimeError(
            "Bitcoin USD price is missing"
        )

    price = Decimal(
        str(price)
    )

    if price <= 0:

        raise RuntimeError(
            "Invalid Bitcoin price"
        )

    return price


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
        "X-CMC_PRO_API_KEY":
            COINMARKETCAP_API_KEY,
    }

    params = {
        # Bitcoin official CMC ID
        "id": "1",
        "convert": "USD",
    }

    try:

        response = session.get(
            CMC_URL,
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

        logger.info(
            "CoinMarketCap response type: %s",
            type(data).__name__,
        )

        error = extract_cmc_error(
            data
        )

        if error:

            raise RuntimeError(
                error
            )

        price = extract_bitcoin_from_cmc(
            data
        )

        logger.info(
            "Bitcoin price = $%s",
            format_price(price),
        )

        return price

    except Exception as error:

        logger.exception(
            "CoinMarketCap Bitcoin fetch failed: %s",
            error,
        )

        raise RuntimeError(
            "Could not fetch Bitcoin price "
            "from CoinMarketCap"
        ) from error


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

    # Bitcoin
    prices["bitcoin"] = get_bitcoin_price()

    logger.info(
        "بیت‌کوین = %s USD",
        format_price(
            prices["bitcoin"]
        ),
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

        "💱 <b>نرخ رسمی بازار ارز</b>\n"

        f"📅 <b>{persian_date}</b>\n"

        "\n"

        "<b>——————————</b>\n"

        "\n"

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

        "<b>——————————</b>\n"

        "\n"

        '🔗 <b>خرید و فروش آنلاین:</b> '
        '<a href="https://bitpin.ir/signup/?ref=oDdSXxtY">'
        "bitpin"
        "</a>"
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
# DAILY REPORT
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

    # =====================================================
    # FIRST RUN
    # =====================================================

    if previous_state is None:

        logger.info(
            "First run detected."
        )

        save_state(
            prices
        )

        if not daily_report:

            logger.info(
                "First run and not daily report time."
            )

            return

    # =====================================================
    # SEND DECISION
    # =====================================================

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

    # =====================================================
    # BUILD MESSAGE
    # =====================================================

    message = build_message(
        prices,
        previous_state,
    )

    # =====================================================
    # SEND
    # =====================================================

    send_telegram(
        message
    )

    # =====================================================
    # SAVE ONLY AFTER SUCCESSFUL SEND
    # =====================================================

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
