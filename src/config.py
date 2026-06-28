import os

from dotenv import load_dotenv

# Load keys from .env file
load_dotenv()

# API KEYS
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# PAPER TRADING
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "10000"))
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

# ─── LLM SETTINGS ─────────────────────────────────────────
LLM_MODEL = "openrouter/auto"  # Auto-selects best available free model
LLM_BASE_URL = "https://openrouter.ai/api/v1"

# ─── DATABASE ─────────────────────────────────────────────
DATABASE_FILE = "data/trades.db"

# ─── THE 5 CITIES ─────────────────────────────────────────
# Each city has:
#   name       → Display name
#   country    → Country
#   lat / lon  → GPS coordinates (for weather APIs)
#   airport    → ICAO airport code (Polymarket uses this)
#   timezone   → Local timezone

CITIES = [
    {
        "name": "New York",
        "country": "USA",
        "lat": 40.6413,
        "lon": -73.7781,
        "airport": "KLGA",  # LaGuardia Airport
        "timezone": "America/New_York",
        "emoji": "🇺🇸",
    },
    {
        "name": "London",
        "country": "UK",
        "lat": 51.4700,
        "lon": -0.4543,
        "airport": "EGLL",  # Heathrow Airport
        "timezone": "Europe/London",
        "emoji": "🇬🇧",
    },
    {
        "name": "Tokyo",
        "country": "Japan",
        "lat": 35.5494,
        "lon": 139.7798,
        "airport": "RJTT",  # Tokyo Haneda Airport
        "timezone": "Asia/Tokyo",
        "emoji": "🇯🇵",
    },
    {
        "name": "Sydney",
        "country": "Australia",
        "lat": -33.9399,
        "lon": 151.1753,
        "airport": "YSSY",  # Sydney Airport
        "timezone": "Australia/Sydney",
        "emoji": "🇦🇺",
    },
    {
        "name": "Dubai",
        "country": "UAE",
        "lat": 25.2532,
        "lon": 55.3657,
        "airport": "OMDB",  # Dubai International Airport
        "timezone": "Asia/Dubai",
        "emoji": "🇦🇪",
    },
]
