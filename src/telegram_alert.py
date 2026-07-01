import os

import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> bool:
    """
    Send any text message to your Telegram chat.
    Returns True if sent, False if skipped or failed.
    Supports HTML formatting: <b>bold</b>, <i>italic</i>
    """
    if not TELEGRAM_BOT_TOKEN:
        return False  # Silently skip — token not configured

    if not TELEGRAM_CHAT_ID:
        print("[Telegram] TELEGRAM_CHAT_ID not set in .env — skipping alert.")
        print("[Telegram] Message @userinfobot on Telegram to get your Chat ID.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        print("[Telegram] Network error — cannot reach Telegram API. Check internet connection.")
        return False
    except requests.exceptions.Timeout:
        print("[Telegram] Request timed out sending Telegram message.")
        return False
    except Exception as e:
        print(f"[Telegram] Failed to send message: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"[Telegram] API response: {e.response.text}")
        return False


def send_trade_alert(trade: dict) -> bool:
    """
    Send a formatted Telegram message when a trade is placed.
    """
    action = trade.get("action", "").replace("_", " ")
    city = trade.get("city", "Unknown")
    bet = trade.get("bet_size_usd", 0)
    edge = trade.get("edge", 0)
    our_p = trade.get("our_probability", "?")
    mkt_p = trade.get("market_price", "?")
    reason = trade.get("reason", "")[:120]

    emoji = "🟢" if "YES" in trade.get("action", "") else "🔴"
    edge_sign = "+" if edge >= 0 else ""

    msg = (
        f"{emoji} <b>TRADE PLACED — {city}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action:</b>   {action}\n"
        f"<b>Bet Size:</b> ${bet:,.2f}\n"
        f"<b>Our Prob:</b> {our_p}%\n"
        f"<b>Market:</b>   {mkt_p}%\n"
        f"<b>Edge:</b>     {edge_sign}{edge}%\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{reason}</i>"
    )
    return send_message(msg)


def send_resolution_alert(
    trade: dict, outcome: str, pnl: float, new_balance: float
) -> bool:
    """
    Send a formatted Telegram message when a trade resolves (WON/LOST).
    """
    city = trade.get("city", "Unknown")
    action = trade.get("action", "").replace("_", " ")
    emoji = "✅" if outcome == "WON" else "❌"
    sign = "+" if pnl >= 0 else ""

    msg = (
        f"{emoji} <b>TRADE RESOLVED — {city}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action:</b>   {action}\n"
        f"<b>Outcome:</b>  {outcome}\n"
        f"<b>P&L:</b>      {sign}${pnl:,.2f}\n"
        f"<b>Balance:</b>  ${new_balance:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    return send_message(msg)


def send_daily_summary(stats: dict, balance: float) -> bool:
    """
    Send a daily summary message with portfolio stats.
    """
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    pnl = stats.get("total_pnl", 0)
    win_rate = stats.get("win_rate_pct", 0)
    sign = "+" if pnl >= 0 else ""

    msg = (
        f"📊 <b>Daily Summary — Weather AI Trading Agent</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Balance:</b>   ${balance:,.2f}\n"
        f"<b>Total P&L:</b> {sign}${pnl:,.2f}\n"
        f"<b>Win Rate:</b>  {win_rate}%\n"
        f"<b>Wins:</b>      {wins}\n"
        f"<b>Losses:</b>    {losses}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    return send_message(msg)


if __name__ == "__main__":
    print("Testing Telegram alerts...")
    ok = send_message(
        "🚀 <b>Weather AI Trading Agent</b> — Test message!\n"
        "If you can see this, Telegram alerts are working correctly."
    )
    if ok:
        print("✅ Message sent! Check your Telegram.")
    else:
        print(
            "⚠  Message not sent. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        )
        print("   Step 1: Message @userinfobot on Telegram to get your Chat ID")
        print("   Step 2: Add TELEGRAM_CHAT_ID=<your_id> to your .env file")
