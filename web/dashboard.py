import asyncio
import os
import sqlite3
import sys
import time

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from rich.console import Console

# Ensure src module is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import CHECK_INTERVAL_MINUTES
from src.runner import run_once

# ---------------------------------------------------------
# Configuration & Setup
# ---------------------------------------------------------
os.environ["PYTHONIOENCODING"] = "utf-8"
load_dotenv()
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "10000"))
DB_FILE = "data/trades.db"

app = FastAPI(title="Weather AI Agent Dashboard")
os.makedirs("web/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# ---------------------------------------------------------
# Global State for Background Agent
# ---------------------------------------------------------
# AUTO_START_AGENT=true in Railway env vars means the agent starts
# automatically on every deploy without needing a manual UI button click.
AUTO_START = os.getenv("AUTO_START_AGENT", "false").lower() == "true"
AGENT_RUNNING = AUTO_START
IS_WORKING = False  # To prevent overlapping runs
# Set NEXT_RUN_TIME to now so the first run fires immediately on startup
NEXT_RUN_TIME = time.time() if AUTO_START else 0


def get_conn():
    """Returns a row-factory configured SQLite connection."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------
# Background Worker Loop
# ---------------------------------------------------------
async def agent_worker_loop():
    """Continuously runs the agent logic in the background if enabled."""
    global IS_WORKING, NEXT_RUN_TIME
    while True:
        if not AGENT_RUNNING:
            NEXT_RUN_TIME = 0
            await asyncio.sleep(1)
            continue

        if NEXT_RUN_TIME == 0 or time.time() >= NEXT_RUN_TIME:
            if not IS_WORKING:
                try:
                    IS_WORKING = True
                    print("\n[Dashboard Worker] Agent is active. Running cycle...")
                    await run_in_threadpool(run_once)
                    print(f"[Dashboard Worker] Cycle complete. Next run in {CHECK_INTERVAL_MINUTES} min.")
                except Exception as e:
                    print(f"[Dashboard Worker] Error during run: {e}")
                finally:
                    IS_WORKING = False
                    NEXT_RUN_TIME = time.time() + (CHECK_INTERVAL_MINUTES * 60)
        
        await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """On startup: ensure DB directory exists, start worker, and send Telegram ping."""
    os.makedirs("data", exist_ok=True)
    asyncio.create_task(agent_worker_loop())
    if AUTO_START:
        print(f"[Dashboard] AUTO_START_AGENT=true — agent will run immediately.")
        # Send a Telegram startup notification
        try:
            from src.telegram_alert import send_message
            send_message(
                "🚀 <b>Weather AI Agent — Deployed & Started</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Agent is now running on Railway.\n"
                f"First cycle starting now. Interval: {CHECK_INTERVAL_MINUTES} min."
            )
        except Exception as e:
            print(f"[Dashboard] Startup Telegram ping failed: {e}")


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


# ---------------------------------------------------------
# API Endpoints: Agent Controls
# ---------------------------------------------------------
@app.get("/api/agent/status")
def agent_status():
    seconds_left = max(0, int(NEXT_RUN_TIME - time.time())) if NEXT_RUN_TIME > 0 else 0
    return {
        "running": AGENT_RUNNING, 
        "working": IS_WORKING,
        "seconds_until_next": seconds_left
    }


@app.post("/api/agent/toggle")
def agent_toggle():
    global AGENT_RUNNING, NEXT_RUN_TIME
    AGENT_RUNNING = not AGENT_RUNNING
    status_str = "STARTED" if AGENT_RUNNING else "STOPPED"
    print(f"\n[Dashboard] Agent {status_str} via UI.")
    if not AGENT_RUNNING:
        NEXT_RUN_TIME = 0
    return {"running": AGENT_RUNNING}


@app.post("/api/agent/force_run")
def agent_force_run():
    """Forces the agent to run a cycle immediately."""
    global AGENT_RUNNING, NEXT_RUN_TIME
    print("\n[Dashboard] Manual trigger requested via UI.")
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
