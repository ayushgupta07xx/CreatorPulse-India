"""initial schema: raw, staging, marts.channel_embeddings (pgvector 384-dim)

Revision ID: 0001
Revises:
Create Date: 2026-06-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 384  # BAAI/bge-small-en-v1.5


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS staging")
    op.execute("CREATE SCHEMA IF NOT EXISTS marts")

    op.create_table(
        "youtube_channels",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Text, nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        schema="raw",
    )
    op.create_index("ix_raw_channels_channel_id", "youtube_channels", ["channel_id"], schema="raw")
    op.create_index("ix_raw_channels_fetched_at", "youtube_channels", ["fetched_at"], schema="raw")

    op.create_table(
        "youtube_videos",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.Text, nullable=False),
        sa.Column("channel_id", sa.Text, nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        schema="raw",
    )
    op.create_index("ix_raw_videos_channel_id", "youtube_videos", ["channel_id"], schema="raw")
    op.create_index("ix_raw_videos_video_id", "youtube_videos", ["video_id"], schema="raw")

    op.create_table(
        "channels",
        sa.Column("channel_id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text),
        sa.Column("custom_url", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("default_language", sa.Text),
        sa.Column("niche", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("subscriber_count", sa.BigInteger),
        sa.Column("view_count", sa.BigInteger),
        sa.Column("video_count", sa.Integer),
        sa.Column("thumbnail_url", sa.Text),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="staging",
    )

    op.create_table(
        "channel_metrics_daily",
        sa.Column("channel_id", sa.Text, nullable=False),
        sa.Column("metric_date", sa.Date, nullable=False),
        sa.Column("subscriber_count", sa.BigInteger),
        sa.Column("view_count", sa.BigInteger),
        sa.Column("video_count", sa.Integer),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("channel_id", "metric_date", name="pk_channel_metrics_daily"),
        schema="staging",
    )

    op.create_table(
        "videos",
        sa.Column("video_id", sa.Text, primary_key=True),
        sa.Column("channel_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("view_count", sa.BigInteger),
        sa.Column("like_count", sa.BigInteger),
        sa.Column("comment_count", sa.BigInteger),
        sa.Column("duration_seconds", sa.Integer),
        sa.Column("tags", postgresql.JSONB),
        sa.Column("thumbnail_url", sa.Text),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="staging",
    )
    op.create_index("ix_staging_videos_channel_id", "videos", ["channel_id"], schema="staging")

    op.create_table(
        "channel_embeddings",
        sa.Column("channel_id", sa.Text, primary_key=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("model_name", sa.Text, nullable=False, server_default="BAAI/bge-small-en-v1.5"),
        sa.Column("source_text_hash", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="marts",
    )
    # HNSW cosine index. NOTE: query-time hnsw.ef_search defaults to 40 and
    # silently caps results regardless of LIMIT -- set it per session at query time.
    op.execute(
        "CREATE INDEX ix_marts_channel_embeddings_hnsw "
        "ON marts.channel_embeddings "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS marts.ix_marts_channel_embeddings_hnsw")
    op.drop_table("channel_embeddings", schema="marts")
    op.drop_index("ix_staging_videos_channel_id", table_name="videos", schema="staging")
    op.drop_table("videos", schema="staging")
    op.drop_table("channel_metrics_daily", schema="staging")
    op.drop_table("channels", schema="staging")
    op.drop_index("ix_raw_videos_video_id", table_name="youtube_videos", schema="raw")
    op.drop_index("ix_raw_videos_channel_id", table_name="youtube_videos", schema="raw")
    op.drop_table("youtube_videos", schema="raw")
    op.drop_index("ix_raw_channels_fetched_at", table_name="youtube_channels", schema="raw")
    op.drop_index("ix_raw_channels_channel_id", table_name="youtube_channels", schema="raw")
    op.drop_table("youtube_channels", schema="raw")
