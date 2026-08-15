import os
import requests
from datetime import datetime, timezone, timedelta


# ==========================================
# TELEGRAM
# ==========================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Telegram secrets are missing.")


# ==========================================
# BINANCE SPOT
# ==========================================

BINANCE_URL = "https://api.binance.com/api/v3/klines"

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
]

INTERVAL = "5m"

# Stoch_VX3 settings
LENGTH = 13
SMOOTH_K = 5


# ==========================================
# UTC +3:30
# ==========================================

UTC_3_30 = timezone(
    timedelta(hours=3, minutes=30)
)


# ==========================================
# GET SPOT KLINES
# ==========================================

def get_klines(symbol, limit=100):

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": limit
    }

    response = requests.get(
        BINANCE_URL,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# ==========================================
# STOCHASTIC VX3
# ==========================================

def calculate_k(klines):

    highs = [float(candle[2]) for candle in klines]
    lows = [float(candle[3]) for candle in klines]
    closes = [float(candle[4]) for candle in klines]

    raw_stochastic = []

    for i in range(len(closes)):

        if i < LENGTH - 1:
            raw_stochastic.append(None)
            continue

        highest_high = max(
            highs[i - LENGTH + 1:i + 1]
        )

        lowest_low = min(
            lows[i - LENGTH + 1:i + 1]
        )

        if highest_high == lowest_low:
            value = 0.0
        else:
            value = (
                (closes[i] - lowest_low)
                /
                (highest_high - lowest_low)
            ) * 100

        raw_stochastic.append(value)


    # SMA(5) = K
    k_values = []

    for i in range(len(raw_stochastic)):

        if i < LENGTH - 1 + SMOOTH_K - 1:
            k_values.append(None)
            continue

        window = raw_stochastic[
            i - SMOOTH_K + 1:i + 1
        ]

        if any(value is None for value in window):
            k_values.append(None)
        else:
            k_values.append(
                sum(window) / len(window)
            )


    return k_values[-1]


# ==========================================
# ANALYZE
# ==========================================

def analyze_symbol(symbol):

    klines = get_klines(symbol)

    k = calculate_k(klines)

    return k


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    response = requests.post(
        url,
        json=payload,
        timeout=20
    )

    response.raise_for_status()


# ==========================================
# MAIN
# ==========================================

def main():

    now = datetime.now(UTC_3_30)

    message = (
        "📊 STOCH VX3 — SPOT TEST\n\n"
        f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')} "
        "UTC+3:30\n"
        "🏦 Binance Spot\n"
        "⏱ Timeframe: 5M\n\n"
    )

    for symbol in SYMBOLS:

        try:

            k = analyze_symbol(symbol)

            if k is None:
                message += (
                    f"⚪ {symbol}\n"
                    "K = N/A\n\n"
                )
                continue

            if k >= 70:
                emoji = "🔴"
            elif k <= 30:
                emoji = "🟢"
            else:
                emoji = "🟠"

            message += (
                f"{emoji} {symbol}\n"
                f"K = {k:.2f}\n\n"
            )

        except Exception as error:

            message += (
                f"❌ {symbol}\n"
                f"K = ERROR: {error}\n\n"
            )


    message += (
        "TEST MODE\n"
        "Stoch_VX3 = Stochastic(13) + SMA(5)"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()# ==============================

UTC_3_30 = timezone(timedelta(hours=3, minutes=30))


# ==============================
# Get Binance Futures candles
# ==============================

def get_klines(symbol, limit=100):

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": limit
    }

    response = requests.get(
        BINANCE_URL,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    return response.json()


# ==============================
# Calculate Stoch VX3 K
# ==============================

def calculate_k(klines):

    highs = [float(x[2]) for x in klines]
    lows = [float(x[3]) for x in klines]
    closes = [float(x[4]) for x in klines]

    raw_stoch = []

    for i in range(len(closes)):

        if i < LENGTH - 1:
            raw_stoch.append(None)
            continue

        highest_high = max(
            highs[i - LENGTH + 1:i + 1]
        )

        lowest_low = min(
            lows[i - LENGTH + 1:i + 1]
        )

        if highest_high == lowest_low:
            raw_stoch.append(0.0)
        else:
            value = (
                (closes[i] - lowest_low)
                / (highest_high - lowest_low)
            ) * 100

            raw_stoch.append(value)

    # SMA 5 of raw stochastic = K
    k_values = []

    for i in range(len(raw_stoch)):

        if i < LENGTH - 1 + SMOOTH_K - 1:
            k_values.append(None)
            continue

        values = raw_stoch[
            i - SMOOTH_K + 1:i + 1
        ]

        if any(v is None for v in values):
            k_values.append(None)
        else:
            k_values.append(
                sum(values) / len(values)
            )

    return k_values[-1]


# ==============================
# Get all K values
# ==============================

def analyze():

    results = []

    for symbol in SYMBOLS:

        try:

            klines = get_klines(symbol)

            k = calculate_k(klines)

            if k is None:
                results.append(
                    (symbol, "N/A")
                )
            else:
                results.append(
                    (symbol, f"{k:.2f}")
                )

        except Exception as e:

            results.append(
                (symbol, f"ERROR: {e}")
            )

    return results


# ==============================
# Telegram message
# ==============================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    response = requests.post(
        url,
        json=payload,
        timeout=15
    )

    response.raise_for_status()


# ==============================
# Main
# ==============================

def main():

    now = datetime.now(UTC_3_30)

    results = analyze()

    message = (
        "📊 STOCH VX3 — TEST\n\n"
        f"⏰ {now.strftime('%Y-%m-%d %H:%M:%S')} "
        "UTC+3:30\n"
        "⏱ Timeframe: 5M\n\n"
    )

    for symbol, k in results:

        if k == "N/A":
            emoji = "⚪"
        elif k.startswith("ERROR"):
            emoji = "❌"
        else:
            k_value = float(k)

            if k_value >= 70:
                emoji = "🔴"
            elif k_value <= 30:
                emoji = "🟢"
            else:
                emoji = "🟠"

        message += (
            f"{emoji} {symbol}\n"
            f"K = {k}\n\n"
        )

    message += (
        "TEST MODE\n"
        "Stoch_VX3 K = SMA(5) of Stochastic(13)"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
