# Polymarket Telegram Bot - Deployment Guide

## Prerequisites

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram.
2. Copy the bot token.

## Local Development (Polling Mode)

```bash
cd telegram-bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your-token-here"
python bot.py
```

The bot will run in long-polling mode. Send `/start` to your bot in Telegram.

## Deploy to Vercel (Webhook Mode)

### 1. Add bot token as a Vercel secret

```bash
vercel secrets add telegram-bot-token "your-token-here"
```

### 2. Deploy

```bash
cd telegram-bot
vercel --prod
```

Or push to GitHub and import the repo on https://vercel.com. Set the
root directory to `telegram-bot`.

### 3. Register the webhook

After deploying, run the webhook registration script once:

```bash
export TELEGRAM_BOT_TOKEN="your-token-here"
export VERCEL_URL="your-project.vercel.app"
python set_webhook.py
```

This tells Telegram to send all updates to `https://your-project.vercel.app/api/webhook`.

### 4. Verify

Send `/start` or `/markets` to your bot on Telegram. You should get a response.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with available commands |
| `/markets` | List top 15 active prediction markets |
| `/details <keyword>` | Search for a market and show probabilities, volume, liquidity |
