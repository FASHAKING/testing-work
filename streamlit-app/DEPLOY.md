# Polymarket Streamlit Dashboard - Deployment Guide

## Local Development

```bash
cd streamlit-app
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Deploy to Vercel

1. Push this directory to a GitHub repository.
2. Go to https://vercel.com and import the repository.
3. Set the **Root Directory** to `streamlit-app` if this lives inside a monorepo.
4. Vercel will detect `vercel.json` and install dependencies automatically.
5. Click **Deploy**.

> **Note:** Streamlit apps are long-running processes. Vercel's serverless
> functions have a 10-second timeout on the Hobby plan. For production use
> consider deploying to **Streamlit Community Cloud** (free) or a VPS with
> `streamlit run app.py --server.port $PORT`.

### Alternative: Streamlit Community Cloud (recommended)

1. Push to GitHub.
2. Go to https://share.streamlit.io and connect your repo.
3. Select `streamlit-app/app.py` as the main file.
4. Click **Deploy** - no extra config needed.
