# Architecture Decision Records

## ADR-0001 — PEP 621 pyproject + pip editable install (not poetry)
**Decision:** Use a PEP 621 `pyproject.toml` with the hatchling backend and `pip install -e ".[dev]"` for installs.
**Why:** Matches the standing local convention (`.venv` per project root, editable installs) used across the other repos, keeping tooling identical project-to-project. A PEP 621 file is still poetry-readable if needed later. Heavy ML/app/warehouse deps are isolated in optional-dependency groups so Day 1-2 installs stay light.

## ADR-0002 — PostHog Cloud, not self-hosted
**Decision:** Use PostHog Cloud free tier (1M events/month) for all product analytics; do not self-host PostHog in docker compose.
**Why:** Free tier covers portfolio-scale traffic comfortably, and self-hosting PostHog adds ~6 heavy containers with no benefit. Keeps the local stack to Postgres (+ optional Airflow).

## ADR-0003 — Remapped host ports to coexist with concurrent host projects
**Decision:** Publish Postgres on host `5436` and Airflow webserver on host `8088`.
**Why:** This host runs other projects concurrently (e.g. a kind/k8s cluster on `8080`, other Postgres instances on `5432-5435`). Remap our ports rather than freeing theirs; never reconfigure another project's containers.

## ADR-0004 — Pre-commit hooks pinned to the venv toolchain
**Decision:** Run ruff, ruff-format, mypy, and sqlfluff as `repo: local` / `language: system` hooks invoking the venv's installed tools; pin `ruff==0.6.9` in `[dev]` to match.
**Why:** A version gap between a pinned pre-commit rev and the venv's ruff makes the hook re-fix files on commit and abort, costing a re-stage every commit. Calling the venv tools directly keeps hook == local fixer.

## ADR-0005 — YouTube Data API v3 only for v1; Instagram is v2 future work
**Decision:** v1 ingests only via the official YouTube Data API v3. Instagram (and X, Twitch, etc.) are scoped out behind an abstract `CreatorSource` interface.
**Why:** YouTube has a free, documented API with predictable quotas. Instagram has no equivalent public API; the alternatives are TOS-restricted scraping or paid services. Scoping to YouTube keeps v1 legally clean and fully reproducible.

## ADR-0006 — Alembic owns the operational layer; dbt owns the dimensional marts

**Status:** Accepted (Day 2)

**Context:** Day 2 builds the Postgres schema; Day 4 builds the dbt warehouse. Both could plausibly manage the `staging.*` and `marts.*` tables, risking an ownership collision (dbt dropping or recreating tables the ingest pipeline writes to directly).

**Decision:** Alembic owns only the operational layer the Python pipeline writes to: `raw.youtube_channels` / `raw.youtube_videos` (append-only JSONB), the normalized `staging.channels` / `staging.channel_metrics_daily` / `staging.videos`, and `marts.channel_embeddings` (pgvector 384-dim, ML-written). dbt owns the dimensional marts (`dim_channel`, `dim_niche`, `dim_date`, `fact_channel_metrics_daily`, `fact_video`, `mart_*`), reading `staging.*` as sources. dbt never manages `channel_embeddings`.

**Consequences:** No dbt/Alembic collision. `marts` is shared but table names are disjoint. The SCD2 snapshot on `dim_channel` (Day 4) reads from `staging.channels`.

## ADR-0007 — Airflow ingest runs in an isolated venv on a custom image
**Status:** Accepted (Day 3)
**Context:** Airflow 2.9 pins SQLAlchemy 1.4; a full `pip install -e .` pulls SQLAlchemy 2.0 + Alembic (pgvector extra) and collides with Airflow's ORM.
**Decision:** Custom image (`docker/airflow/Dockerfile`) builds `/opt/ingest-venv` with only the slim ingest runtime. DAGs are pure BashOperators running `/opt/ingest-venv/bin/python -m apps.ingest.refresh …` against `apps/` mounted read-only at `/opt/airflow/project`. Airflow's env stays untouched.
**Consequences:** No ORM conflict; DAGs import only airflow+pendulum. Cost: ~2-min image build + a second venv.

## ADR-0008 — Host port remap for the Airflow webserver → 8089 (extends ADR-0003)
**Status:** Accepted (Day 3)
**Context:** Host 8080 = sentinelops; host 8088 = jobatlas-airflow-webserver. The Day-2 plan's 8088 mapping would fail to bind.
**Decision:** Publish CreatorPulse's webserver on host 8089 (`8089:8080`). Never free another project's port.

## ADR-0009 — Recurring ingest reads the universe from the DB; uploads playlist derived UC→UU
**Status:** Accepted (Day 3)
**Context:** `data/seed_channels.csv` is gitignored/host-only and `staging.channels` doesn't store the uploads playlist id.
**Decision:** `apps.ingest.refresh` selects the channel set from `staging.channels` (subs-ranked into tiers), decoupling the recurring path from the CSV. The uploads playlist id is derived as `UU`+channel_id[2:] (YouTube convention) — no schema change to fetch videos. `static_ingest` stays the CSV-seeded one-shot bootstrap.

## ADR-0010 — dbt warehouse schema layout & ownership materialization
**Status:** Accepted (Day 4)
**Context:** dbt builds the dimensional warehouse reading Alembic-owned `staging.*`
as sources (ADR-0006 split). It must materialize without colliding with or
dropping Alembic-owned tables (`raw.*`, `staging.*`, `marts.channel_embeddings`).

**Decision:**
- Override `generate_schema_name` to emit bare custom schema names (no
  target-schema prefix).
- staging → views in `staging_dbt`; intermediate → views in `intermediate`;
  marts → tables in `marts`; snapshot → `snapshots`.
- dbt NEVER writes `raw`/`staging`. `marts` is shared at the OBJECT level only:
  Alembic owns `marts.channel_embeddings`; dbt owns `dim_*/fact_*/mart_*`. dbt
  only creates/drops its own relations, so `channel_embeddings` is never touched.
- `dim_channel` is fed from the `snap_dim_channel` SCD2 snapshot (current rows),
  making the dimension genuinely SCD2-backed.

**Consequences:**
- Clean ownership boundary; no recreation collisions.
- Postgres-specific SQL in several models (`filter`, `distinct on`,
  `percentile_cont within group`, interval math, `to_char`) — must be
  target-gated IF the optional Day-13 BigQuery cycle runs (JobAtlas lesson).
- Actual model count is 21 on 3 source surfaces; the "40+" target was not
  architecturally reachable without padding — canonical/bullets reconciled to "20+".
