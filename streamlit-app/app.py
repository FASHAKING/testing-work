"""
Polymarket Data Dashboard - Streamlit Web App
==============================================
Fetches active prediction markets from the Polymarket Gamma API,
displays them in a searchable table, and charts the top markets
by volume and probability.

Gamma API docs: https://docs.polymarket.com/developers/gamma-markets-api/overview
"""

import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import streamlit as st

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_LIMIT = 50  # markets per page

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_markets(limit: int = DEFAULT_LIMIT, offset: int = 0, active: bool = True) -> list[dict]:
    """Return a list of market dicts from the Gamma /markets endpoint."""
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
    except requests.RequestException as exc:
        st.error(f"Failed to fetch markets: {exc}")
        return []


def fetch_market_details(market_id: str) -> dict | None:
    """Return full details for a single market by its condition ID / slug."""
    try:
        resp = requests.get(f"{GAMMA_API_BASE}/markets/{market_id}", timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"Failed to fetch market {market_id}: {exc}")
        return None


def parse_probability(raw) -> float | None:
    """Safely convert a raw probability value to a float percentage (0-100)."""
    if raw is None:
        return None
    try:
        value = float(raw)
        # API returns values in 0-1 range
        if 0 <= value <= 1:
            return round(value * 100, 2)
        return round(value, 2)
    except (TypeError, ValueError):
        return None


def calculate_probabilities(outcomes: list[dict]) -> list[dict]:
    """Given a list of outcome dicts, return cleaned probability info."""
    results = []
    for outcome in outcomes:
        prob = parse_probability(outcome.get("price") or outcome.get("probability"))
        results.append({
            "outcome": outcome.get("value", outcome.get("title", "Unknown")),
            "probability_pct": prob,
        })
    return results


# ---------------------------------------------------------------------------
# Data processing
# ---------------------------------------------------------------------------

def markets_to_dataframe(markets: list[dict]) -> pd.DataFrame:
    """Convert raw market JSON list into a tidy DataFrame."""
    rows = []
    for m in markets:
        # The Gamma API nests outcome prices inside outcomePrices / outcomes
        outcome_prices = m.get("outcomePrices", "")
        yes_prob = None
        if outcome_prices:
            try:
                import json
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if isinstance(prices, list) and len(prices) > 0:
                    yes_prob = parse_probability(prices[0])
            except Exception:
                pass

        # Fall back to bestAsk / bestBid if outcomePrices missing
        if yes_prob is None:
            yes_prob = parse_probability(m.get("bestAsk") or m.get("outcomePrices"))

        volume_raw = m.get("volume", m.get("volumeNum", 0))
        liquidity_raw = m.get("liquidity", m.get("liquidityNum", 0))

        rows.append({
            "id": m.get("id", ""),
            "question": m.get("question", m.get("title", "Untitled")),
            "yes_probability": yes_prob,
            "volume_usd": safe_float(volume_raw),
            "liquidity_usd": safe_float(liquidity_raw),
            "end_date": m.get("endDate", m.get("end_date_iso", "")),
        })

    df = pd.DataFrame(rows)
    return df


def safe_float(val, default=0.0) -> float:
    """Convert val to float, returning default on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def plot_top_by_volume(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Horizontal bar chart of top-N markets by trading volume."""
    top = df.nlargest(n, "volume_usd").sort_values("volume_usd")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.5)))
    bars = ax.barh(top["question"], top["volume_usd"], color="#6366f1")
    ax.set_xlabel("Volume (USD)")
    ax.set_title(f"Top {n} Markets by Volume")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    # Wrap long labels
    ax.set_yticklabels([_wrap(q, 50) for q in top["question"]], fontsize=8)
    fig.tight_layout()
    return fig


def plot_top_by_probability(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Horizontal bar chart of top-N markets by YES probability."""
    valid = df.dropna(subset=["yes_probability"])
    top = valid.nlargest(n, "yes_probability").sort_values("yes_probability")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.5)))
    colors = ["#22c55e" if p >= 50 else "#ef4444" for p in top["yes_probability"]]
    ax.barh(top["question"], top["yes_probability"], color=colors)
    ax.set_xlabel("YES Probability (%)")
    ax.set_title(f"Top {n} Markets by YES Probability")
    ax.set_xlim(0, 105)
    ax.set_yticklabels([_wrap(q, 50) for q in top["question"]], fontsize=8)
    fig.tight_layout()
    return fig


def _wrap(text: str, width: int) -> str:
    """Insert newlines so no line exceeds *width* characters."""
    words, lines, current = text.split(), [], ""
    for w in words:
        if len(current) + len(w) + 1 > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    lines.append(current)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Polymarket Dashboard", layout="wide")
    st.title("Polymarket Active Markets Dashboard")
    st.caption("Data sourced from the Gamma API  |  https://gamma-api.polymarket.com")

    # --- Sidebar controls ---------------------------------------------------
    st.sidebar.header("Settings")
    market_count = st.sidebar.slider("Markets to fetch", 10, 200, 50, step=10)
    chart_count = st.sidebar.slider("Top-N for charts", 5, 30, 10, step=5)

    # --- Fetch data ----------------------------------------------------------
    with st.spinner("Fetching markets from Gamma API..."):
        raw_markets = fetch_markets(limit=market_count)

    if not raw_markets:
        st.warning("No markets returned. The API may be temporarily unavailable.")
        return

    df = markets_to_dataframe(raw_markets)
    st.success(f"Loaded {len(df)} active markets.")

    # --- Search / filter -----------------------------------------------------
    search = st.text_input("Search markets by keyword")
    if search:
        mask = df["question"].str.contains(search, case=False, na=False)
        df = df[mask]
        st.info(f"{len(df)} markets match '{search}'")

    # --- Data table ----------------------------------------------------------
    st.subheader("Market Data")
    display_df = df[["question", "yes_probability", "volume_usd", "liquidity_usd", "end_date"]].copy()
    display_df.columns = ["Question", "YES Prob (%)", "Volume (USD)", "Liquidity (USD)", "End Date"]
    st.dataframe(display_df, use_container_width=True, height=400)

    # --- Charts --------------------------------------------------------------
    st.subheader("Charts")
    col1, col2 = st.columns(2)

    with col1:
        fig_vol = plot_top_by_volume(df, n=chart_count)
        st.pyplot(fig_vol)
        plt.close(fig_vol)

    with col2:
        fig_prob = plot_top_by_probability(df, n=chart_count)
        st.pyplot(fig_prob)
        plt.close(fig_prob)

    # --- Single market detail ------------------------------------------------
    st.subheader("Market Detail Lookup")
    market_id_input = st.text_input("Enter a market ID (condition ID or slug) to fetch details")
    if market_id_input:
        with st.spinner("Fetching details..."):
            details = fetch_market_details(market_id_input.strip())
        if details:
            st.json(details)
        else:
            st.warning("No data returned for that ID.")


if __name__ == "__main__":
    main()
