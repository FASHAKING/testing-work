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
        no_prob = None
        if outcome_prices:
            try:
                import json
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if isinstance(prices, list):
                    if len(prices) > 0:
                        yes_prob = parse_probability(prices[0])
                    if len(prices) > 1:
                        no_prob = parse_probability(prices[1])
            except Exception:
                pass

        # Fall back to bestAsk / bestBid if outcomePrices missing
        if yes_prob is None:
            yes_prob = parse_probability(m.get("bestAsk") or m.get("outcomePrices"))

        # Derive NO from YES if not explicitly available
        if no_prob is None and yes_prob is not None:
            no_prob = round(100 - yes_prob, 2)

        volume_raw = m.get("volume", m.get("volumeNum", 0))
        liquidity_raw = m.get("liquidity", m.get("liquidityNum", 0))

        rows.append({
            "id": m.get("id", ""),
            "question": m.get("question", m.get("title", "Untitled")),
            "yes_probability": yes_prob,
            "no_probability": no_prob,
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

def _apply_chart_style(fig, ax):
    """Apply a consistent dark + colorful style to chart."""
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")
    ax.tick_params(colors="#c4b5fd", labelsize=8)
    ax.xaxis.label.set_color("#c4b5fd")
    ax.yaxis.label.set_color("#c4b5fd")
    ax.title.set_color("#f1f5f9")
    ax.title.set_fontweight("bold")
    for spine in ax.spines.values():
        spine.set_color("#3b3b5c")
    ax.grid(axis="x", color="#3b3b5c", linestyle="--", alpha=0.4)


def plot_top_by_volume(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Horizontal bar chart of top-N markets by trading volume."""
    import numpy as np
    top = df.nlargest(n, "volume_usd").sort_values("volume_usd")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.55)))

    # Gradient-like colors from purple to pink
    cmap = plt.cm.plasma
    colors = [cmap(0.2 + 0.6 * i / max(n - 1, 1)) for i in range(len(top))]

    ax.barh(top["question"], top["volume_usd"], color=colors, edgecolor="#1e1b4b", linewidth=0.5)
    ax.set_xlabel("Volume (USD)")
    ax.set_title(f"Top {n} Markets by Volume")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.set_yticklabels([_wrap(q, 50) for q in top["question"]], fontsize=8)
    _apply_chart_style(fig, ax)
    fig.tight_layout()
    return fig


def plot_top_by_probability(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Grouped horizontal bar chart of top-N markets by YES and NO probability."""
    import numpy as np
    valid = df.dropna(subset=["yes_probability"])
    top = valid.nlargest(n, "yes_probability").sort_values("yes_probability")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.65)))

    labels = [_wrap(q, 50) for q in top["question"]]
    y_pos = np.arange(len(labels))
    bar_height = 0.35

    ax.barh(y_pos + bar_height / 2, top["yes_probability"], bar_height,
            label="YES", color="#34d399", edgecolor="#065f46", linewidth=0.5)
    ax.barh(y_pos - bar_height / 2, top["no_probability"].fillna(0), bar_height,
            label="NO", color="#fb7185", edgecolor="#881337", linewidth=0.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Probability (%)")
    ax.set_title(f"Top {n} Markets — YES vs NO Probability")
    ax.set_xlim(0, 105)
    ax.legend(loc="lower right", facecolor="#1e1b4b", edgecolor="#7c3aed",
              labelcolor="#f1f5f9", fontsize=9)
    _apply_chart_style(fig, ax)
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

def inject_custom_css():
    """Inject custom CSS for a vibrant, colorful dashboard."""
    st.markdown("""
    <style>
    /* Gradient header banner */
    .main > div:first-child {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 0.5rem;
        border-radius: 0 0 16px 16px;
    }
    /* Title styling */
    h1 {
        background: linear-gradient(90deg, #f093fb, #f5576c, #fda085);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800 !important;
    }
    /* Section headers */
    h2, h3 {
        color: #7c3aed !important;
    }
    /* Metric cards */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #1e1e2f, #2d2b55);
        border: 1px solid #7c3aed;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 15px rgba(124, 58, 237, 0.3);
    }
    div[data-testid="stMetric"] label {
        color: #a78bfa !important;
        font-weight: 600;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #f1f5f9 !important;
        font-size: 1.5rem !important;
    }
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    section[data-testid="stSidebar"] h2 {
        color: #e2e8f0 !important;
    }
    /* Dataframe container */
    div[data-testid="stDataFrame"] {
        border: 2px solid #6366f1;
        border-radius: 12px;
        overflow: hidden;
    }
    /* Search input */
    div[data-testid="stTextInput"] input {
        border: 2px solid #8b5cf6 !important;
        border-radius: 8px !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #f472b6 !important;
        box-shadow: 0 0 10px rgba(244, 114, 182, 0.4) !important;
    }
    /* Divider lines */
    hr {
        border-color: #6366f1 !important;
    }
    </style>
    """, unsafe_allow_html=True)


def main():
    st.set_page_config(
        page_title="Polymarket Dashboard",
        page_icon="<icon>",
        layout="wide",
    )
    inject_custom_css()

    st.title("Polymarket Active Markets Dashboard")
    st.caption("Real-time prediction market data from the Gamma API")
    st.divider()

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

    # --- Summary metric cards ------------------------------------------------
    total_volume = df["volume_usd"].sum()
    total_liquidity = df["liquidity_usd"].sum()
    avg_yes = df["yes_probability"].mean()
    avg_no = df["no_probability"].mean()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Markets Loaded", f"{len(df)}")
    m2.metric("Total Volume", f"${total_volume:,.0f}")
    m3.metric("Total Liquidity", f"${total_liquidity:,.0f}")
    m4.metric("Avg YES Prob", f"{avg_yes:.1f}%" if pd.notna(avg_yes) else "N/A")
    m5.metric("Avg NO Prob", f"{avg_no:.1f}%" if pd.notna(avg_no) else "N/A")

    st.divider()

    # --- Search / filter -----------------------------------------------------
    search = st.text_input("Search markets by keyword")
    if search:
        mask = df["question"].str.contains(search, case=False, na=False)
        df = df[mask]
        st.info(f"{len(df)} markets match '{search}'")

    # --- Data table ----------------------------------------------------------
    st.subheader("Market Data")
    display_df = df[["question", "yes_probability", "no_probability", "volume_usd", "liquidity_usd", "end_date"]].copy()
    display_df.columns = ["Question", "YES Prob (%)", "NO Prob (%)", "Volume (USD)", "Liquidity (USD)", "End Date"]
    st.dataframe(display_df, use_container_width=True, height=400)

    st.divider()

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

    st.divider()

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

    # --- Footer --------------------------------------------------------------
    st.divider()
    st.markdown(
        "<div style='text-align:center; color:#94a3b8; padding:1rem;'>"
        "Polymarket Dashboard &mdash; Powered by the Gamma API"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
