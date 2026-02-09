"""
Polymarket Gamma API helpers
=============================
Shared between the local polling bot (bot.py) and the Vercel webhook
handler (api/webhook.py).

Gamma API docs: https://docs.polymarket.com/developers/gamma-markets-api/overview
"""

import json
import requests

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_LIMIT = 50

# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def fetch_markets(limit: int = DEFAULT_LIMIT, offset: int = 0, active: bool = True) -> list[dict]:
    """Fetch a page of markets from the Gamma API."""
    params = {
        "limit": limit,
        "offset": offset,
        "active": str(active).lower(),
        "closed": "false",
    }
    try:
        resp = requests.get(f"{GAMMA_API_BASE}/markets", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return []


def fetch_market_by_slug(slug: str) -> dict | None:
    """Fetch a single market by slug or condition ID."""
    try:
        resp = requests.get(f"{GAMMA_API_BASE}/markets/{slug}", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Probability parsing
# ---------------------------------------------------------------------------

def parse_probability(raw) -> float | None:
    """Convert a raw value to a percentage (0-100). Returns None on failure."""
    if raw is None:
        return None
    try:
        value = float(raw)
        if 0 <= value <= 1:
            return round(value * 100, 2)
        return round(value, 2)
    except (TypeError, ValueError):
        return None


def extract_yes_probability(market: dict) -> float | None:
    """Pull the YES probability out of a market dict."""
    outcome_prices = market.get("outcomePrices", "")
    if outcome_prices:
        try:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if isinstance(prices, list) and len(prices) > 0:
                return parse_probability(prices[0])
        except Exception:
            pass
    return parse_probability(market.get("bestAsk"))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_markets(markets: list[dict], query: str) -> list[dict]:
    """Case-insensitive keyword search across market questions."""
    query_lower = query.lower()
    return [
        m for m in markets
        if query_lower in (m.get("question", "") or "").lower()
        or query_lower in (m.get("description", "") or "").lower()
    ]


# ---------------------------------------------------------------------------
# Formatting helpers (Telegram Markdown)
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def markets_to_summary(markets: list[dict]) -> str:
    """Format a list of markets into a Telegram-friendly summary."""
    lines = ["*Top Active Polymarket Markets*\n"]
    for i, m in enumerate(markets, 1):
        question = m.get("question", "Untitled")
        prob = extract_yes_probability(m)
        prob_str = f"{prob:.1f}%" if prob is not None else "N/A"
        volume = _safe_float(m.get("volume", m.get("volumeNum", 0)))
        lines.append(f"{i}. {question}\n   YES: {prob_str}  |  Vol: ${volume:,.0f}")
    return "\n".join(lines)


def market_detail_text(market: dict) -> str:
    """Format a single market into a detailed Telegram message."""
    question = market.get("question", "Untitled")
    description = market.get("description", "No description available.")
    prob = extract_yes_probability(market)
    prob_str = f"{prob:.1f}%" if prob is not None else "N/A"
    volume = _safe_float(market.get("volume", market.get("volumeNum", 0)))
    liquidity = _safe_float(market.get("liquidity", market.get("liquidityNum", 0)))
    end_date = market.get("endDate", market.get("end_date_iso", "Unknown"))

    # Truncate long descriptions for Telegram
    if len(description) > 400:
        description = description[:397] + "..."

    return (
        f"*{question}*\n\n"
        f"{description}\n\n"
        f"YES Probability: {prob_str}\n"
        f"Volume: ${volume:,.0f}\n"
        f"Liquidity: ${liquidity:,.0f}\n"
        f"End Date: {end_date}"
    )
