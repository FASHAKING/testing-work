"""
One-time script to register the Telegram webhook URL with BotFather.
Run this locally after deploying to Vercel.

Usage:
  TELEGRAM_BOT_TOKEN=<your-token> VERCEL_URL=<your-app>.vercel.app python set_webhook.py
"""

import os
import requests


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    vercel_url = os.environ.get("VERCEL_URL")

    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN environment variable.")
    if not vercel_url:
        raise SystemExit("Set VERCEL_URL environment variable (e.g. my-bot.vercel.app).")

    # Ensure scheme is present
    if not vercel_url.startswith("http"):
        vercel_url = f"https://{vercel_url}"

    webhook_url = f"{vercel_url}/api/webhook"
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"

    print(f"Setting webhook to: {webhook_url}")
    resp = requests.post(api_url, json={"url": webhook_url}, timeout=15)
    resp.raise_for_status()
    result = resp.json()

    if result.get("ok"):
        print("Webhook set successfully!")
        print(f"  Description: {result.get('description')}")
    else:
        print(f"Failed: {result}")


if __name__ == "__main__":
    main()
