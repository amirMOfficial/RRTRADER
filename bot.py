import os
import sys
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


# =========================
# CONFIG
# =========================

BITPIN_API = "https://api.bitpin.ir/v1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEZONE = ZoneInfo("Asia/Tehran")

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
    "User-Agent": "Bitpin-Telegram-Bot/1.0"
})


def api_get(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# =========================
# BITPIN
# =========================

def get_all_markets():
    """
    دریافت تمام بازارهای Bitpin
    """

    markets = []

    page = 1

    while True:

        data = api_get(
            f"{BITPIN_API}/mkt/markets/",
            params={"page": page}
        )

        results = data.get("results", [])

        if not results:
            break

        markets.extend(results)

        next_url = data.get("next")

        if not next_url:
            break

        page += 1

        # جلوگیری از حلقه بی‌نهایت
        if page > 100:
            raise RuntimeError("Too many Bitpin market pages")

    logger.info("Loaded %s Bitpin markets", len(markets))

    return markets


def find_market(markets, base, quote):
    """
    پیدا کردن بازار بر اساس BTC/IRT ، BTC/USDT و ...
    """

    target = f"{base}_{quote}".upper()

    for market in markets:

        code = str(
            market.get("code", "")
        ).upper()

        if code == target:
            return market

    return None


def get_tickers():
    """
    دریافت tickerهای Bitpin
    """

    data = api_get(
        f"{BITPIN_API}/mkt/tickers/"
    )

    if isinstance(data, dict):

        # حالت رایج API
        if "results" in data:
            return data["results"]

        # در صورت تغییر ساختار
        if "data" in data:
            return data["data"]

    if isinstance(data, list):
        return data

    raise RuntimeError(
        "Unknown Bitpin ticker response format"
    )


def ticker_by_market_code(tickers, market_code):
    """
    پیدا کردن ticker بر اساس symbol بازار
    """

    target = market_code.upper()

    for ticker in tickers:

        code = str(
            ticker.get("symbol")
            or ticker.get("code")
            or ticker.get("market")
            or ""
        ).upper()

        if code == target:
            return ticker

    return None


def get_price_from_ticker(ticker):
    """
    استخراج قیمت از ticker
    """

    possible_fields = [
        "price",
        "last",
        "close"
    ]

    for field in possible_fields:

        value = ticker.get(field)

        if value is not None:

            try:
                return Decimal(str(value))
            except InvalidOperation:
                pass

    raise RuntimeError(
        f"Could not find price in ticker: {ticker}"
    )


# =========================
# FORMATTING
# =========================

def format_number(value, decimals=0):

    value = Decimal(value)

    formatted = f"{value:,.{decimals}f}"

    return formatted


def rial_from_irt(irt_price):
    """
    Bitpin IRT = تومان
    ریال = تومان × 10
    """

    return Decimal(irt_price) * Decimal("10")


def usd_price_from_irt(
    asset_irt,
    usdt_irt
):
    """
    تبدیل قیمت ریالی دارایی به USD
    با استفاده از قیمت USDT/IRT

    asset USD =
        asset IRT / USDT IRT
    """

    if usdt_irt <= 0:
        raise ValueError(
            "USDT/IRT price must be positive"
        )

    return asset_irt / usdt_irt


# =========================
# MARKET DATA
# =========================

def fetch_market_data():

    markets = get_all_markets()

    tickers = get_tickers()

    required_markets = {
        "BTC_IRT": ("BTC", "IRT"),
        "BTC_USDT": ("BTC", "USDT"),

        "PAXG_IRT": ("PAXG", "IRT"),
        "PAXG_USDT": ("PAXG", "USDT"),

        "USDT_IRT": ("USDT", "IRT"),
    }

    selected = {}

    for name, (base, quote) in required_markets.items():

        market = find_market(
            markets,
            base,
            quote
        )

        if market is None:

            raise RuntimeError(
                f"Bitpin market not found: {name}"
            )

        code = market.get("code")

        ticker = ticker_by_market_code(
            tickers,
            code
        )

        if ticker is None:

            raise RuntimeError(
                f"Ticker not found for: {code}"
            )

        price = get_price_from_ticker(ticker)

        if price <= 0:

            raise RuntimeError(
                f"Invalid price for {code}: {price}"
            )

        selected[name] = {
            "code": code,
            "price": price,
        }

    return selected


# =========================
# TELEGRAM MESSAGE
# =========================

def build_message(data):

    btc_irt = data["BTC_IRT"]["price"]
    btc_usdt = data["BTC_USDT"]["price"]

    paxg_irt = data["PAXG_IRT"]["price"]
    paxg_usdt = data["PAXG_USDT"]["price"]

    usdt_irt = data["USDT_IRT"]["price"]

    btc_rial = rial_from_irt(btc_irt)
    paxg_rial = rial_from_irt(paxg_irt)
    usdt_rial = rial_from_irt(usdt_irt)

    # قیمت دلاری محاسبه‌شده از بازار Bitpin
    btc_usd = usd_price_from_irt(
        btc_irt,
        usdt_irt
    )

    paxg_usd = usd_price_from_irt(
        paxg_irt,
        usdt_irt
    )

    # کنترل sanity check:
    # اگر قیمت دلاری مستقیم Bitpin موجود باشد،
    # اختلاف بسیار شدید را خطا در نظر می‌گیریم.
    btc_usd_direct = btc_usdt
    paxg_usd_direct = paxg_usdt

    def suspicious(calculated, direct):

        if direct <= 0:
            return False

        ratio = calculated / direct

        return ratio < Decimal("0.80") or ratio > Decimal("1.20")

    if suspicious(btc_usd, btc_usd_direct):

        raise RuntimeError(
            f"BTC USD sanity check failed: "
            f"calculated={btc_usd}, direct={btc_usd_direct}"
        )

    if suspicious(paxg_usd, paxg_usd_direct):

        raise RuntimeError(
            f"PAXG USD sanity check failed: "
            f"calculated={paxg_usd}, direct={paxg_usd_direct}"
        )

    now = datetime.now(TIMEZONE)

    date_text = now.strftime("%Y/%m/%d")
    time_text = now.strftime("%H:%M")

    message = f"""
📊 <b>گزارش بازار بیت‌پین</b>

🟠 <b>Bitcoin (BTC)</b>

🇺🇸 دلار:
<b>${format_number(btc_usd, 2)}</b>

🇮🇷 ریال:
<b>{format_number(btc_rial, 0)} ریال</b>


🟡 <b>PAX Gold (PAXG)</b>

🇺🇸 دلار:
<b>${format_number(paxg_usd, 2)}</b>

🇮🇷 ریال:
<b>{format_number(paxg_rial, 0)} ریال</b>


🟢 <b>Tether (USDT)</b>

🇺🇸 دلار:
<b>$1.00</b>

🇮🇷 ریال:
<b>{format_number(usdt_rial, 0)} ریال</b>


🕐 <b>آخرین بروزرسانی:</b>
{date_text} — {time_text}

📌 منبع: Bitpin
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

    logger.info("Telegram message sent successfully")


# =========================
# MAIN
# =========================

def main():

    logger.info("Starting Bitpin market job...")

    data = fetch_market_data()

    message = build_message(data)

    logger.info("Generated message:")
    logger.info("\n%s", message)

    send_telegram(message)

    logger.info("Job completed successfully")


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        logger.exception(
            "JOB FAILED: %s",
            exc
        )

        sys.exit(1)
