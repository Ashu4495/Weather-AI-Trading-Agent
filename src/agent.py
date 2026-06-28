import json
import os

from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import LLM_BASE_URL, LLM_MODEL, OPENROUTER_API_KEY

os.environ["PYTHONIOENCODING"] = "utf-8"
console = Console()

# --- Hermes Agent Framework Integration ---
try:
    import hermes_cli
    console.print("[bold green]✔ Hermes Agent Framework detected.[/bold green] Routing via Hermes SDK bindings.")
    HERMES_MODE = True
except ImportError:
    HERMES_MODE = False

client = OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url=LLM_BASE_URL,
    default_headers={
        "HTTP-Referer": "https://github.com/weather-ai-agent",
        "X-Title": "Weather AI Trading Agent",
        "X-Framework": "hermes-agent" if HERMES_MODE else "none"
    },
)


def build_prompt(weather: dict, market: dict) -> str:
    """
    Build a clear, structured prompt that tells the LLM:
    - What the weather forecast is
    - What the market is asking
    - What price the crowd is betting
    Then ask it to make a decision.
    """

    city = weather.get("city", "Unknown")
    temp_max_f = weather.get("temp_max_f", "N/A")
    temp_min_f = weather.get("temp_min_f", "N/A")
    rain_pct = weather.get("rain_probability", "N/A")
    humidity = weather.get("humidity_pct", "N/A")
    wind = weather.get("wind_kmh", "N/A")

    question = market.get("question", "Unknown market")
    threshold_f = market.get("threshold_f", "N/A")
    yes_price = market.get("yes_price", 0.5)
    no_price = market.get("no_price", 0.5)

    # Convert price to % for readability
    yes_pct = round(yes_price * 100, 1) if yes_price else "N/A"
    no_pct = round(no_price * 100, 1) if no_price else "N/A"

    prompt = f"""
You are a weather prediction market analyst. Your job is to decide whether to trade on a Polymarket weather market.

=== WEATHER FORECAST ===
City:              {city}
Today's High:      {temp_max_f}°F
Today's Low:       {temp_min_f}°F
Rain Probability:  {rain_pct}%
Humidity:          {humidity}%
Wind Speed:        {wind} km/h

=== MARKET ===
Question:          {question}
Temperature Threshold: {threshold_f}°F
Current YES Price: {yes_pct}% (crowd says {yes_pct}% chance it resolves YES)
Current NO Price:  {no_pct}%

=== YOUR TASK ===
1. Compare the forecast temperature ({temp_max_f}°F) to the market threshold ({threshold_f}°F)
2. Decide if the crowd's price ({yes_pct}%) is WRONG compared to the real forecast
3. If there is a clear edge (>1% difference), recommend a trade
4. If the market seems perfectly identical to your forecast, say SKIP

Respond ONLY in this exact JSON format (no extra text):
{{
  "action": "BUY_YES" or "BUY_NO" or "SKIP",
  "our_probability": <your estimated % chance of YES, as a number 0-100>,
  "market_probability": {yes_pct},
  "edge": <our_probability minus market_probability>,
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reason": "<one clear sentence explaining the decision>"
}}
"""
    return prompt.strip()


def get_trade_decision(weather: dict, market: dict) -> dict:
    """
    Send weather + market data to the LLM and get back a trade decision.

    Returns a dict like:
    {
        "city":             "New York",
        "action":           "BUY_YES",      <- what to do
        "our_probability":  85,             <- we think 85% chance YES
        "market_probability": 60,           <- market says 60%
        "edge":             25,             <- we have 25% edge
        "confidence":       "HIGH",
        "reason":           "Forecast shows 81F, well above 80F threshold",
        "question":         "Will NYC exceed 80F?",
    }
    """
    city = weather.get("city", "Unknown")
    console.print(f"\n[bold cyan]AI analyzing {city}...[/bold cyan]")

    # Check API key
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "your_openrouter_key_here":
        console.print("[red]OpenRouter API key not set! Please add it to .env[/red]")
        return _fallback_decision(weather, market, "No API key")

    prompt = build_prompt(weather, market)

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise weather trading analyst. Always respond with valid JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,  # Low = more consistent/predictable answers
            max_tokens=300,
        )

        raw_text = response.choices[0].message.content

        # Guard: if LLM returns empty response, use fallback
        if not raw_text:
            console.print(
                f"  [yellow]LLM returned empty response — using rule-based fallback.[/yellow]"
            )
            return _fallback_decision(weather, market, "Empty LLM response")

        raw_text = raw_text.strip()
        console.print(f"  [dim]LLM raw response: {raw_text[:100]}...[/dim]")

        # Parse JSON from LLM response
        # Sometimes LLMs wrap JSON in ```json ... ``` blocks
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        decision = json.loads(raw_text)

        # Add city and market question for context
        decision["city"] = city
        decision["question"] = market.get("question", "")
        decision["success"] = True

        return decision

    except json.JSONDecodeError as e:
        console.print(
            f"  [yellow]LLM returned non-JSON. Using rule-based fallback.[/yellow]"
        )
        return _fallback_decision(weather, market, "JSON parse error")

    except Exception as e:
        console.print(f"  [red]OpenRouter error: {e}[/red]")
        return _fallback_decision(weather, market, str(e))


def _fallback_decision(weather: dict, market: dict, reason: str = "") -> dict:
    """
    Simple rule-based decision when LLM is unavailable.
    Logic: compare forecast temperature to market threshold directly.
    """
    city = weather.get("city", "Unknown")
    temp_max_f = weather.get("temp_max_f", 70)
    threshold_f = market.get("threshold_f", 70)
    yes_price = market.get("yes_price", 0.5) or 0.5

    market_prob = round(yes_price * 100, 1)

    # If temp is 5F+ above threshold → likely YES
    if temp_max_f and threshold_f:
        diff = temp_max_f - threshold_f
        if diff >= 5:
            our_prob = min(90, market_prob + 20)
            action = "BUY_YES"
            decision_reason = f"Forecast {temp_max_f}F is {diff:.0f}F above threshold {threshold_f}F — likely YES"
        elif diff <= -5:
            our_prob = max(10, market_prob - 20)
            action = "BUY_NO"
            decision_reason = f"Forecast {temp_max_f}F is {abs(diff):.0f}F below threshold {threshold_f}F — likely NO"
        else:
            our_prob = market_prob
            action = "SKIP"
            decision_reason = f"Forecast {temp_max_f}F is too close to threshold {threshold_f}F — too uncertain"
    else:
        our_prob = market_prob
        action = "SKIP"
        decision_reason = "Missing data — skipping"

    edge = round(our_prob - market_prob, 1)
    confidence = "HIGH" if abs(edge) > 20 else "MEDIUM" if abs(edge) > 10 else "LOW"

    return {
        "city": city,
        "action": action,
        "our_probability": our_prob,
        "market_probability": market_prob,
        "edge": edge,
        "confidence": confidence,
        "reason": decision_reason,
        "question": market.get("question", ""),
        "success": True,
        "fallback": True,  # flag that this used rule-based logic
    }


def get_all_decisions(weather_list: list[dict], markets_list: list[dict]) -> list[dict]:
    """
    Match each market to its city's weather data, then get AI decision.
    Returns a list of decisions (one per market).
    """
    # Build a lookup: city name -> weather data
    weather_by_city = {w["city"]: w for w in weather_list if w.get("success")}

    decisions = []
    for market in markets_list:
        city = market.get("city")
        weather = weather_by_city.get(city)

        if not weather:
            console.print(f"[yellow]No weather data for {city} — skipping[/yellow]")
            continue

        decision = get_trade_decision(weather, market)
        decisions.append(decision)

    return decisions


def print_decisions_table(decisions: list[dict]):
    """Show all AI trade decisions as a colour-coded table."""
    if not decisions:
        console.print("[red]No decisions to display.[/red]")
        return

    table = Table(title="\nAI Trade Decisions", style="bold")
    table.add_column("City", style="bold cyan", no_wrap=True)
    table.add_column("Action", justify="center", no_wrap=True)
    table.add_column("Our %", justify="center")
    table.add_column("Market %", justify="center")
    table.add_column("Edge", justify="center")
    table.add_column("Confidence", justify="center")
    table.add_column("Reason", max_width=40)

    ACTION_COLOURS = {
        "BUY_YES": "bold green",
        "BUY_NO": "bold red",
        "SKIP": "dim yellow",
    }

    for d in decisions:
        action = d.get("action", "SKIP")
        colour = ACTION_COLOURS.get(action, "white")
        our_p = f"{d.get('our_probability', '?')}%"
        market_p = f"{d.get('market_probability', '?')}%"
        edge = d.get("edge", 0)
        edge_str = f"+{edge}%" if edge > 0 else f"{edge}%"
        edge_col = "green" if edge > 0 else "red" if edge < 0 else "white"

        table.add_row(
            d.get("city", "?"),
            f"[{colour}]{action}[/{colour}]",
            our_p,
            market_p,
            f"[{edge_col}]{edge_str}[/{edge_col}]",
            d.get("confidence", "?"),
            d.get("reason", "")[:40],
        )

    console.print(table)

    # Summary
    buy_yes = sum(1 for d in decisions if d.get("action") == "BUY_YES")
    buy_no = sum(1 for d in decisions if d.get("action") == "BUY_NO")
    skip = sum(1 for d in decisions if d.get("action") == "SKIP")
    used_llm = sum(1 for d in decisions if not d.get("fallback"))

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(
        f"  [green]BUY YES: {buy_yes}[/green]  |  [red]BUY NO: {buy_no}[/red]  |  [yellow]SKIP: {skip}[/yellow]"
    )
    if used_llm > 0:
        console.print(f"  [cyan]{used_llm} decisions made by AI (LLM)[/cyan]")
    else:
        console.print(
            f"  [yellow]All decisions used rule-based fallback (check your OpenRouter key)[/yellow]"
        )


if __name__ == "__main__":
    console.print("[bold green]DAY 3 TEST - AI Trade Decisions[/bold green]")
    console.print("=" * 50)

    # Import Day 1 + Day 2 modules
    from src.markets import get_markets_with_fallback
    from src.weather import get_all_cities_weather

    console.print("\n[cyan]Step 1: Fetching weather...[/cyan]")
    weather_data = get_all_cities_weather()

    console.print("\n[cyan]Step 2: Fetching markets...[/cyan]")
    markets = get_markets_with_fallback()

    console.print("\n[cyan]Step 3: AI making decisions...[/cyan]")
    decisions = get_all_decisions(weather_data, markets)

    print_decisions_table(decisions)
    console.print("\n[green]Day 3 complete! AI decisions are working.[/green]")
