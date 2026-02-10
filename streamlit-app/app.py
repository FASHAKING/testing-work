"""
Polymarket Data Dashboard - Streamlit Web App
==============================================
Fetches active prediction markets from the Polymarket Gamma API,
displays them in a searchable table, and charts the top markets
by volume and probability.

Gamma API docs: https://docs.polymarket.com/developers/gamma-markets-api/overview
"""

import json
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import streamlit as st
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DEFAULT_LIMIT = 50

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
        outcome_prices = m.get("outcomePrices", "")
        yes_prob = None
        no_prob = None
        if outcome_prices:
            try:
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                if isinstance(prices, list):
                    if len(prices) > 0:
                        yes_prob = parse_probability(prices[0])
                    if len(prices) > 1:
                        no_prob = parse_probability(prices[1])
            except Exception:
                pass

        if yes_prob is None:
            yes_prob = parse_probability(m.get("bestAsk") or m.get("outcomePrices"))

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

    return pd.DataFrame(rows)


def safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def detect_suspicious_markets(df: pd.DataFrame) -> list[dict]:
    """
    Detect markets with suspicious or unusual activity patterns.
    Flags:
      - Extreme volume/liquidity ratio (whale dumping or thin book manipulation)
      - Very high volume + extreme probability (possible insider / coordinated move)
      - Statistical outlier volume (>2 std devs above mean)
      - Near-certain markets with unusual liquidity (exit scam setup)
    """
    alerts = []
    if len(df) < 3:
        return alerts

    vol_mean = df["volume_usd"].mean()
    vol_std = df["volume_usd"].std()
    liq_mean = df["liquidity_usd"].mean()

    for _, row in df.iterrows():
        vol = row["volume_usd"]
        liq = row["liquidity_usd"]
        yes = row["yes_probability"] if pd.notna(row["yes_probability"]) else 50
        no = row["no_probability"] if pd.notna(row["no_probability"]) else 50
        q = row["question"]
        ratio = vol / liq if liq > 0 else 0

        base = {
            "question": q,
            "volume": vol,
            "liquidity": liq,
            "yes": yes,
            "no": no,
            "ratio": f"{ratio:.1f}x",
        }

        # CRITICAL: Extreme volume/liquidity ratio with significant volume
        if ratio > 50 and vol > vol_mean:
            alerts.append({
                **base,
                "severity": "critical",
                "flag": "Extreme Vol/Liq Ratio",
                "stat": f"{ratio:.0f}x ratio \u2014 possible thin-book manipulation",
            })
        # HIGH: Statistical outlier volume (>2 std devs)
        elif vol_std > 0 and vol > vol_mean + 2 * vol_std:
            alerts.append({
                **base,
                "severity": "high",
                "flag": "Volume Outlier",
                "stat": f"{((vol - vol_mean) / vol_std):.1f} std devs above mean",
            })
        # HIGH: Big money on near-certain outcome
        elif vol > vol_mean * 1.5 and (yes > 95 or yes < 5):
            alerts.append({
                **base,
                "severity": "high",
                "flag": "Large Position on Extreme Odds",
                "stat": f"{'YES' if yes > 95 else 'NO'} at {max(yes, no):.1f}% with ${vol:,.0f} volume",
            })
        # MEDIUM: High volume/liquidity ratio
        elif ratio > 20 and vol > vol_mean * 0.5:
            alerts.append({
                **base,
                "severity": "medium",
                "flag": "Elevated Vol/Liq Ratio",
                "stat": f"{ratio:.0f}x ratio \u2014 volume outpacing available liquidity",
            })
        # MEDIUM: Very low liquidity but non-trivial volume
        elif liq > 0 and liq < liq_mean * 0.1 and vol > vol_mean * 0.5:
            alerts.append({
                **base,
                "severity": "medium",
                "flag": "Thin Liquidity with Active Trading",
                "stat": f"Only ${liq:,.0f} liquidity vs ${vol:,.0f} volume",
            })

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))

    return alerts[:15]  # Cap at 15 alerts


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
    ax.title.set_fontsize(14)
    ax.title.set_fontweight("bold")
    for spine in ax.spines.values():
        spine.set_color("#3b3b5c")
    ax.grid(axis="x", color="#3b3b5c", linestyle="--", alpha=0.4)


def plot_top_by_volume(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Horizontal bar chart of top-N markets by trading volume."""
    top = df.nlargest(n, "volume_usd").sort_values("volume_usd")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.55)))
    cmap = plt.cm.plasma
    colors = [cmap(0.2 + 0.6 * i / max(n - 1, 1)) for i in range(len(top))]
    bars = ax.barh(range(len(top)), top["volume_usd"], color=colors, edgecolor="#1e1b4b", linewidth=0.5)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels([_wrap(q, 45) for q in top["question"]], fontsize=8)
    ax.set_xlabel("Volume (USD)")
    ax.set_title(f"Top {n} Markets by Volume")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    # Value labels on bars
    for bar, val in zip(bars, top["volume_usd"]):
        ax.text(bar.get_width() + bar.get_width() * 0.01, bar.get_y() + bar.get_height() / 2,
                f"${val:,.0f}", va="center", ha="left", color="#e2e8f0", fontsize=7)
    _apply_chart_style(fig, ax)
    fig.tight_layout()
    return fig


def plot_top_by_probability(df: pd.DataFrame, n: int = 10) -> plt.Figure:
    """Grouped horizontal bar chart of top-N markets by YES and NO probability."""
    valid = df.dropna(subset=["yes_probability"])
    top = valid.nlargest(n, "yes_probability").sort_values("yes_probability")
    fig, ax = plt.subplots(figsize=(10, max(4, n * 0.65)))
    labels = [_wrap(q, 45) for q in top["question"]]
    y_pos = np.arange(len(labels))
    bar_height = 0.35
    bars_yes = ax.barh(y_pos + bar_height / 2, top["yes_probability"], bar_height,
                       label="YES", color="#34d399", edgecolor="#065f46", linewidth=0.5)
    bars_no = ax.barh(y_pos - bar_height / 2, top["no_probability"].fillna(0), bar_height,
                      label="NO", color="#fb7185", edgecolor="#881337", linewidth=0.5)
    # Value labels
    for bar, val in zip(bars_yes, top["yes_probability"]):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", ha="left", color="#34d399", fontsize=7, fontweight="bold")
    for bar, val in zip(bars_no, top["no_probability"].fillna(0)):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", va="center", ha="left", color="#fb7185", fontsize=7, fontweight="bold")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Probability (%)")
    ax.set_title(f"Top {n} Markets \u2014 YES vs NO")
    ax.set_xlim(0, 115)
    ax.legend(loc="lower right", facecolor="#1e1b4b", edgecolor="#7c3aed",
              labelcolor="#f1f5f9", fontsize=9)
    _apply_chart_style(fig, ax)
    fig.tight_layout()
    return fig


def plot_volume_donut(df: pd.DataFrame, n: int = 8) -> plt.Figure:
    """Donut chart of volume distribution across top markets."""
    top = df.nlargest(n, "volume_usd")
    other_vol = df["volume_usd"].sum() - top["volume_usd"].sum()
    labels = [_wrap(q, 30) for q in top["question"]]
    sizes = list(top["volume_usd"])
    if other_vol > 0:
        labels.append("Others")
        sizes.append(other_vol)
    cmap = plt.cm.cool
    colors = [cmap(i / len(sizes)) for i in range(len(sizes))]
    fig, ax = plt.subplots(figsize=(8, 8))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct="%1.1f%%", startangle=140,
        colors=colors, pctdistance=0.8,
        wedgeprops=dict(width=0.45, edgecolor="#0e1117", linewidth=2),
    )
    for t in autotexts:
        t.set_color("#f1f5f9")
        t.set_fontsize(9)
        t.set_fontweight("bold")
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(-0.35, 0.5),
              fontsize=7, facecolor="#0e1117", edgecolor="#3b3b5c", labelcolor="#c4b5fd")
    ax.set_title("Volume Distribution", color="#f1f5f9", fontsize=14, fontweight="bold")
    fig.patch.set_facecolor("#0e1117")
    fig.tight_layout()
    return fig


def plot_liquidity_vs_volume(df: pd.DataFrame) -> plt.Figure:
    """Scatter plot: liquidity vs volume, sized by YES probability."""
    valid = df.dropna(subset=["yes_probability"])
    fig, ax = plt.subplots(figsize=(10, 6))
    sizes = valid["yes_probability"].fillna(50) * 3
    scatter = ax.scatter(
        valid["volume_usd"], valid["liquidity_usd"],
        c=valid["yes_probability"], cmap="RdYlGn", s=sizes,
        alpha=0.75, edgecolors="#1e1b4b", linewidth=0.5,
    )
    cbar = fig.colorbar(scatter, ax=ax, pad=0.02)
    cbar.set_label("YES Prob (%)", color="#c4b5fd")
    cbar.ax.yaxis.set_tick_params(color="#c4b5fd")
    plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="#c4b5fd")
    ax.set_xlabel("Volume (USD)")
    ax.set_ylabel("Liquidity (USD)")
    ax.set_title("Liquidity vs Volume (bubble size = YES probability)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    _apply_chart_style(fig, ax)
    ax.grid(axis="both", color="#3b3b5c", linestyle="--", alpha=0.3)
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
# UI Components
# ---------------------------------------------------------------------------

def render_spotlight_card(title: str, question: str, value: str, color: str, bg: str):
    """Render a bold spotlight card with HTML."""
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {bg}, #0e1117);
        border-left: 5px solid {color};
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    ">
        <div style="color: {color}; font-size: 0.8rem; font-weight: 700; text-transform: uppercase;
                    letter-spacing: 1px; margin-bottom: 6px;">
            {title}
        </div>
        <div style="color: #f1f5f9; font-size: 1rem; font-weight: 600; margin-bottom: 8px;">
            {question[:80]}{'...' if len(question) > 80 else ''}
        </div>
        <div style="color: {color}; font-size: 1.8rem; font-weight: 800;">
            {value}
        </div>
    </div>
    """, unsafe_allow_html=True)


def render_prob_bar(yes: float, no: float) -> str:
    """Return an HTML inline probability bar."""
    yes_w = max(yes, 0)
    no_w = max(no, 0)
    return f"""
    <div style="display:flex; border-radius:6px; overflow:hidden; height:22px; width:100%;
                background:#1e1b4b; box-shadow: inset 0 1px 3px rgba(0,0,0,0.4);">
        <div style="width:{yes_w}%; background: linear-gradient(90deg, #059669, #34d399);
                    display:flex; align-items:center; justify-content:center;
                    color:#fff; font-size:11px; font-weight:700;">{yes_w:.0f}%</div>
        <div style="width:{no_w}%; background: linear-gradient(90deg, #fb7185, #e11d48);
                    display:flex; align-items:center; justify-content:center;
                    color:#fff; font-size:11px; font-weight:700;">{no_w:.0f}%</div>
    </div>
    """


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

def inject_custom_css():
    """Inject custom CSS for a vibrant, colorful dashboard."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
    /* Global font */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    /* Gradient header banner */
    .main > div:first-child {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 0.5rem;
        border-radius: 0 0 16px 16px;
    }
    /* Title styling */
    h1 {
        background: linear-gradient(90deg, #f093fb, #f5576c, #fda085, #f5af19);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900 !important;
        font-size: 2.5rem !important;
    }
    /* Section headers */
    h2 {
        color: #a78bfa !important;
        font-weight: 800 !important;
        border-bottom: 2px solid #6366f1;
        padding-bottom: 6px;
    }
    h3 {
        color: #818cf8 !important;
        font-weight: 700 !important;
    }
    /* Metric cards */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #1e1e2f, #2d2b55);
        border: 1px solid #7c3aed;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 15px rgba(124, 58, 237, 0.3);
        transition: transform 0.2s, box-shadow 0.2s;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(124, 58, 237, 0.5);
    }
    div[data-testid="stMetric"] label {
        color: #a78bfa !important;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        font-size: 0.75rem !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #f1f5f9 !important;
        font-size: 1.6rem !important;
        font-weight: 800 !important;
    }
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {
        color: #e2e8f0 !important;
        border-bottom: none;
    }
    /* Dataframe container */
    div[data-testid="stDataFrame"] {
        border: 2px solid #6366f1;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.2);
    }
    /* Search input */
    div[data-testid="stTextInput"] input {
        border: 2px solid #8b5cf6 !important;
        border-radius: 8px !important;
        font-weight: 600;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #f472b6 !important;
        box-shadow: 0 0 15px rgba(244, 114, 182, 0.5) !important;
    }
    /* Tabs */
    button[data-baseweb="tab"] {
        font-weight: 700 !important;
    }
    /* Divider lines */
    hr {
        border-image: linear-gradient(90deg, #6366f1, #a855f7, #ec4899) 1 !important;
    }
    /* Expander */
    details {
        border: 1px solid #6366f1 !important;
        border-radius: 8px !important;
    }
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(
        page_title="Polymarket Dashboard",
        page_icon="\U0001f4ca",
        layout="wide",
    )
    inject_custom_css()

    # --- Header ---------------------------------------------------------------
    st.title("Polymarket Active Markets Dashboard")
    st.caption(f"Real-time prediction market data \u2022 Last refreshed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    st.divider()

    # --- Sidebar --------------------------------------------------------------
    st.sidebar.markdown(
        "<h2 style='text-align:center;'>\U0001f3af Polymarket</h2>",
        unsafe_allow_html=True,
    )
    st.sidebar.divider()
    st.sidebar.subheader("Controls")
    market_count = st.sidebar.slider("Markets to fetch", 10, 200, 50, step=10)
    chart_count = st.sidebar.slider("Top-N for charts", 5, 30, 10, step=5)
    auto_refresh = st.sidebar.checkbox("Auto-refresh (60s)", value=False)
    if st.sidebar.button("Refresh Now", use_container_width=True):
        st.rerun()

    if auto_refresh:
        import time
        time.sleep(60)
        st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown(
        "<div style='text-align:center; padding: 0.5rem;'>"
        "<span style='color:#64748b; font-size:0.75rem;'>Powered by Gamma API</span><br>"
        "<span style='color:#64748b; font-size:0.75rem;'>Built with Streamlit</span><br><br>"
        "<a href='https://x.com/FASHAKING3' target='_blank' style='text-decoration:none;'>"
        "<span style='background: linear-gradient(90deg, #f093fb, #f5576c, #fda085); "
        "-webkit-background-clip: text; -webkit-text-fill-color: transparent; "
        "font-weight: 900; font-size: 0.95rem; letter-spacing: 0.5px;'>"
        "Built by fashaking</span></a>"
        "</div>",
        unsafe_allow_html=True,
    )

    # --- Fetch data -----------------------------------------------------------
    with st.spinner("Fetching markets from Gamma API..."):
        raw_markets = fetch_markets(limit=market_count)

    if not raw_markets:
        st.warning("No markets returned. The API may be temporarily unavailable.")
        return

    df = markets_to_dataframe(raw_markets)

    # --- Summary metric cards -------------------------------------------------
    total_volume = df["volume_usd"].sum()
    total_liquidity = df["liquidity_usd"].sum()
    avg_yes = df["yes_probability"].mean()
    avg_no = df["no_probability"].mean()
    max_vol_market = df.loc[df["volume_usd"].idxmax()] if len(df) > 0 else None

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Markets", f"{len(df)}")
    m2.metric("Total Volume", f"${total_volume:,.0f}")
    m3.metric("Total Liquidity", f"${total_liquidity:,.0f}")
    m4.metric("Avg YES", f"{avg_yes:.1f}%" if pd.notna(avg_yes) else "N/A")
    m5.metric("Avg NO", f"{avg_no:.1f}%" if pd.notna(avg_no) else "N/A")

    st.divider()

    # --- Spotlight cards (top movers) -----------------------------------------
    st.subheader("Market Spotlight")
    valid_df = df.dropna(subset=["yes_probability"])

    if len(valid_df) > 0:
        s1, s2, s3, s4 = st.columns(4)
        # Highest YES
        top_yes = valid_df.loc[valid_df["yes_probability"].idxmax()]
        with s1:
            render_spotlight_card(
                "Highest YES", top_yes["question"],
                f"{top_yes['yes_probability']:.1f}%", "#34d399", "#052e16"
            )
        # Highest NO
        top_no = valid_df.loc[valid_df["no_probability"].idxmax()] if "no_probability" in valid_df else None
        with s2:
            if top_no is not None:
                render_spotlight_card(
                    "Highest NO", top_no["question"],
                    f"{top_no['no_probability']:.1f}%", "#fb7185", "#4c0519"
                )
        # Most contested (closest to 50/50)
        valid_df_copy = valid_df.copy()
        valid_df_copy["_dist50"] = (valid_df_copy["yes_probability"] - 50).abs()
        most_contested = valid_df_copy.loc[valid_df_copy["_dist50"].idxmin()]
        with s3:
            render_spotlight_card(
                "Most Contested", most_contested["question"],
                f"{most_contested['yes_probability']:.1f}% / {most_contested['no_probability']:.1f}%",
                "#fbbf24", "#451a03"
            )
        # Highest volume
        top_vol = df.loc[df["volume_usd"].idxmax()]
        with s4:
            render_spotlight_card(
                "Highest Volume", top_vol["question"],
                f"${top_vol['volume_usd']:,.0f}", "#818cf8", "#1e1b4b"
            )

    st.divider()

    # --- Search / filter ------------------------------------------------------
    search = st.text_input("Search markets by keyword", placeholder="e.g. Bitcoin, election, AI...")
    if search:
        mask = df["question"].str.contains(search, case=False, na=False)
        df = df[mask]
        st.info(f"{len(df)} markets match '{search}'")

    # --- Data table with probability bars -------------------------------------
    st.subheader("Market Data")

    tab_table, tab_visual = st.tabs(["Data Table", "Visual Probabilities"])

    with tab_table:
        display_df = df[["question", "yes_probability", "no_probability", "volume_usd", "liquidity_usd", "end_date"]].copy()
        display_df.columns = ["Question", "YES Prob (%)", "NO Prob (%)", "Volume (USD)", "Liquidity (USD)", "End Date"]
        st.dataframe(
            display_df.style.background_gradient(subset=["YES Prob (%)"], cmap="Greens")
                           .background_gradient(subset=["NO Prob (%)"], cmap="Reds")
                           .background_gradient(subset=["Volume (USD)"], cmap="Purples")
                           .format({"YES Prob (%)": "{:.1f}", "NO Prob (%)": "{:.1f}",
                                    "Volume (USD)": "${:,.0f}", "Liquidity (USD)": "${:,.0f}"}),
            use_container_width=True,
            height=450,
        )

    with tab_visual:
        st.markdown("**YES vs NO probability for each market:**")
        for _, row in df.head(25).iterrows():
            yes_val = row["yes_probability"] if pd.notna(row["yes_probability"]) else 0
            no_val = row["no_probability"] if pd.notna(row["no_probability"]) else 0
            q = row["question"][:80] + ("..." if len(row["question"]) > 80 else "")
            st.markdown(
                f"<div style='margin-bottom:4px;'>"
                f"<span style='color:#e2e8f0; font-size:0.85rem; font-weight:600;'>{q}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.markdown(render_prob_bar(yes_val, no_val), unsafe_allow_html=True)
            st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)

    st.divider()

    # --- Charts ---------------------------------------------------------------
    st.subheader("Charts")
    chart_tab1, chart_tab2, chart_tab3, chart_tab4 = st.tabs([
        "Volume Ranking", "YES vs NO", "Volume Distribution", "Liquidity vs Volume"
    ])

    with chart_tab1:
        fig_vol = plot_top_by_volume(df, n=chart_count)
        st.pyplot(fig_vol)
        plt.close(fig_vol)

    with chart_tab2:
        fig_prob = plot_top_by_probability(df, n=chart_count)
        st.pyplot(fig_prob)
        plt.close(fig_prob)

    with chart_tab3:
        fig_donut = plot_volume_donut(df, n=chart_count)
        st.pyplot(fig_donut)
        plt.close(fig_donut)

    with chart_tab4:
        fig_scatter = plot_liquidity_vs_volume(df)
        st.pyplot(fig_scatter)
        plt.close(fig_scatter)

    st.divider()

    # --- Whale Alert / Suspicious Activity ------------------------------------
    st.subheader("Whale Alert \u2014 Suspicious Activity Detector")
    st.markdown(
        "<span style='color:#94a3b8; font-size:0.85rem;'>"
        "Flagging markets with unusual patterns: massive volume relative to liquidity, "
        "extreme probabilities with big money, and statistical outliers.</span>",
        unsafe_allow_html=True,
    )

    alerts = detect_suspicious_markets(df)

    if alerts:
        for alert in alerts:
            severity_colors = {
                "critical": ("#ff0040", "#4a0011", "\u26a0\ufe0f CRITICAL"),
                "high": ("#f97316", "#431407", "\U0001f6a8 HIGH"),
                "medium": ("#fbbf24", "#451a03", "\u26a1 MEDIUM"),
            }
            color, bg, label = severity_colors.get(alert["severity"], ("#fbbf24", "#451a03", "\u26a1"))
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {bg}, #0e1117);
                border: 1px solid {color};
                border-left: 5px solid {color};
                border-radius: 10px;
                padding: 16px 20px;
                margin-bottom: 12px;
                box-shadow: 0 0 20px {color}33;
            ">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="color:{color}; font-weight:800; font-size:0.8rem;
                                 letter-spacing:1px; text-transform:uppercase;">
                        {label} &mdash; {alert['flag']}
                    </span>
                    <span style="color:#64748b; font-size:0.75rem;">{alert.get('stat', '')}</span>
                </div>
                <div style="color:#f1f5f9; font-weight:600; font-size:0.95rem; margin-bottom:6px;">
                    {alert['question'][:90]}{'...' if len(alert['question']) > 90 else ''}
                </div>
                <div style="display:flex; gap:20px; flex-wrap:wrap;">
                    <span style="color:#a78bfa; font-size:0.8rem;">
                        Volume: <b style="color:#f1f5f9;">${alert['volume']:,.0f}</b>
                    </span>
                    <span style="color:#a78bfa; font-size:0.8rem;">
                        Liquidity: <b style="color:#f1f5f9;">${alert['liquidity']:,.0f}</b>
                    </span>
                    <span style="color:#a78bfa; font-size:0.8rem;">
                        YES: <b style="color:#34d399;">{alert['yes']:.1f}%</b>
                    </span>
                    <span style="color:#a78bfa; font-size:0.8rem;">
                        NO: <b style="color:#fb7185;">{alert['no']:.1f}%</b>
                    </span>
                    <span style="color:#a78bfa; font-size:0.8rem;">
                        Vol/Liq Ratio: <b style="color:#fbbf24;">{alert.get('ratio', 'N/A')}</b>
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown(
            "<div style='text-align:center; padding:2rem; color:#64748b;'>"
            "No suspicious activity detected in current dataset.</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Single market detail -------------------------------------------------
    st.subheader("Market Detail Lookup")
    market_id_input = st.text_input(
        "Enter a market ID (condition ID or slug) to fetch details",
        placeholder="Paste a market ID here...",
    )
    if market_id_input:
        with st.spinner("Fetching details..."):
            details = fetch_market_details(market_id_input.strip())
        if details:
            with st.expander("Raw JSON Response", expanded=True):
                st.json(details)
        else:
            st.warning("No data returned for that ID.")

    # --- Footer ---------------------------------------------------------------
    st.divider()
    st.markdown(
        "<div style='text-align:center; padding:1.5rem;'>"
        "<span style='background: linear-gradient(90deg, #f093fb, #f5576c, #fda085); "
        "-webkit-background-clip: text; -webkit-text-fill-color: transparent; "
        "font-weight: 800; font-size: 1.3rem;'>"
        "Polymarket Dashboard</span>"
        "<br><span style='color:#64748b; font-size: 0.8rem;'>"
        "Powered by the Gamma API &bull; Data updates on every refresh"
        "</span>"
        "<br><br>"
        "<a href='https://x.com/FASHAKING3' target='_blank' style='text-decoration:none;'>"
        "<span style='background: linear-gradient(90deg, #667eea, #764ba2, #f093fb); "
        "-webkit-background-clip: text; -webkit-text-fill-color: transparent; "
        "font-weight: 900; font-size: 1.1rem; letter-spacing: 1px;'>"
        "Built by fashaking</span></a>"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
