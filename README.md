# CreatorPulse India

**The Creator Economy Intelligence Platform.** Track Indian YouTube creators' growth, screen for engagement quality, and match creators to brand briefs — built entirely on the official YouTube Data API v3.

> Status: early build. Live app, demo video, and dashboards land here as they ship.

## What it does

- **Creators** — see your channel's growth curve with a 12-week forecast, your niche archetype, an engagement-quality score, and how you stack up against peers.
- **Brands** — describe a campaign brief and budget, get a ranked shortlist of vetted creators with engagement-quality screening applied before you ever reach out.

## Stack

Python 3.11 - YouTube Data API v3 - PostgreSQL + pgvector - Airflow - dbt - XGBoost / scikit-learn / sentence-transformers / Prophet - Streamlit - PostHog - Power BI - Docker.

## Quickstart

```bash
cp .env.example .env          # add YOUTUBE_API_KEY
make install                  # .venv + pip install -e ".[dev]"
make up                       # postgres (pgvector) on :5436
make seed                     # resolve + validate seed channels via the API
```

## About / Built by

CreatorPulse India is designed and built by **Ayush Gupta**.
GitHub: https://github.com/ayushgupta07xx · LinkedIn: https://www.linkedin.com/in/ayush-gupta-544a803a2

## License

Code under Apache 2.0 (see `LICENSE`). Business documents under CC-BY-SA 4.0. See `LEGAL.md` for data-use terms.
