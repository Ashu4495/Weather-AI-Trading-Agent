import os
import random
import re
import sqlite3
from datetime import datetime

from rich.console import Console
from rich.table import Table

os.environ["PYTHONIOENCODING"] = "utf-8"
console = Console()

DB_FILE = "data/trades.db"
PORTFOLIO_FILE = "portfolio.json"


def resolve_pending_trades():
    """
    Find all PENDING trades, check the weather, and mark them WON or LOST.
    Also updates portfolio balance and sends Telegram alerts.
    """
    if not os.path.exists(DB_FILE):
        console.print("[yellow]No trades.db found — nothing to resolve.[/yellow]")
        return []

    # 1. Load pending trades from DB
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE outcome = 'PENDING'")
    pending = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not pending:
        console.print("[dim]No PENDING trades to resolve right now.[/dim]")
        return []

    console.print(
        f"[cyan]Found {len(pending)} PENDING trade(s). Fetching weather to resolve...[/cyan]"
    )

    # 2. Get live weather for all cities
    from src.weather import get_all_cities_weather

    weather_list = get_all_cities_weather()
    weather_by_city = {w["city"]: w for w in weather_list if w.get("success")}

    # 3. Load portfolio
    from src.trader import load_portfolio, save_portfolio

    portfolio = load_portfolio()

    resolved = []

    for trade in pending:
        city = trade["city"]
        action = trade["action"]
        bet_size = trade["bet_size_usd"]
        question = trade.get("question", "")

        # Parse threshold from market question (e.g. "exceed 80F")
        match = re.search(r"(\d+(?:\.\d+)?)\s*[fF]", question)
        if not match:
            console.print(
                f"  [yellow]Can't parse threshold from: '{question}' — skipping[/yellow]"
            )
            continue

        threshold_f = float(match.group(1))
        w = weather_by_city.get(city)
        if not w:
            console.print(f"  [yellow]No weather data for {city} — skipping[/yellow]")
            continue

        actual_max_f = w.get("temp_max_f")
        if actual_max_f is None:
            continue

        # --- REALITY SIMULATOR ---
        # The AI predicted based on the forecast. In the real world, the actual
        # weather often deviates from the forecast by a few degrees.
        # We add a small random variance (-3F to +3F) so that close calls
        # sometimes result in a LOST trade!
        variance = round(random.uniform(-3.5, 3.5), 1)
        forecast_f = actual_max_f
        actual_max_f = round(actual_max_f + variance, 1)

        # 4. Did the market resolve YES or NO?
        resolved_yes = actual_max_f > threshold_f

        # Did we win?
        if (action == "BUY_YES" and resolved_yes) or (
            action == "BUY_NO" and not resolved_yes
        ):
            outcome = "WON"
        else:
            outcome = "LOST"

        # 5. Calculate P&L using prediction market payout logic
        #    Payout = (bet / market_price) * $1 per share if WON, else $0
        market_price = (trade["market_price"] or 50) / 100.0

        if outcome == "WON":
            shares = bet_size / market_price
            payout = shares * 1.0  # $1 per winning share
            pnl = round(payout - bet_size, 2)
            portfolio["balance"] = round(portfolio["balance"] + payout, 2)
        else:
            pnl = round(-bet_size, 2)
            # Balance was already reduced when the bet was placed — no change

        new_balance = portfolio["balance"]

        # 6. Update database
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE trades SET outcome=?, pnl=?, balance_after=? WHERE id=?",
            (outcome, pnl, new_balance, trade["id"]),
        )
        conn.commit()
        conn.close()

        # 7. Display result
        colour = "green" if outcome == "WON" else "red"
        sign = "+" if pnl > 0 else ""
        console.print(
            f"  [bold {colour}]{outcome}[/bold {colour}] | {action} on {city} | "
            f"Forecast: {forecast_f}°F -> Actual: {actual_max_f}°F vs Threshold: {threshold_f}°F | "
            f"P&L: {sign}${pnl:.2f}"
        )

        # 8. Telegram alert
        try:
            from src.telegram_alert import send_resolution_alert

            send_resolution_alert(trade, outcome, pnl, new_balance)
        except Exception:
            pass

        resolved.append(
            {**trade, "outcome": outcome, "pnl": pnl, "actual_max_f": actual_max_f}
        )

    # 9. Save updated portfolio
    if resolved:
        save_portfolio(portfolio)

        # Save new snapshot to portfolio_history for the chart
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO portfolio_history (recorded_at, balance, num_trades, num_wins, num_losses, total_pnl)
            VALUES (?,?,?,?,?,?)
        """,
            (
                datetime.now().isoformat(),
                portfolio["balance"],
                len(resolved),
                sum(1 for r in resolved if r["outcome"] == "WON"),
                sum(1 for r in resolved if r["outcome"] == "LOST"),
                sum(r["pnl"] for r in resolved),
            ),
        )
        conn.commit()
        conn.close()

        # Send daily summary via Telegram
        try:
            from src.telegram_alert import send_daily_summary
            from src.trader import get_portfolio_stats

            stats = get_portfolio_stats()
            send_daily_summary(stats, portfolio["balance"])
        except Exception:
            pass

        console.print(
            f"\n[green]Resolved {len(resolved)} trade(s). Portfolio updated.[/green]"
        )
        console.print(
            f"[bold]New balance: [green]${portfolio['balance']:,.2f}[/green][/bold]"
        )

    return resolved


def print_resolution_table(resolved: list[dict]):
    """Show resolved trades in a pretty table."""
    if not resolved:
        return

    table = Table(title="\nResolved Trades", style="bold")
    table.add_column("City", style="bold cyan", no_wrap=True)
    table.add_column("Action", justify="center")
    table.add_column("Actual °F", justify="center")
    table.add_column("Threshold", justify="center")
    table.add_column("Outcome", justify="center")
    table.add_column("P&L", justify="right")

    for r in resolved:
        outcome_str = (
            f"[green]{r['outcome']}[/green]"
            if r["outcome"] == "WON"
            else f"[red]{r['outcome']}[/red]"
        )
        pnl = r["pnl"]
        pnl_col = "green" if pnl >= 0 else "red"
        sign = "+" if pnl >= 0 else ""
        table.add_row(
            r["city"],
            r["action"].replace("_", " "),
            f"{r['actual_max_f']}°F",
            f"{r.get('threshold_f', '?')}°F",
            outcome_str,
            f"[{pnl_col}]{sign}${pnl:.2f}[/{pnl_col}]",
        )

    console.print(table)


if __name__ == "__main__":
    console.print(
        "[bold green]DAY 6 TEST — Market Resolution & Telegram Alerts[/bold green]"
    )
    console.print("=" * 55)
    resolved = resolve_pending_trades()
    print_resolution_table(resolved)
