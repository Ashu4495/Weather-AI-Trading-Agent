---
name: weather-trader
description: An autonomous agent skill that trades profitably on Polymarket weather markets.
version: 1.0.0
metadata:
  hermes:
    tags: [Finance, Crypto, Weather, Prediction Markets]
requires_tools: []
---

# Weather Trader Skill

This skill allows the Hermes Agent to automatically research, analyze, and place paper trades on global weather markets using the Kelly Criterion for risk management.

## Capabilities
- Scrapes global weather data using Open-Meteo and Apify.
- Analyzes sentiment and statistical models to predict weather outcomes in New York, London, Tokyo, Sydney, and Dubai.
- Uses OpenRouter LLM models to make trade decisions (resolving to NO/YES probabilities).
- Computes Kelly Criterion to size paper trades and manages a simulated portfolio.
- Sends live Telegram alerts when a trade is executed.

## Usage
To execute the weather trading pipeline, invoke the main python script in headless Hermes mode:

```bash
python main.py --hermes-run
```

## How It Works
The backend Python project handles the heavy lifting of interacting with the Polymarket Gamma/CLOB APIs and weather APIs. It builds a localized model and places the orders via the `polymarket-paper-trader` logic embedded in `src/trader.py`. 
The results are outputted to the standard output for the Hermes Agent to parse and relay to the user.
