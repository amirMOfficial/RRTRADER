import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "1h"
LIMIT = 250

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

BINANCE_URL = "https://api.binance.com/api/v3/klines"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"


def get_klines():
    r = requests.get(
        BINANCE_URL,
        params={"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()

    cols = [
        "open_time","open","high","low","close","volume","close_time",
        "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df):
    df = df.copy()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["rsi"] = rsi(df["close"], 14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


def swing_points(df, left=2, right=2):
    highs = []
    lows = []
    h = df["high"].values
    l = df["low"].values

    for i in range(left, len(df)-right):
        if h[i] == max(h[i-left:i+right+1]):
            highs.append(i)
        if l[i] == min(l[i-left:i+right+1]):
            lows.append(i)
    return highs, lows


def analyze(df):
    # Exclude the currently forming candle; only the last CLOSED candle is analyzed.
    now = pd.Timestamp.now(tz="UTC")
    closed = df[df["close_time"] <= now].copy()
    if len(closed) < 210:
        raise RuntimeError("Not enough closed candles.")

    x = add_indicators(closed).reset_index(drop=True)
    last = x.iloc[-1]

    highs, lows = swing_points(x, 2, 2)
    recent_highs = [i for i in highs if i < len(x)-2][-4:]
    recent_lows = [i for i in lows if i < len(x)-2][-4:]

    last_swing_high = x.loc[recent_highs[-1], "high"] if recent_highs else np.nan
    prev_swing_high = x.loc[recent_highs[-2], "high"] if len(recent_highs) >= 2 else np.nan
    last_swing_low = x.loc[recent_lows[-1], "low"] if recent_lows else np.nan
    prev_swing_low = x.loc[recent_lows[-2], "low"] if len(recent_lows) >= 2 else np.nan

    bullish_structure = (
        pd.notna(last_swing_high) and pd.notna(prev_swing_high) and
        pd.notna(last_swing_low) and pd.notna(prev_swing_low) and
        last_swing_high > prev_swing_high and last_swing_low > prev_swing_low
    )
    bearish_structure = (
        pd.notna(last_swing_high) and pd.notna(prev_swing_high) and
        pd.notna(last_swing_low) and pd.notna(prev_swing_low) and
        last_swing_high < prev_swing_high and last_swing_low < prev_swing_low
    )

    # Simple liquidity sweep: last closed candle takes a recent swing and closes back inside.
    prev20_high = x["high"].iloc[-21:-1].max()
    prev20_low = x["low"].iloc[-21:-1].min()
    bull_sweep = last["low"] < prev20_low and last["close"] > prev20_low
    bear_sweep = last["high"] > prev20_high and last["close"] < prev20_high

    # Simple displacement / volume confirmation.
    body = abs(last["close"] - last["open"])
    ranges = (x["high"] - x["low"]).replace(0, np.nan)
    avg_range = ranges.iloc[-21:-1].mean()
    displacement = body > 1.3 * avg_range
    volume_ok = last["volume"] > last["vol_ma20"] if pd.notna(last["vol_ma20"]) else False

    ema_bias = "bullish" if last["close"] > last["ema200"] else "bearish"
    rsi_val = float(last["rsi"])

    # FVG approximation: 3-candle imbalance.
    fvg_bull = x.iloc[-1]["low"] > x.iloc[-3]["high"]
    fvg_bear = x.iloc[-1]["high"] < x.iloc[-3]["low"]

    score_buy = 0
    score_sell = 0
    reasons_buy = []
    reasons_sell = []

    if bullish_structure:
        score_buy += 2
        reasons_buy.append("ساختار صعودی")
    if bearish_structure:
        score_sell += 2
        reasons_sell.append("ساختار نزولی")
    if ema_bias == "bullish":
        score_buy += 1
        reasons_buy.append("قیمت بالای EMA200")
    else:
        score_sell += 1
        reasons_sell.append("قیمت زیر EMA200")
    if bull_sweep:
        score_buy += 2
        reasons_buy.append("Liquidity Sweep صعودی")
    if bear_sweep:
        score_sell += 2
        reasons_sell.append("Liquidity Sweep نزولی")
    if displacement and volume_ok:
        if last["close"] > last["open"]:
            score_buy += 1
            reasons_buy.append("Displacement + حجم")
        elif last["close"] < last["open"]:
            score_sell += 1
            reasons_sell.append("Displacement + حجم")
    if fvg_bull:
        score_buy += 1
        reasons_buy.append("Bullish FVG")
    if fvg_bear:
        score_sell += 1
        reasons_sell.append("Bearish FVG")

    # Conservative: require strong confluence.
    if score_buy >= 5 and score_buy > score_sell and 50 <= rsi_val <= 72:
        status = "BUY WATCH"
        bias = "صعودی"
        reasons = reasons_buy
    elif score_sell >= 5 and score_sell > score_buy and 28 <= rsi_val <= 50:
        status = "SELL WATCH"
        bias = "نزولی"
        reasons = reasons_sell
    else:
        status = "NO SETUP"
        bias = "خنثی/نامشخص"
        reasons = []

    close = float(last["close"])
    # Informational zones only; not an automatic execution signal.
    if status == "BUY WATCH":
        entry_low = min(close, float(last["open"]))
        entry_high = close
        sl = min(float(last["low"]), prev20_low)
        risk = max(entry_high - sl, close * 0.001)
        tp1 = close + 1.5 * risk
        tp2 = close + 2.5 * risk
    elif status == "SELL WATCH":
        entry_low = close
        entry_high = max(close, float(last["open"]))
        sl = max(float(last["high"]), prev20_high)
        risk = max(sl - entry_low, close * 0.001)
        tp1 = close - 1.5 * risk
        tp2 = close - 2.5 * risk
    else:
        entry_low = entry_high = sl = tp1 = tp2 = np.nan

    return {
        "candle_time": last["close_time"],
        "close": close,
        "ema200": float(last["ema200"]),
        "rsi": rsi_val,
        "bias": bias,
        "status": status,
        "reasons": reasons,
        "bull_sweep": bool(bull_sweep),
        "bear_sweep": bool(bear_sweep),
        "fvg_bull": bool(fvg_bull),
        "fvg_bear": bool(fvg_bear),
        "entry_low": entry_low,
        "entry_high": entry_high,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


def fmt(v):
    if pd.isna(v):
        return "-"
    return f"{v:,.2f}"


def send_telegram(text):
    r = requests.post(
        TELEGRAM_URL,
        json={"chat_id": CHAT_ID, "text": text},
        timeout=20,
    )
    r.raise_for_status()


def main():
    df = get_klines()
    a = analyze(df)

    if a["status"] == "NO SETUP":
        setup = "❌ ستاپ نداریم"
        detail = "شرایط هم‌زمان برای یک ستاپ معتبر کافی نیست."
    else:
        setup = f"🟢 {a['status']}" if a["status"].startswith("BUY") else f"🔴 {a['status']}"
        detail = "\n".join(f"• {r}" for r in a["reasons"])

    msg = (
        f"📊 BTCUSDT — 1H\n"
        f"🕐 کندل بسته‌شده: {a['candle_time'].strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"💰 Close: {fmt(a['close'])}\n"
        f"📈 EMA200: {fmt(a['ema200'])}\n"
        f"📉 RSI(14): {a['rsi']:.1f}\n"
        f"🧭 Bias: {a['bias']}\n"
        f"💧 Sweep: {'Bullish' if a['bull_sweep'] else 'Bearish' if a['bear_sweep'] else 'None'}\n"
        f"🧩 FVG: {'Bullish' if a['fvg_bull'] else 'Bearish' if a['fvg_bear'] else 'None'}\n\n"
        f"{setup}\n"
        f"{detail}\n"
    )

    if a["status"] != "NO SETUP":
        msg += (
            f"\n🎯 Entry zone: {fmt(a['entry_low'])} – {fmt(a['entry_high'])}\n"
            f"🛑 SL: {fmt(a['sl'])}\n"
            f"🎯 TP1: {fmt(a['tp1'])}\n"
            f"🎯 TP2: {fmt(a['tp2'])}\n"
        )

    msg += "\n⚠️ این سیستم اعلان/تحلیل است، نه توصیه قطعی یا اجرای خودکار معامله."
    send_telegram(msg)


if __name__ == "__main__":
    main()
