"""Interactive terminal entrypoint: `uv run agent`."""

from __future__ import annotations

import logging
import sys

from rich.console import Console

from .config import settings
from .core import build_agent

console = Console()


def main() -> int:
    logging.basicConfig(level=settings.log_level)

    console.print(f"[dim]model: {settings.model_id}  region: {settings.region}[/dim]")
    console.print("[dim]Type your request. Ctrl-C or 'exit' to quit.[/dim]\n")

    agent = build_agent()

    while True:
        try:
            prompt = console.input("[bold cyan]you ›[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye[/dim]")
            return 0

        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return 0

        console.print("\n[bold green]agent ›[/bold green] ", end="")
        try:
            agent(prompt)
        except Exception as exc:  # noqa: BLE001 - a REPL should show errors, not die
            console.print(f"\n[bold red]error:[/bold red] {exc}")
        console.print()


if __name__ == "__main__":
    sys.exit(main())
