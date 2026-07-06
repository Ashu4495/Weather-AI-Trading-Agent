import asyncio
import os
import sqlite3
import sys
import time
import traceback
from collections import deque
from datetime import datetime

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from rich.console import Console

# Ensure src module is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import CHECK_INTERVAL_MINUTES
# ---------------------------------------------------------
# Configuration & Setup
# ---------------------------------------------------------
os.environ["PYTHONIOENCODING"] = "utf-8"
load_dotenv()
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "10000"))
DB_FILE = "/tmp/trades.db" if os.environ.get("VERCEL") else "data/trades.db"

app = FastAPI(title="Weather AI Trading Agent Dashboard")
try:
    os.makedirs("web/static", exist_ok=True)
    if not os.environ.get("VERCEL"):
        os.makedirs("data", exist_ok=True)
except Exception:
    pass

app.mount("/static", StaticFiles(directory="web/static"), name="static")

# ---------------------------------------------------------
# In-Memory Log Buffer (last 200 lines) for /api/logs
# ---------------------------------------------------------
LOG_BUFFER: deque = deque(maxlen=200)

def log(msg: str):
    """Log to both stdout and in-memory buffer."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_BUFFER.append(line)

# ---------------------------------------------------------
# Global State for Background Agent
# ---------------------------------------------------------
# AUTO_START_AGENT=true in Railway env vars means the agent starts
# automatically on every deploy without needing a manual UI button click.
AUTO_START = os.getenv("AUTO_START_AGENT", "false").lower() == "true"
AGENT_RUNNING = AUTO_START
IS_WORKING = False   # Prevents overlapping runs
NEXT_RUN_TIME = 0    # Unix timestamp of next scheduled run (0 = run now)
CYCLE_COUNT = 0


def get_conn():
    """Returns a row-factory configured SQLite connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------
# Wrapped run_once that captures all output + errors
# ---------------------------------------------------------
def run_once_safe():
    """Run one agent cycle with full error capture and logging."""
    global CYCLE_COUNT
    CYCLE_COUNT += 1
    cycle_num = CYCLE_COUNT
    log(f"=== CYCLE #{cycle_num} STARTING ===")

    try:
        # Capture stdout/stderr from run_once
        from src.agent import get_all_decisions
        from src.markets import get_markets_with_fallback
        from src.resolve import resolve_pending_trades
        from src.trader import (
            load_portfolio,
            run_all_trades,
        )
        from src.weather import get_all_cities_weather

        # Step 1: Weather
        log("Step 1/4: Fetching weather...")
        weather = get_all_cities_weather()
        ok_weather = [w for w in weather if w.get("success")]
        log(f"  Weather: {len(ok_weather)}/{len(weather)} cities OK")
        for w in weather:
            if w.get("success"):
                log(f"  {w['city']}: {w.get('temp_max_f')}°F")
            else:
                log(f"  {w['city']}: FAILED - {w.get('error', 'unknown')}")

        if not ok_weather:
            log("ERROR: All weather fetches failed! No trades can be placed.")
            return

        # Step 2: Markets
        log("Step 2/4: Fetching markets...")
        markets = get_markets_with_fallback()
        log(f"  Markets: {len(markets)} found")

        # Step 3: AI Decisions
        log("Step 3/4: Getting AI decisions...")
        decisions = get_all_decisions(weather, markets)
        log(f"  Decisions: {len(decisions)} total")
        for d in decisions:
            log(f"  {d.get('city')}: {d.get('action')} | edge={d.get('edge')}% | our={d.get('our_probability')}% | mkt={d.get('market_probability')}%")

        if not decisions:
            log("WARNING: No decisions returned. Check weather/market city name matching.")
            return

        # Step 4: Place Trades
        log("Step 4/4: Placing trades...")
        placed = run_all_trades(decisions)
        log(f"  Placed: {len(placed)} trades")
        for t in placed:
            log(f"  TRADE: {t.get('action')} {t.get('city')} | ${t.get('bet_size_usd'):.2f} | edge={t.get('edge')}%")

        # Resolve pending
        log("Resolving pending trades...")
        resolve_pending_trades()

        portfolio = load_portfolio()
        log(f"=== CYCLE #{cycle_num} DONE | Balance: ${portfolio['balance']:,.2f} ===")

    except Exception as e:
        tb = traceback.format_exc()
        log(f"ERROR in cycle #{cycle_num}: {e}")
        log(f"TRACEBACK:\n{tb}")
        raise


# ---------------------------------------------------------
# Background Worker Loop
# ---------------------------------------------------------
async def agent_worker_loop():
    """Continuously runs the agent logic in the background if enabled."""
    global IS_WORKING, NEXT_RUN_TIME

    # Brief startup delay to let FastAPI fully initialize
    await asyncio.sleep(3)

    if AUTO_START:
        log(f"AUTO_START=true. First cycle will fire immediately.")
        NEXT_RUN_TIME = time.time()  # Fire immediately on first loop iteration

    while True:
        if not AGENT_RUNNING:
            NEXT_RUN_TIME = 0
            await asyncio.sleep(1)
            continue

        now = time.time()
        should_run = (NEXT_RUN_TIME == 0) or (now >= NEXT_RUN_TIME)

        if should_run and not IS_WORKING:
            # Set NEXT_RUN_TIME BEFORE starting the run so we don't re-fire
            NEXT_RUN_TIME = time.time() + (CHECK_INTERVAL_MINUTES * 60)
            try:
                IS_WORKING = True
                log(f"Worker: Starting cycle. Next scheduled at +{CHECK_INTERVAL_MINUTES}min")
                await run_in_threadpool(run_once_safe)
            except Exception as e:
                log(f"Worker: Cycle failed with exception: {e}")
            finally:
                IS_WORKING = False
                log(f"Worker: Cycle finished. Next run in {CHECK_INTERVAL_MINUTES} min.")

        await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """On startup: ensure directories exist, start worker, send Telegram ping."""
    if not os.environ.get("VERCEL"):
        os.makedirs("data", exist_ok=True)
    log("Dashboard starting up...")
    log(f"AUTO_START_AGENT={AUTO_START}")
    log(f"CHECK_INTERVAL_MINUTES={CHECK_INTERVAL_MINUTES}")
    log(f"DB_FILE={DB_FILE}")
    asyncio.create_task(agent_worker_loop())
    if AUTO_START:
        log("Agent auto-start enabled — sending Telegram startup ping...")
        try:
            from src.telegram_alert import send_message
            send_message(
                "🚀 <b>Weather AI Trading Agent — Deployed &amp; Started</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Agent is now running on Railway.\n"
                f"First cycle fires immediately. Interval: {CHECK_INTERVAL_MINUTES} min."
            )
            log("Telegram startup ping sent.")
        except Exception as e:
            log(f"Telegram startup ping failed: {e}")


# ---------------------------------------------------------
# API Endpoints: Data Access
# ---------------------------------------------------------
@app.get("/api/portfolio")
def get_portfolio():
    """Returns current portfolio stats."""
    import json

    # Read true balance from portfolio.json
    portfolio_file = "portfolio.json"
    current_balance = STARTING_BALANCE
    if os.path.exists(portfolio_file):
        try:
            with open(portfolio_file, "r") as f:
                port_data = json.load(f)
                current_balance = port_data.get("balance", STARTING_BALANCE)
        except Exception:
            pass

    if not os.path.exists(DB_FILE):
        return {
            "balance": current_balance,
            "start_balance": STARTING_BALANCE,
            "total_trades": 0,
            "win_rate": 0.0,
            "pnl": 0.0,
        }

    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM trades WHERE action != 'SKIP'")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM trades WHERE outcome = 'WON'")
    wins = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(pnl) FROM trades WHERE pnl IS NOT NULL")
    total_pnl = cursor.fetchone()[0] or 0.0

    conn.close()
    win_rate = round((wins / total * 100), 1) if total > 0 else 0.0

    return {
        "balance": current_balance,
        "start_balance": STARTING_BALANCE,
        "total_trades": total,
        "win_rate": win_rate,
        "pnl": round(total_pnl, 2),
    }


@app.get("/api/trades")
def get_trades():
    """Returns the list of recent trades."""
    if not os.path.exists(DB_FILE):
        return []
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


@app.get("/api/portfolio_history")
def get_portfolio_history():
    """Returns portfolio balance history for the chart."""
    if not os.path.exists(DB_FILE):
        return []
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT recorded_at, balance FROM portfolio_history ORDER BY id ASC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


@app.get("/api/logs", response_class=PlainTextResponse)
def get_logs():
    """Returns the in-memory agent log for Railway debugging."""
    if not LOG_BUFFER:
        return "No logs yet. Agent may not have run."
    return "\n".join(LOG_BUFFER)


# ---------------------------------------------------------
# API Endpoints: Agent Controls
# ---------------------------------------------------------
@app.get("/api/agent/status")
def agent_status():
    seconds_left = max(0, int(NEXT_RUN_TIME - time.time())) if NEXT_RUN_TIME > 0 else 0
    return {
        "running": AGENT_RUNNING,
        "working": IS_WORKING,
        "seconds_until_next": seconds_left,
        "cycle_count": CYCLE_COUNT,
    }


@app.post("/api/agent/toggle")
def agent_toggle():
    global AGENT_RUNNING, NEXT_RUN_TIME
    AGENT_RUNNING = not AGENT_RUNNING
    status_str = "STARTED" if AGENT_RUNNING else "STOPPED"
    log(f"Agent {status_str} via UI toggle.")
    if AGENT_RUNNING:
        NEXT_RUN_TIME = time.time()   # Fire immediately when turned on
    else:
        NEXT_RUN_TIME = 0
    return {"running": AGENT_RUNNING}


@app.post("/api/agent/force_run")
def agent_force_run():
    """Forces the agent to run a cycle immediately."""
    global AGENT_RUNNING, NEXT_RUN_TIME
    log("Manual force-run triggered via UI.")
    
    if os.environ.get("VERCEL"):
        log("Vercel detected: Running synchronously to prevent freezing...")
        run_once_safe()
        return {"status": "finished"}
    else:
        AGENT_RUNNING = True
        NEXT_RUN_TIME = time.time()  # Set to now so the loop picks it up instantly
        return {"status": "triggered"}


# ---------------------------------------------------------
# Web Routes
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root():
    """Serve the main dashboard HTML."""
    try:
        with open("web/static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard loading... refresh in a moment.</h1>"


def run_dashboard(port: int = None):
    if port is None:
        port = int(os.getenv("PORT", 8000))
    console = Console()
    console.print(f"\n[bold green]Dashboard running at http://0.0.0.0:{port}[/bold green]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    run_dashboard()
