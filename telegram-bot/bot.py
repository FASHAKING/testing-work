"""
Polymarket Telegram Bot - Local Polling Mode
=============================================
Run this file directly for local development (uses long-polling).
For Vercel deployment the webhook handler lives in api/webhook.py.

Commands:
  /start           - Welcome message
  /markets         - List top active markets with probabilities
  /details <query> - Search for a market and show detailed info

Environment variables:
  TELEGRAM_BOT_TOKEN  - Token from @BotFather (required)
"""

import os
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from polymarket_api import (
    fetch_markets,
    fetch_market_by_slug,
    markets_to_summary,
    market_detail_text,
    search_markets,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start - send a welcome message."""
    text = (
        "Welcome to the Polymarket Bot!\n\n"
        "Commands:\n"
        "/markets - Show top active prediction markets\n"
        "/details <keyword> - Search for a market and show details\n\n"
        "Data is sourced from the Polymarket Gamma API."
    )
    await update.message.reply_text(text)


async def cmd_markets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets - list top active markets."""
    await update.message.reply_text("Fetching markets...")
    raw = fetch_markets(limit=15)
    if not raw:
        await update.message.reply_text("No markets returned. Try again later.")
        return
    summary = markets_to_summary(raw)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def cmd_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /details <query> - show detailed info for a market."""
    if not context.args:
        await update.message.reply_text("Usage: /details <keyword>\nExample: /details presidential election")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"Searching for '{query}'...")

    # First try to find via search in a batch of markets
    raw = fetch_markets(limit=100)
    matches = search_markets(raw, query)

    if not matches:
        await update.message.reply_text(f"No markets found matching '{query}'.")
        return

    # Show the best match
    market = matches[0]
    detail = market_detail_text(market)
    await update.message.reply_text(detail, parse_mode="Markdown")

    if len(matches) > 1:
        other = "\n".join(f"  - {m.get('question', 'Untitled')}" for m in matches[1:6])
        await update.message.reply_text(f"Other matches:\n{other}")


# ---------------------------------------------------------------------------
# Main (local polling)
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set the TELEGRAM_BOT_TOKEN environment variable.")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("markets", cmd_markets))
    app.add_handler(CommandHandler("details", cmd_details))

    logger.info("Bot started in polling mode. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
