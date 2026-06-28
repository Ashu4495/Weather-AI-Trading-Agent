import os
from datetime import datetime

import requests
from rich.console import Console
from rich.table import Table

from src.config import APIFY_API_TOKEN, CITIES

os.environ["PYTHONIOENCODING"] = "utf-8"

console = Console()

# Set USE_APIFY=true in .env to enable Apify scraping (slower but more data)
# By default it's OFF so the app runs fast
USE_APIFY = os.getenv("USE_APIFY", "false").lower() == "true"


def get_openmeteo_weather(city: dict) -> dict:
    """
    Fetch today's weather from Open-Meteo (free API, no key needed).
    Returns temperature, humidity, wind speed, and rain probability.
    """
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": city["lat"],
        "longitude": city["lon"],
        "daily": [
            "temperature_2m_max",  # Today's HIGH temperature (°C)
            "temperature_2m_min",  # Today's LOW temperature (°C)
            "precipitation_probability_max",  # % chance of rain
            "windspeed_10m_max",  # Max wind speed
        ],
        "hourly": [
            "relative_humidity_2m",  # Hourly humidity
        ],
        "timezone": city["timezone"],
        "forecast_days": 3,  # Today + 2 more days
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        daily = data["daily"]
        hourly = data["hourly"]

        # Get today's values (index 0)
        today_max_c = daily["temperature_2m_max"][0]
        today_min_c = daily["temperature_2m_min"][0]
        rain_pct = daily["precipitation_probability_max"][0]
        wind_kmh = daily["windspeed_10m_max"][0]

        # Average humidity for today (first 24 hours)
        humidity_avg = sum(hourly["relative_humidity_2m"][:24]) / 24

        # Convert °C to °F (Polymarket uses °F for US markets)
        today_max_f = round((today_max_c * 9 / 5) + 32, 1)
        today_min_f = round((today_min_c * 9 / 5) + 32, 1)

        return {
            "source": "Open-Meteo",
            "city": city["name"],
            "date": daily["time"][0],
            "temp_max_c": today_max_c,
            "temp_min_c": today_min_c,
            "temp_max_f": today_max_f,
            "temp_min_f": today_min_f,
            "rain_probability": rain_pct,  # 0–100%
            "wind_kmh": wind_kmh,
            "humidity_pct": round(humidity_avg, 1),
            "success": True,
        }

    except Exception as e:
        console.print(f"[red]Open-Meteo error for {city['name']}: {e}[/red]")
        return {"city": city["name"], "success": False, "error": str(e)}


def get_apify_weather(city: dict) -> dict:
    """
    Fetch weather via Apify's weather-database-scraper Actor.
    Only runs when USE_APIFY=true is set in .env
    """
    if not USE_APIFY:
        return {
            "city": city["name"],
            "source": "Apify",
            "success": False,
            "error": "Apify disabled",
        }

    if not APIFY_API_TOKEN or APIFY_API_TOKEN == "your_apify_token_here":
        console.print(
            f"[yellow]Apify token not set - skipping for {city['name']}[/yellow]"
        )
        return {
            "city": city["name"],
            "source": "Apify",
            "success": False,
            "error": "No token",
        }

    try:
        from apify_client import ApifyClient

        client = ApifyClient(APIFY_API_TOKEN)

        run_input = {
            "locations": [f"{city['name']}, {city['country']}"],
            "timeFrame": "today",
        }

        console.print(f"[cyan]  Fetching Apify data for {city['name']}...[/cyan]")

        # Call the actor and wait for it to finish
        actor_run = client.actor("oneary/weather-database-scraper").call(
            run_input=run_input
        )

        # Fix: use .default_dataset() method instead of subscript
        dataset_id = (
            actor_run.get("defaultDatasetId")
            if isinstance(actor_run, dict)
            else getattr(actor_run, "default_dataset_id", None)
        )

        if not dataset_id:
            return {
                "city": city["name"],
                "source": "Apify",
                "success": False,
                "error": "No dataset ID",
            }

        results = list(client.dataset(dataset_id).iterate_items())

        if not results:
            return {
                "city": city["name"],
                "source": "Apify",
                "success": False,
                "error": "No data returned",
            }

        item = results[0]
        return {
            "source": "Apify",
            "city": city["name"],
            "temp_max_f": item.get("maxTemperatureF"),
            "temp_min_f": item.get("minTemperatureF"),
            "rain_probability": item.get("precipitationProbability"),
            "description": item.get("weatherDescription", ""),
            "success": True,
        }

    except Exception as e:
        console.print(f"[red]Apify error for {city['name']}: {e}[/red]")
        return {
            "city": city["name"],
            "source": "Apify",
            "success": False,
            "error": str(e),
        }


def get_city_weather(city: dict) -> dict:
    """
    Get weather for one city from all sources and combine them.
    Open-Meteo is the primary source.
    Apify adds extra context if available.
    """
    console.print(
        f"\n[bold]{city['emoji']} Fetching weather for {city['name']}...[/bold]"
    )

    # Primary source
    meteo_data = get_openmeteo_weather(city)

    # Apify extra source (optional)
    apify_data = get_apify_weather(city)

    # Use Open-Meteo as base; blend Apify if available
    result = {
        "city": city["name"],
        "country": city["country"],
        "airport": city["airport"],
        "emoji": city["emoji"],
        "fetched_at": datetime.now().isoformat(),
    }

    if meteo_data.get("success"):
        result.update(
            {
                "temp_max_c": meteo_data["temp_max_c"],
                "temp_min_c": meteo_data["temp_min_c"],
                "temp_max_f": meteo_data["temp_max_f"],
                "temp_min_f": meteo_data["temp_min_f"],
                "rain_probability": meteo_data["rain_probability"],
                "wind_kmh": meteo_data["wind_kmh"],
                "humidity_pct": meteo_data["humidity_pct"],
                "date": meteo_data["date"],
                "success": True,
            }
        )

        # If Apify has extra temperature data, average it in for accuracy
        if apify_data.get("success") and apify_data.get("temp_max_f"):
            blended_max_f = round(
                (meteo_data["temp_max_f"] * 0.6 + apify_data["temp_max_f"] * 0.4), 1
            )
            result["temp_max_f"] = blended_max_f
            result["data_sources"] = ["Open-Meteo", "Apify"]
        else:
            result["data_sources"] = ["Open-Meteo"]
    else:
        result["success"] = False
        result["error"] = meteo_data.get("error", "Unknown error")

    return result


def get_all_cities_weather() -> list[dict]:
    """
    Fetch weather for ALL 5 cities.
    Returns a list of weather results.
    """
    console.print("\n[bold green]🌍 Fetching weather for all 5 cities...[/bold green]")
    results = []
    for city in CITIES:
        weather = get_city_weather(city)
        results.append(weather)
    return results


def print_weather_table(weather_data: list[dict]):
    """Show weather results as a nice table in the terminal."""
    table = Table(title="\nCurrent Weather - 5 Cities", style="bold")

    table.add_column("City", style="bold cyan", no_wrap=True)
    table.add_column("Max Temp (°C)", justify="center")
    table.add_column("Max Temp (°F)", justify="center")
    table.add_column("Min Temp (°F)", justify="center")
    table.add_column("Rain %", justify="center")
    table.add_column("Humidity %", justify="center")
    table.add_column("Wind km/h", justify="center")
    table.add_column("Sources", style="dim")

    for w in weather_data:
        if w.get("success"):
            table.add_row(
                f"{w['emoji']} {w['city']}",
                f"{w.get('temp_max_c', 'N/A')}°C",
                f"{w.get('temp_max_f', 'N/A')}°F",
                f"{w.get('temp_min_f', 'N/A')}°F",
                f"{w.get('rain_probability', 'N/A')}%",
                f"{w.get('humidity_pct', 'N/A')}%",
                f"{w.get('wind_kmh', 'N/A')}",
                ", ".join(w.get("data_sources", [])),
            )
        else:
            table.add_row(
                f"{w.get('emoji', '?')} {w['city']}",
                "[red]ERROR[/red]",
                "—",
                "—",
                "—",
                "—",
                "—",
                w.get("error", ""),
            )

    console.print(table)


if __name__ == "__main__":
    console.print("[bold green]DAY 1 TEST — Weather Data Fetching[/bold green]")
    console.print("=" * 50)

    weather_data = get_all_cities_weather()
    print_weather_table(weather_data)

    # Count successes
    ok = sum(1 for w in weather_data if w.get("success"))
    fail = len(weather_data) - ok
    console.print(f"\n[green]OK: {ok} cities fetched successfully[/green]")
    if fail:
        console.print(f"[red]FAILED: {fail} cities failed[/red]")
