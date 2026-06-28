import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import time

from rich.console import Console
from rich.panel import Panel

console = Console()


def run_loop():
    """Keep running the full agent loop on a schedule."""
    from src.runner import run_once
    from src.config import CHECK_INTERVAL_MINUTES

    console.print(
        f"[cyan]Agent will run every {CHECK_INTERVAL_MINUTES} min. Press Ctrl+C to stop.[/cyan]"
    )
    while True:
        run_once()
        console.print(f"\n[dim]Sleeping {CHECK_INTERVAL_MINUTES} min...[/dim]")
        time.sleep(CHECK_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    if "--dashboard" in sys.argv:
        from web.dashboard import run_dashboard

        run_dashboard()
    elif "--loop" in sys.argv:
        run_loop()
    elif "--hermes-run" in sys.argv:
        from src.runner import run_once
        console.print("[bold yellow]Hermes Agent Skill Triggered[/bold yellow]")
        run_once()
        console.print("[bold green]Hermes execution complete.[/bold green]")
    else:
        from src.runner import run_once
        run_once()

