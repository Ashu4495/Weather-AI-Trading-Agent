import os

import requests
from rich.console import Console
from rich.table import Table



os.environ["PYTHONIOENCODING"] = "utf-8"
console = Console()

GAMMA_API = "https://gamma-api.polymarket.com"  # search markets
CLOB_API = "https://clob.polymarket.com"  # get prices


def search_weather_markets(keyword: str = "weather", limit: int = 50) -> list[dict]:
    """
    Search Polymarket for markets that mention weather or temperature.
    Returns a list of raw market objects.
    """
    try:
        response = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "q": keyword,  # search term
                "active": "true",  # only open markets
                "closed": "false",  # exclude resolved
                "limit": limit,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # The API returns a list directly or wrapped in a key
        if isinstance(data, list):
            return data
        return data.get("markets", data.get("data", []))

    except Exception as e:
        console.print(f"[red]Gamma API error: {e}[/red]")
        return None


def get_market_price(condition_id: str) -> dict:
    """
    Get the current YES/NO price for a market from the CLOB API.

    Price is between 0 and 1:
      0.75 means the crowd thinks there's a 75% chance of YES
    """
    try:
        response = requests.get(f"{CLOB_API}/markets/{condition_id}", timeout=10)
        response.raise_for_status()
        data = response.json()

        tokens = data.get("tokens", [])
        yes_price = None
        no_price = None

        for token in tokens:
            outcome = token.get("outcome", "").upper()
            price = float(token.get("price", 0))
            if outcome == "YES":
                yes_price = round(price, 3)
            elif outcome == "NO":
                no_price = round(price, 3)

        return {
            "condition_id": condition_id,
            "yes_price": yes_price,  # e.g. 0.72 = 72% chance YES
            "no_price": no_price,
            "success": yes_price is not None,
        }

    except Exception as e:
        return {"condition_id": condition_id, "success": False, "error": str(e)}


def find_city_in_question(question: str) -> str | None:
    """
    Check if a market question mentions one of our 5 cities.
    Returns the city name if found, else None.

    Examples of Polymarket weather questions:
      "Will New York hit 80F on June 28?"
      "Tokyo temperature above 75F?"
      "London daily high above 70 degrees?"
    """
    question_lower = question.lower()
    city_aliases = {
        "New York": ["new york", "nyc", "lga", "klga", "jfk"],
        "London": ["london", "heathrow", "egll"],
        "Tokyo": ["tokyo", "haneda", "rjtt"],
        "Sydney": ["sydney", "yssy"],
        "Dubai": ["dubai", "omdb"],
    }
    for city_name, aliases in city_aliases.items():
        if any(alias in question_lower for alias in aliases):
            return city_name
    return None


def parse_temperature_threshold(question: str) -> float | None:
    """
    Try to extract a temperature threshold from the market question.
    e.g. "Will NYC be above 80F?" -> 80.0
    """
    import re

    # Look for patterns like "80F", "80°F", "80 degrees", "80f"
    match = re.search(
        r"(\d+\.?\d*)\s*(?:°?f|degrees?\s*f|fahrenheit)", question, re.IGNORECASE
    )
    if match:
        return float(match.group(1))

    # Also check for Celsius
    match = re.search(
        r"(\d+\.?\d*)\s*(?:°?c|degrees?\s*c|celsius)", question, re.IGNORECASE
    )
    if match:
        celsius = float(match.group(1))
        return round((celsius * 9 / 5) + 32, 1)  # convert to F

    return None


def get_all_weather_markets() -> list[dict]:
    """
    Search Polymarket for weather markets, filter to our 5 cities,
    and attach current YES/NO prices.

    Returns a list of market dicts like:
    {
        "question":     "Will NYC daily high exceed 80F on June 28?",
        "city":         "New York",
        "threshold_f":  80.0,
        "yes_price":    0.72,    <- crowd says 72% chance of YES
        "no_price":     0.28,
        "market_url":   "https://polymarket.com/event/...",
        "condition_id": "0xabc...",
        "end_date":     "2026-06-28",
    }
    """
    console.print(
        "\n[bold green]Searching Polymarket for weather markets...[/bold green]"
    )

    found_markets = []
    search_terms = ["weather", "temperature", "high", "degrees", "fahrenheit"]

    # Search with multiple keywords to find more markets
    all_raw = []
    for term in search_terms:
        raw = search_weather_markets(keyword=term, limit=100)
        if raw is None:
            console.print("[red]Aborting further searches due to API error.[/red]")
            break
        all_raw.extend(raw)
        console.print(f"  [dim]Searched '{term}': {len(raw)} results[/dim]")


    # Remove duplicates by condition_id
    seen_ids = set()
    unique_raw = []
    for m in all_raw:
        cid = m.get("conditionId") or m.get("condition_id") or m.get("id", "")
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            unique_raw.append(m)

    console.print(f"  [cyan]Total unique markets found: {len(unique_raw)}[/cyan]")

    # Filter and enrich
    for market in unique_raw:
        question = market.get("question", "")
        if not question:
            continue

        # Check if this market is about one of our cities
        city = find_city_in_question(question)
        if not city:
            continue

        # Get condition ID and fetch live price
        condition_id = (
            market.get("conditionId")
            or market.get("condition_id")
            or market.get("id", "")
        )

        console.print(f"  [yellow]Found city market: {question[:60]}...[/yellow]")

        price_data = get_market_price(condition_id) if condition_id else {}

        found_markets.append(
            {
                "question": question,
                "city": city,
                "threshold_f": parse_temperature_threshold(question),
                "yes_price": price_data.get("yes_price"),
                "no_price": price_data.get("no_price"),
                "condition_id": condition_id,
                "market_url": f"https://polymarket.com/event/{market.get('slug', '')}",
                "end_date": market.get("endDate", market.get("end_date", "N/A")),
                "volume": market.get("volume", "N/A"),
            }
        )

    console.print(
        f"\n[bold green]Found {len(found_markets)} weather markets for our cities![/bold green]"
    )
    return found_markets


def get_mock_markets() -> list[dict]:
    """
    Returns realistic fake market data so we can test
    Day 3 (AI agent) and Day 4 (trading) even if Polymarket
    has no live weather markets at the moment.
    """
    console.print("[yellow]Using mock market data for testing.[/yellow]")
    return [
        {
            "question": "Will New York daily high exceed 80F on June 29?",
            "city": "New York",
            "threshold_f": 80.0,
            "yes_price": 0.60,  # market says 60% chance YES
            "no_price": 0.40,
            "condition_id": "mock-ny-001",
            "market_url": "https://polymarket.com/mock",
            "end_date": "2026-06-29",
            "volume": "$12,500",
        },
        {
            "question": "Will London daily high exceed 70F on June 29?",
            "city": "London",
            "threshold_f": 70.0,
            "yes_price": 0.55,
            "no_price": 0.45,
            "condition_id": "mock-lon-001",
            "market_url": "https://polymarket.com/mock",
            "end_date": "2026-06-29",
            "volume": "$8,200",
        },
        {
            "question": "Will Tokyo daily high exceed 75F on June 29?",
            "city": "Tokyo",
            "threshold_f": 75.0,
            "yes_price": 0.70,
            "no_price": 0.30,
            "condition_id": "mock-tok-001",
            "market_url": "https://polymarket.com/mock",
            "end_date": "2026-06-29",
            "volume": "$5,900",
        },
        {
            "question": "Will Sydney daily high exceed 60F on June 29?",
            "city": "Sydney",
            "threshold_f": 60.0,
            "yes_price": 0.45,
            "no_price": 0.55,
            "condition_id": "mock-syd-001",
            "market_url": "https://polymarket.com/mock",
            "end_date": "2026-06-29",
            "volume": "$3,400",
        },
        {
            "question": "Will Dubai daily high exceed 100F on June 29?",
            "city": "Dubai",
            "threshold_f": 100.0,
            "yes_price": 0.80,
            "no_price": 0.20,
            "condition_id": "mock-dxb-001",
            "market_url": "https://polymarket.com/mock",
            "end_date": "2026-06-29",
            "volume": "$6,100",
        },
    ]


def get_markets_with_fallback() -> list[dict]:
    """
    Try to get real markets. If none found, use mock data.
    This ensures Day 3+ can always run during development.
    """
    markets = get_all_weather_markets()
    if not markets:
        console.print(
            "[yellow]No live markets found. Using mock data so we can keep building.[/yellow]"
        )
        markets = get_mock_markets()
    return markets


def print_markets_table(markets: list[dict]):
    """Show all found markets in a readable table."""
    if not markets:
        console.print("[red]No markets to display.[/red]")
        return

    table = Table(title="\nPolymarket - Weather Markets", style="bold")
    table.add_column("City", style="bold cyan", no_wrap=True)
    table.add_column("Question", max_width=45)
    table.add_column("Threshold", justify="center")
    table.add_column("YES Price", justify="center", style="green")
    table.add_column("NO Price", justify="center", style="red")
    table.add_column("Volume", justify="center")
    table.add_column("Ends", justify="center")

    for m in markets:
        yes_p = f"{m['yes_price']*100:.0f}%" if m.get("yes_price") else "N/A"
        no_p = f"{m['no_price']*100:.0f}%" if m.get("no_price") else "N/A"
        thresh = f"{m['threshold_f']}F" if m.get("threshold_f") else "N/A"
        table.add_row(
            m["city"],
            m["question"][:45] + "..." if len(m["question"]) > 45 else m["question"],
            thresh,
            yes_p,
            no_p,
            str(m.get("volume", "N/A")),
            str(m.get("end_date", "N/A"))[:10],
        )

    console.print(table)


if __name__ == "__main__":
    console.print("[bold green]DAY 2 TEST - Polymarket Weather Markets[/bold green]")
    console.print("=" * 50)

    markets = get_markets_with_fallback()
    print_markets_table(markets)

    console.print(f"\n[bold]Total markets: {len(markets)}[/bold]")
    if markets:
        console.print("[green]Day 2 complete! Market data is working.[/green]")
