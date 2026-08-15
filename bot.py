import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


# ============================================================
# SETTINGS
# ============================================================

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

# Stoch_VX3
STOCH_LENGTH = 13
SMOOTH_K = 5

# Important levels from the indicator
LOW_LEVEL = 20.0
HIGH_LEVEL = 80.0

# Binance USDⓈ-M Futures
BINANCE_URL = "https://fapi.binance.com/fapi/v1/klines"

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Persistent state
STATE_FILE = "state.json"

# UTC + 3:30
UTC_PLUS_330 = timezone(timedelta(hours=3, minutes=30))


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception as error:
        print(f"STATE LOAD ERROR: {error}")
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


# ============================================================
# BINANCE
# ============================================================

def get_klines(symbol, limit=100):

    url = (
        f"{BINANCE_URL}"
        f"?symbol={symbol}"
        f"&interval={INTERVAL}"
        f"&limit={limit}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:

        data = response.read().decode()

        return json.loads(data)


# ============================================================
# STOCH_VX3
# ============================================================

def calculate_k(klines):
    """
    Stoch_VX3:

    length = 13
    smoothK = 5

    Raw Stochastic:
        ((close - lowest low) /
        (highest high - lowest low)) * 100

    K:
        SMA(raw stochastic, 5)

    Only K is used.
    """

    raw_stochastic = []

    # --------------------------------------------------------
    # Raw Stochastic
    # --------------------------------------------------------

    for i in range(len(klines)):

        if i < STOCH_LENGTH - 1:
            raw_stochastic.append(None)
            continue

        window = klines[
            i - STOCH_LENGTH + 1:
            i + 1
        ]

        highs = [
            float(candle[2])
            for candle in window
        ]

        lows = [
            float(candle[3])
            for candle in window
        ]

        close = float(
            klines[i][4]
        )

        highest_high = max(highs)
        lowest_low = min(lows)

        # Avoid division by zero
        if highest_high == lowest_low:

            value = 0.0

        else:

            value = (
                (close - lowest_low)
                /
                (highest_high - lowest_low)
            ) * 100.0

        raw_stochastic.append(value)

    # --------------------------------------------------------
    # Smooth K = SMA 5
    # --------------------------------------------------------

    k_values = []

    for i in range(len(raw_stochastic)):

        if i < SMOOTH_K - 1:
            k_values.append(None)
            continue

        window = raw_stochastic[
            i - SMOOTH_K + 1:
            i + 1
        ]

        if any(
            value is None
            for value in window
        ):

            k_values.append(None)

        else:

            k_values.append(
                sum(window) / len(window)
            )

    return k_values


# ============================================================
# TELEGRAM
# ============================================================

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

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        result = response.read().decode()

        print(
            f"TELEGRAM RESPONSE: {result}"
        )

        return result


# ============================================================
# PROCESS SYMBOL
# ============================================================

def process_symbol(symbol, state):

    print("")
    print("=" * 50)
    print(f"Processing {symbol}")

    # --------------------------------------------------------
    # Get Binance candles
    # --------------------------------------------------------

    klines = get_klines(
        symbol,
        limit=100
    )

    if len(klines) < 30:

        print(
            f"{symbol}: Not enough candles"
        )

        return

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Binance's last candle can still be forming.
    #
    # We remove it and use ONLY the last CLOSED candle.
    # --------------------------------------------------------

    closed_klines = klines[:-1]

    # --------------------------------------------------------
    # Calculate K
    # --------------------------------------------------------

    k_values = calculate_k(
        closed_klines
    )

    k = k_values[-1]

    if k is None:

        print(
            f"{symbol}: K unavailable"
        )

        return

    # --------------------------------------------------------
    # Candle information
    # --------------------------------------------------------

    last_candle = closed_klines[-1]

    price = float(
        last_candle[4]
    )

    candle_time_ms = int(
        last_candle[0]
    )

    candle_time = datetime.fromtimestamp(
        candle_time_ms / 1000,
        tz=timezone.utc
    ).astimezone(
        UTC_PLUS_330
    )

    candle_time_text = candle_time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # --------------------------------------------------------
    # Initialize state
    # --------------------------------------------------------

    if symbol not in state:

        state[symbol] = {
            "state": "READY"
        }

    current_state = state[symbol]["state"]

    print(
        f"{symbol} | "
        f"K={k:.2f} | "
        f"State={current_state}"
    )

    # ========================================================
    # STATE MACHINE
    # ========================================================

    # --------------------------------------------------------
    # READY
    #
    # We can trigger either side.
    # --------------------------------------------------------

    if current_state == "READY":

        # ----------------------------------------------------
        # Oversold
        # ----------------------------------------------------

        if k < LOW_LEVEL:

            message = (
                "🔴 STOCH_VX3 ALERT\n\n"
                f"🪙 {symbol}\n"
                f"⏱ Timeframe: 5M\n"
                f"📊 K: {k:.2f}\n"
                f"💰 Price: {price:.8f}\n\n"
                "🔻 K < 20\n"
                "🔒 Locked until K reaches 80\n\n"
                "🕐 UTC+3:30\n"
                f"{candle_time_text}"
            )

            send_telegram(
                message
            )

            state[symbol]["state"] = "LOCKED_LOW"

            print(
                f"{symbol}: "
                f"LOW ALERT SENT"
            )

        # ----------------------------------------------------
        # Overbought
        # ----------------------------------------------------

        elif k > HIGH_LEVEL:

            message = (
                "🟢 STOCH_VX3 ALERT\n\n"
                f"🪙 {symbol}\n"
                f"⏱ Timeframe: 5M\n"
                f"📊 K: {k:.2f}\n"
                f"💰 Price: {price:.8f}\n\n"
                "🔺 K > 80\n"
                "🔒 Locked until K reaches 20\n\n"
                "🕐 UTC+3:30\n"
                f"{candle_time_text}"
            )

            send_telegram(
                message
            )

            state[symbol]["state"] = "LOCKED_HIGH"

            print(
                f"{symbol}: "
                f"HIGH ALERT SENT"
            )

    # --------------------------------------------------------
    # LOCKED LOW
    #
    # Previous alert happened below 20.
    #
    # NOTHING can trigger another alert until K >= 80.
    # --------------------------------------------------------

    elif current_state == "LOCKED_LOW":

        if k >= HIGH_LEVEL:

            state[symbol]["state"] = "READY"

            print(
                f"{symbol}: "
                f"LOW LOCK RELEASED "
                f"because K reached {k:.2f}"
            )

        else:

            print(
                f"{symbol}: "
                f"LOW LOCK ACTIVE"
            )

    # --------------------------------------------------------
    # LOCKED HIGH
    #
    # Previous alert happened above 80.
    #
    # NOTHING can trigger another alert until K <= 20.
    # --------------------------------------------------------

    elif current_state == "LOCKED_HIGH":

        if k <= LOW_LEVEL:

            state[symbol]["state"] = "READY"

            print(
                f"{symbol}: "
                f"HIGH LOCK RELEASED "
                f"because K reached {k:.2f}"
            )

        else:

            print(
                f"{symbol}: "
                f"HIGH LOCK ACTIVE"
            )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 60)
    print("STOCH_VX3 BOT START")
    print("Binance USD-M Futures")
    print("Timeframe: 5M")
    print("Timezone: UTC+3:30")
    print("=" * 60)

    state = load_state()

    for symbol in SYMBOLS:

        try:

            process_symbol(
                symbol,
                state
            )

        except Exception as error:

            print(
                f"ERROR | "
                f"{symbol} | "
                f"{type(error).__name__}: "
                f"{error}"
            )

    save_state(state)

    print("")
    print("=" * 60)
    print("STOCH_VX3 BOT FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
