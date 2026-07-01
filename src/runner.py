from rich.console import Console
from rich.panel import Panel

console = Console()

def run_once():
    """Run the complete agent cycle once: weather → AI → trade → resolve."""
    console.print(
        Panel.fit(
            "[bold cyan]Weather AI Trading Agent — Full Run[/bold cyan]", border_style="cyan"
        )
    )
    from src.agent import get_all_decisions, print_decisions_table
    from src.markets import get_markets_with_fallback, print_markets_table
    from src.resolve import resolve_pending_trades
    from src.trader import (
        load_portfolio,
        print_portfolio_summary,
        print_trades_table,
        run_all_trades,
    )
    from src.weather import get_all_cities_weather, print_weather_table

    weather = get_all_cities_weather()
    print_weather_table(weather)
    markets = get_markets_with_fallback()
    print_markets_table(markets)
    decisions = get_all_decisions(weather, markets)
    print_decisions_table(decisions)
    placed = run_all_trades(decisions)
    print_trades_table(placed)

    console.print("\n[dim]Resolving any previously PENDING trades...[/dim]")
    resolve_pending_trades()

    portfolio = load_portfolio()
    print_portfolio_summary(portfolio)
