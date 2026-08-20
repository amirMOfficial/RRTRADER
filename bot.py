import os
import sys
import logging
import base64
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import jdatetime


# =========================
# CONFIG
# =========================

BITPIN_API = "https://api.bitpin.ir/v1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEZONE = ZoneInfo("Asia/Tehran")
REQUEST_TIMEOUT = 20

# Previous prices are stored in the GitHub repository.
STATE_FILE = "data/last_prices.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")


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
    """Get all Bitpin markets."""

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

        if not data.get("next"):
            break

        page += 1

        if page > 100:
            raise RuntimeError("Too many Bitpin market pages")

    logger.info("Loaded %s Bitpin markets", len(markets))
    return markets


def find_market(markets, base, quote):
    """Find a market such as BTC_IRT or BTC_USDT."""

    target = f"{base}_{quote}".upper()

    for market in markets:
        code = str(market.get("code", "")).upper()

        if code == target:
            return market

    return None


# =========================
# FORMATTING
# =========================

def format_number(value, decimals=0):
    """Format numbers with Latin digits and comma separators."""

    value = Decimal(str(value))
    return f"{value:,.{decimals}f}"


def rial_from_irt(irt_price):
    """
    Bitpin IRT is تومان.
    1 تومان = 10 ریال.
    """

    return Decimal(str(irt_price)) * Decimal("10")


def usd_price_from_irt(asset_irt, usdt_irt):
    """Convert an IRT price to approximate USD."""

    if usdt_irt <= 0:
        raise ValueError("USDT/IRT price must be positive")

    return Decimal(str(asset_irt)) / Decimal(str(usdt_irt))


def calculate_change(current, previous):
    """Calculate percentage change from previous report."""

    if previous is None:
        return None

    current = Decimal(str(current))
    previous = Decimal(str(previous))

    if previous == 0:
        return None

    return ((current - previous) / previous) * Decimal("100")


def format_change(change):
    """Format percentage change for Telegram."""

    if change is None:
        return "—"

    change = Decimal(str(change))

    if change > 0:
        return f"🟢 +{change:.2f}%"

    if change < 0:
        return f"🔴 {change:.2f}%"

    return "⚪ 0.00%"


# =========================
# PREVIOUS PRICE STORAGE
# =========================

def load_previous_prices():
    """
    Read the previous prices from GitHub.
    On the first run, returns an empty dictionary.
    """

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logger.warning(
            "GITHUB_TOKEN or GITHUB_REPOSITORY is missing. "
            "Percentage change will be unavailable."
        )
        return {}, None

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/{STATE_FILE}"
    )

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    response = session.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code == 404:
        logger.info("No previous price file found. This is the first run.")
        return {}, None

    response.raise_for_status()

    file_data = response.json()

    content = base64.b64decode(
        file_data["content"]
    ).decode("utf-8")

    prices = json.loads(content)

    return prices, file_data["sha"]


def save_current_prices(prices, sha=None):
    """Save current prices into the GitHub repository."""

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        logger.warning(
            "GitHub token/repository unavailable; "
            "previous prices were not saved."
        )
        return

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}/contents/{STATE_FILE}"
    )

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

    content = json.dumps(
        prices,
        ensure_ascii=False,
        indent=2
    )

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Update Bitpin previous prices",
        "content": encoded,
        "branch": "main",
    }

    if sha:
        payload["sha"] = sha

    response = session.put(
        url,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    logger.info("Previous prices saved successfully.")


# =========================
# MARKET DATA
# =========================

def fetch_market_data():

    markets = get_all_markets()

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

        price = market.get("price")

        if price is None:
            raise RuntimeError(
                f"Price not found for market: {name}"
            )

        try:
            price = Decimal(str(price))
        except (InvalidOperation, ValueError):
            raise RuntimeError(
                f"Invalid price for {name}: {price}"
            )

        if price <= 0:
            raise RuntimeError(
                f"Invalid/non-positive price for {name}: {price}"
            )

        selected[name] = {
            "code": market.get("code", name),
            "price": price,
        }

    logger.info(
        "Selected Bitpin markets: %s",
        list(selected.keys())
    )

    return selected


# =========================
# TELEGRAM MESSAGE
# =========================

def build_message(data, previous_prices):

    btc_irt = data["BTC_IRT"]["price"]
    btc_usdt = data["BTC_USDT"]["price"]

    paxg_irt = data["PAXG_IRT"]["price"]
    paxg_usdt = data["PAXG_USDT"]["price"]

    usdt_irt = data["USDT_IRT"]["price"]

    btc_rial = rial_from_irt(btc_irt)
    paxg_rial = rial_from_irt(paxg_irt)
    usdt_rial = rial_from_irt(usdt_irt)

    btc_usd = usd_price_from_irt(
        btc_irt,
        usdt_irt
    )

    paxg_usd = usd_price_from_irt(
        paxg_irt,
        usdt_irt
    )

    # Sanity check against Bitpin's direct USD markets.
    def suspicious(calculated, direct):
        if direct <= 0:
            return False

        ratio = calculated / direct

        return (
            ratio < Decimal("0.80")
            or ratio > Decimal("1.20")
        )

    if suspicious(btc_usd, btc_usdt):
        raise RuntimeError(
            f"BTC USD sanity check failed: "
            f"calculated={btc_usd}, direct={btc_usdt}"
        )

    if suspicious(paxg_usd, paxg_usdt):
        raise RuntimeError(
            f"PAXG USD sanity check failed: "
            f"calculated={paxg_usd}, direct={paxg_usdt}"
        )

    btc_change = calculate_change(
        btc_rial,
        previous_prices.get("BTC")
    )

    paxg_change = calculate_change(
        paxg_rial,
        previous_prices.get("PAXG")
    )

    usdt_change = calculate_change(
        usdt_rial,
        previous_prices.get("USDT")
    )

    # Tehran local time -> Jalali calendar.
    now = datetime.now(TIMEZONE)

    jalali_now = jdatetime.datetime.fromgregorian(
        datetime=now
    )

    date_text = jalali_now.strftime("%Y/%m/%d")
    time_text = jalali_now.strftime("%H:%M")

    message = f"""
📊 <b>قیمت لحظه‌ای دلار، طلا و بیتکوین</b>

🟠 <b>Bitcoin (BTC)</b> {format_change(btc_change)}

🇺🇸 USD:
<b>${format_number(btc_usd, 2)}</b>
🇮🇷 IRR:
<b>{format_number(btc_rial, 0)} IRR</b>


🟡 <b>Gold (PAXG)</b> {format_change(paxg_change)}

🇺🇸 USD:
<b>${format_number(paxg_usd, 2)}</b>
🇮🇷 IRR:
<b>{format_number(paxg_rial, 0)} IRR</b>


🟢 <b>Tether (USDT)</b> {format_change(usdt_change)}

🇺🇸 USD:
<b>$1.00</b>
🇮🇷 IRR:
<b>{format_number(usdt_rial, 0)} IRR</b>


🕐 <b>آخرین بروزرسانی:</b>
{date_text} — {time_text}
📌 منبع: <a href="https://bitpin.ir/signup/?ref=oDdSXxtY">Bitpin</a>
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

    previous_prices, previous_sha = load_previous_prices()

    data = fetch_market_data()

    message = build_message(
        data,
        previous_prices
    )

    logger.info("Generated message:")
    logger.info("\n%s", message)

    send_telegram(message)

    current_prices = {
        "BTC": str(
            rial_from_irt(
                data["BTC_IRT"]["price"]
            )
        ),
        "PAXG": str(
            rial_from_irt(
                data["PAXG_IRT"]["price"]
            )
        ),
        "USDT": str(
            rial_from_irt(
                data["USDT_IRT"]["price"]
            )
        ),
    }

    save_current_prices(
        current_prices,
        previous_sha
    )

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
