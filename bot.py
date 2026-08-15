import os
import json
import urllib.request
import urllib.parse

# =========================
# SETTINGS
# =========================

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "DOGEUSDT",
    "TRXUSDT",
    "XRPUSDT",
    "BCHUSDT",
    "LTCUSDT",
]

INTERVAL = "5m"
STOCH_LENGTH = 13
SMOOTH_K = 5

LOW_LEVEL = 20.0
HIGH_LEVEL = 80.0

BINANCE_URL = "https://fapi.binance.com/fapi/v1/klines"

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

STATE_FILE = "state.json"

UTC_PLUS_330 = timezone(timedelta(hours=3, minutes=30))


# =========================
# STATE
# =========================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# =========================
# BINANCE DATA
# =========================

def get_klines(symbol, limit=100):
    url = (
        f"{BINANCE_URL}"
        f"?symbol={symbol}"
        f"&interval={INTERVAL}"
        f"&limit={limit}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


# =========================
# STOCH_VX3 K
# =========================

def calculate_k(klines):
    """
    Pine logic:

    stoch(close, high, low, 13)
    then SMA(..., 5)

    Only K is used.
    """

    raw_stoch = []

    for i in range(len(klines)):
        if i < STOCH_LENGTH - 1:
            raw_stoch.append(None)
            continue

        window = klines[i - STOCH_LENGTH + 1:i + 1]

        highs = [float(x[2]) for x in window]
        lows = [float(x[3]) for x in window]
        close = float(klines[i][4])

        highest_high = max(highs)
        lowest_low = min(lows)

        if highest_high == lowest_low:
            value = 0.0
        else:
            value = (
                (close - lowest_low)
                / (highest_high - lowest_low)
            ) * 100.0

        raw_stoch.append(value)

    # SMA 5 of the raw stochastic = K
    k_values = []

    for i in range(len(raw_stoch)):
        if i < SMOOTH_K - 1:
            k_values.append(None)
            continue

        window = raw_stoch[i - SMOOTH_K + 1:i + 1]

        if any(v is None for v in window):
            k_values.append(None)
        else:
            k_values.append(sum(window) / len(window))

    return k_values


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode()


# =========================
# ANALYSIS
# =========================

def process_symbol(symbol, state):

    # Get enough candles for calculation.
    klines = get_klines(symbol, 100)

    # Binance returns the current unfinished candle as the last candle.
    # We remove it and analyze only the last CLOSED candle.
    closed_klines = klines[:-1]

    k_values = calculate_k(closed_klines)

    k = k_values[-1]

    if k is None:
        return

    price = float(closed_klines[-1][4])

    candle_time_ms = int(closed_klines[-1][0])

    candle_time = datetime.fromtimestamp(
        candle_time_ms / 1000,
        tz=timezone.utc
    ).astimezone(UTC_PLUS_330)

    candle_time_text = candle_time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    if symbol not in state:
        state[symbol] = {
            "mode": "neutral"
        }

    current_mode = state[symbol]["mode"]

    # =========================
    # OVERSOLD
    # =========================

    if k < LOW_LEVEL:

        if current_mode != "oversold":

            message = (
                "🚨 STOCH_VX3 ALERT\n\n"
                f"🪙 {symbol}\n"
                f"⏱ Timeframe: 5M\n"
                f"📊 K: {k:.2f}\n"
                f"💰 Price: {price:.8f}\n\n"
                "🔴 K entered BELOW 20\n"
                "🔒 Oversold alert locked\n\n"
                f"🕐 UTC+3:30\n"
                f"{candle_time_text}"
            )

            send_telegram(message)

            state[symbol]["mode"] = "oversold"

    # =========================
    # OVERBOUGHT
    # =========================

    elif k > HIGH_LEVEL:

        if current_mode != "overbought":

            message = (
                "🚨 STOCH_VX3 ALERT\n\n"
                f"🪙 {symbol}\n"
                f"⏱ Timeframe: 5M\n"
                f"📊 K: {k:.2f}\n"
                f"💰 Price: {price:.8f}\n\n"
                "🟢 K entered ABOVE 80\n"
                "🔒 Overbought alert locked\n\n"
                f"🕐 UTC+3:30\n"
                f"{candle_time_text}"
            )

            send_telegram(message)

            state[symbol]["mode"] = "overbought"

    # =========================
    # UNLOCK OVERSOLD
    # =========================

    if current_mode == "oversold" and k >= HIGH_LEVEL:
        state[symbol]["mode"] = "overbought"

    # =========================
    # UNLOCK OVERBOUGHT
    # =========================

    if current_mode == "overbought" and k <= LOW_LEVEL:
        state[symbol]["mode"] = "oversold"


# =========================
# MAIN
# =========================

def main():

    state = load_state()

    for symbol in SYMBOLS:

        try:
            process_symbol(symbol, state)

        except Exception as e:

            print(
                f"ERROR | {symbol} | {type(e).__name__}: {e}"
            )

    save_state(state)


if __name__ == "__main__":
    main()
