"""
Vercel Serverless Function - Telegram Webhook Handler
======================================================
This file is the entry point for POST /api/webhook on Vercel.
Telegram sends updates here after you call bot.set_webhook().

Vercel expects a handler(request) or app callable at module level.
We use Flask for lightweight request handling.
"""

import os
import sys
import json
import asyncio
import logging

from flask import Flask, Request, Response, request as flask_request

# Ensure the parent directory is importable so we can use polymarket_api
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram import Bot, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from polymarket_api import (
    fetch_markets,
    markets_to_summary,
    market_detail_text,
    search_markets,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot setup (reused across invocations in the same warm container)
# ---------------------------------------------------------------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

app_bot = ApplicationBuilder().token(TOKEN).build() if TOKEN else None


# --- Command handlers (same logic as bot.py) --------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Welcome to the Polymarket Bot!\n\n"
        "Commands:\n"
        "/markets - Show top active prediction markets\n"
        "/details <keyword> - Search for a market and show details\n\n"
        "Data is sourced from the Polymarket Gamma API."
    )
    await update.message.reply_text(text)


async def cmd_markets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Fetching markets...")
    raw = fetch_markets(limit=15)
    if not raw:
        await update.message.reply_text("No markets returned. Try again later.")
        return
    summary = markets_to_summary(raw)
    await update.message.reply_text(summary, parse_mode="Markdown")


async def cmd_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /details <keyword>")
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"Searching for '{query}'...")

    raw = fetch_markets(limit=100)
    matches = search_markets(raw, query)

    if not matches:
        await update.message.reply_text(f"No markets found matching '{query}'.")
        return

    detail = market_detail_text(matches[0])
    await update.message.reply_text(detail, parse_mode="Markdown")


if app_bot:
    app_bot.add_handler(CommandHandler("start", cmd_start))
    app_bot.add_handler(CommandHandler("markets", cmd_markets))
    app_bot.add_handler(CommandHandler("details", cmd_details))


# ---------------------------------------------------------------------------
# Flask app for Vercel
# ---------------------------------------------------------------------------
flask_app = Flask(__name__)


@flask_app.route("/api/webhook", methods=["POST"])
def webhook():
    """Receive a Telegram update via webhook and process it."""
    if not app_bot:
        return Response("Bot token not configured", status=500)

    try:
        data = flask_request.get_json(force=True)
        update = Update.de_json(data, app_bot.bot)

        # Process the update asynchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(app_bot.process_update(update))
        finally:
            loop.close()

        return Response("ok", status=200)
    except Exception as exc:
        logger.exception("Error processing update")
        return Response(str(exc), status=500)


@flask_app.route("/api/webhook", methods=["GET"])
def health():
    """Simple health check."""
    return Response("Polymarket Telegram Bot webhook is running.", status=200)


# ---------------------------------------------------------------------------
# Vercel entry point
# Vercel looks for `app` at module level for Python serverless functions.
# ---------------------------------------------------------------------------
app = flask_app
