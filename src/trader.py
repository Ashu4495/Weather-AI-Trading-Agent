import json
import os
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

load_dotenv()

os.environ["PYTHONIOENCODING"] = "utf-8"
console = Console()

STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "10000"))
PORTFOLIO_FILE = "portfolio.json"
MAX_BET_PCT = 0.20  # Never bet more than 20% of bankroll
MIN_EDGE = 0.10  # Only bet if edge > 10%
DB_FILE = "data/trades.db"


def load_portfolio() -> dict:
    """Load portfolio from file, or create a fresh one."""
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            return json.load(f)
    return {
        "balance": STARTING_BALANCE,
        "start_date": datetime.now().isoformat(),
        "num_trades": 0,
    }


def save_portfolio(portfolio: dict):
    """Save portfolio state to file."""
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(portfolio, f, indent=2)


def calculate_kelly_bet(
    our_probability_pct: float, market_price_pct: float, bankroll: float
) -> dict:
    """
    Calculate how much to bet using Half-Kelly Criterion.
    Returns dict with kelly_fraction, bet_size_usd, edge, should_bet.
    """
    p = our_probability_pct / 100
    q = market_price_pct / 100
    edge = p - q

    if edge < MIN_EDGE:
        return {
            "kelly_fraction": 0,
            "bet_size_usd": 0,
            "edge_pct": round(edge * 100, 1),
            "should_bet": False,
            "reason": f"Edge {edge*100:.1f}% < minimum {MIN_EDGE*100:.0f}%",
        }

    kelly_full = edge / (1 - q) if q < 1 else 0
    kelly_half = kelly_full * 0.5
    kelly_capped = min(kelly_half, MAX_BET_PCT)
    bet_size = round(kelly_capped * bankroll, 2)

    if bet_size < 1:
        return {
            "kelly_fraction": 0,
            "bet_size_usd": 0,
            "edge_pct": round(edge * 100, 1),
            "should_bet": False,
            "reason": "Bet size too small (< $1)",
        }

    return {
        "kelly_fraction": round(kelly_capped, 4),
        "bet_size_usd": bet_size,
        "edge_pct": round(edge * 100, 1),
        "should_bet": True,
        "reason": f"Edge {edge*100:.1f}% → Half-Kelly → capped {kelly_capped*100:.1f}%",
    }


def place_paper_trade(decision: dict, portfolio: dict) -> dict | None:
    """Place a paper trade based on an AI decision. Returns trade record or None."""
    action = decision.get("action", "SKIP")
    city = decision.get("city", "Unknown")

    if action == "SKIP":
        console.print(f"  [dim]Skipping {city} (AI said SKIP)[/dim]")
        return None

    our_prob = decision.get("our_probability", 50)
    market_prob = decision.get("market_probability", 50)
    balance = portfolio["balance"]

    kelly = calculate_kelly_bet(our_prob, market_prob, balance)

    if not kelly["should_bet"]:
        console.print(f"  [yellow]Skipping {city}: {kelly['reason']}[/yellow]")
        return None

    bet_size = kelly["bet_size_usd"]
    balance_before = balance
    balance_after = round(balance - bet_size, 2)

    trade = {
        "placed_at": datetime.now().isoformat(),
        "city": city,
        "question": decision.get("question", ""),
        "action": action,
        "bet_size_usd": bet_size,
        "kelly_fraction": kelly["kelly_fraction"],
        "our_probability": our_prob,
        "market_price": market_prob,
        "edge": kelly["edge_pct"],
        "confidence": decision.get("confidence", ""),
        "reason": decision.get("reason", ""),
        "balance_before": balance_before,
        "balance_after": balance_after,
        "outcome": "PENDING",
        "pnl": None,
    }

    portfolio["balance"] = balance_after
    portfolio["num_trades"] = portfolio.get("num_trades", 0) + 1

    console.print(
        f"  [bold green]TRADE PLACED:[/bold green] [cyan]{action}[/cyan] on {city} | "
        f"Bet: [yellow]${bet_size:.2f}[/yellow] | Edge: [green]+{kelly['edge_pct']}%[/green] | "
        f"Balance: ${balance_before:.0f} -> ${balance_after:.0f}"
    )

    # Send Telegram alert (imported locally to avoid circular import at top)
    try:
        from src.telegram_alert import send_trade_alert

        send_trade_alert(trade)
    except Exception:
        pass

    return trade


def run_all_trades(decisions: list[dict]) -> list[dict]:
    """Place paper trades for all AI decisions. Returns list of placed trades."""
    import sqlite3

    # Init DB if needed
    if not os.path.exists(DB_FILE):
        _init_db()

    portfolio = load_portfolio()
    placed = []

    console.print(
        f"\n[bold]Starting balance: [green]${portfolio['balance']:,.2f}[/green][/bold]"
    )
    console.print("-" * 50)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    for decision in decisions:
        trade = place_paper_trade(decision, portfolio)
        if trade:
            cursor.execute(
                """
                INSERT INTO trades (placed_at, city, question, action, bet_size_usd,
                    kelly_fraction, our_probability, market_price, edge, confidence,
                    reason, balance_before, balance_after, outcome)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                (
                    trade["placed_at"],
                    trade["city"],
                    trade["question"],
                    trade["action"],
                    trade["bet_size_usd"],
                    trade["kelly_fraction"],
                    trade["our_probability"],
                    trade["market_price"],
                    trade["edge"],
                    trade["confidence"],
                    trade["reason"],
                    trade["balance_before"],
                    trade["balance_after"],
                    trade["outcome"],
                ),
            )
            trade["id"] = cursor.lastrowid
            placed.append(trade)

    conn.commit()

    # --- HEDGING LOGIC ---
    # Check if we have PENDING trades that need hedging
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades WHERE outcome = 'PENDING'")
    pending_trades = [dict(row) for row in cursor.fetchall()]
    
    for pt in pending_trades:
        city = pt["city"]
        original_action = pt["action"]
        
        # Find the latest decision for this city
        latest_decision = next((d for d in decisions if d.get("city") == city), None)
        if not latest_decision:
            continue
            
        new_edge = latest_decision.get("edge", 0)
        
        # If the edge has dropped significantly negative, we should hedge!
        if new_edge < -20.0:  # Threshold for hedging
            hedge_action = "BUY_NO" if original_action == "BUY_YES" else "BUY_YES"
            console.print(f"  [bold magenta]HEDGE REQUIRED:[/bold magenta] {city} edge dropped to {new_edge}%. Hedging with {hedge_action}!")
            
            # Place a hedge trade
            hedge_decision = {
                "city": city,
                "action": hedge_action,
                "our_probability": latest_decision.get("our_probability", 50),
                "market_probability": latest_decision.get("market_probability", 50),
                "confidence": "HIGH (HEDGE)",
                "reason": f"Hedging against original {original_action} position due to adverse edge shift.",
                "edge": abs(new_edge)  # Use absolute edge for kelly calculation
            }
            
            hedge_trade = place_paper_trade(hedge_decision, portfolio)
            if hedge_trade:
                hedge_trade["outcome"] = "HEDGE"
                cursor.execute(
                    """
                    INSERT INTO trades (placed_at, city, question, action, bet_size_usd,
                        kelly_fraction, our_probability, market_price, edge, confidence,
                        reason, balance_before, balance_after, outcome)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        hedge_trade["placed_at"],
                        hedge_trade["city"],
                        hedge_trade["question"],
                        hedge_trade["action"],
                        hedge_trade["bet_size_usd"],
                        hedge_trade["kelly_fraction"],
                        hedge_trade["our_probability"],
                        hedge_trade["market_price"],
                        hedge_trade["edge"],
                        hedge_trade["confidence"],
                        hedge_trade["reason"],
                        hedge_trade["balance_before"],
                        hedge_trade["balance_after"],
                        hedge_trade["outcome"],
                    ),
                )
                placed.append(hedge_trade)
                
                # Update original trade to indicate it was hedged
                cursor.execute("UPDATE trades SET outcome = 'HEDGED' WHERE id = ?", (pt["id"],))

    conn.commit()

    # Save portfolio history snapshot
    cursor.execute(
        """
        INSERT INTO portfolio_history (recorded_at, balance, num_trades, num_wins, num_losses, total_pnl)
        VALUES (?,?,?,?,?,?)
    """,
        (datetime.now().isoformat(), portfolio["balance"], len(placed), 0, 0, 0.0),
    )
    conn.commit()
    conn.close()

    save_portfolio(portfolio)

    console.print("-" * 50)
    console.print(
        f"[bold]Ending balance:  [green]${portfolio['balance']:,.2f}[/green][/bold]"
    )
    console.print(f"[bold]Trades placed:   {len(placed)}[/bold]")
    return placed


def _init_db():
    """Create database tables if they don't exist yet."""
    import sqlite3

    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            placed_at       TEXT,
            city            TEXT,
            question        TEXT,
            action          TEXT,
            bet_size_usd    REAL,
            kelly_fraction  REAL,
            our_probability REAL,
            market_price    REAL,
            edge            REAL,
            confidence      TEXT,
            reason          TEXT,
            balance_before  REAL,
            balance_after   REAL,
            outcome         TEXT DEFAULT 'PENDING',
            pnl             REAL DEFAULT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            recorded_at TEXT,
            balance     REAL,
            num_trades  INTEGER,
            num_wins    INTEGER,
            num_losses  INTEGER,
            total_pnl   REAL
        )
    """)
    conn.commit()
    conn.close()


def get_portfolio_stats() -> dict:
    """Calculate portfolio stats from all trades."""
    import sqlite3

    if not os.path.exists(DB_FILE):
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "total_pnl": 0.0,
        }

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades WHERE action != 'SKIP'")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM trades WHERE outcome = 'WON'")
    wins = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM trades WHERE outcome = 'LOST'")
    losses = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(pnl) FROM trades WHERE pnl IS NOT NULL")
    total_pnl = cursor.fetchone()[0] or 0.0
    conn.close()
    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(total_pnl, 2),
    }


def save_portfolio_snapshot(balance: float, stats: dict):
    """Save a snapshot of the current portfolio state."""
    import sqlite3

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO portfolio_history (recorded_at, balance, num_trades, num_wins, num_losses, total_pnl)
        VALUES (?,?,?,?,?,?)
    """,
        (
            datetime.now().isoformat(),
            balance,
            stats.get("total_trades", 0),
            stats.get("wins", 0),
            stats.get("losses", 0),
            stats.get("total_pnl", 0),
        ),
    )
    conn.commit()
    conn.close()


def print_trades_table(trades: list[dict]):
    """Show placed trades in a table."""
    if not trades:
        console.print("[yellow]No trades placed this run.[/yellow]")
        return
    table = Table(title="\nPaper Trades Placed", style="bold")
    table.add_column("City", style="bold cyan", no_wrap=True)
    table.add_column("Action", justify="center")
    table.add_column("Bet ($)", justify="right", style="yellow")
    table.add_column("Kelly %", justify="center")
    table.add_column("Edge %", justify="center", style="green")
    table.add_column("Confidence", justify="center")
    for t in trades:
        action_col = {
            "BUY_YES": "[bold green]BUY YES[/bold green]",
            "BUY_NO": "[bold red]BUY NO[/bold red]",
        }.get(t["action"], t["action"])
        table.add_row(
            t["city"],
            action_col,
            f"${t['bet_size_usd']:.2f}",
            f"{t['kelly_fraction']*100:.1f}%",
            f"+{t['edge']}%",
            t["confidence"],
        )
    console.print(table)


def print_portfolio_summary(portfolio: dict):
    """Show current portfolio state."""
    stats = get_portfolio_stats()
    curr = portfolio["balance"]
    change = round(curr - STARTING_BALANCE, 2)
    pct = round((change / STARTING_BALANCE) * 100, 2)
    colour = "green" if change >= 0 else "red"
    sign = "+" if change >= 0 else ""
    console.print(
        Panel(
            f"[bold]Portfolio Summary[/bold]\n\n"
            f"  Starting Balance : [white]${STARTING_BALANCE:,.2f}[/white]\n"
            f"  Current Balance  : [{colour}]${curr:,.2f}[/{colour}]\n"
            f"  Total Change     : [{colour}]{sign}${change:,.2f} ({sign}{pct}%)[/{colour}]\n\n"
            f"  Total Trades     : {stats['total_trades']}\n"
            f"  Win Rate         : {stats['win_rate_pct']}%\n"
            f"  Realized P&L     : ${stats['total_pnl']:,.2f}",
            border_style=colour,
            title="[bold]Paper Trading[/bold]",
        )
    )
