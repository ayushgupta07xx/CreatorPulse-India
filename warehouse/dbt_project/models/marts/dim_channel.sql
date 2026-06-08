with snap as (
    select * from {{ ref('snap_dim_channel') }}
    where dbt_valid_to is null
),

base as (
    select * from {{ ref('int_channel_base') }}
)

select
    snap.channel_id,
    snap.title,
    snap.custom_url,
    snap.country,
    base.default_language,
    snap.niche,
    base.published_at,
    snap.subscriber_count,
    snap.view_count,
    snap.video_count,
    base.latest_metric_date,
    base.last_published_at,
    base.days_since_last_upload,
    snap.dbt_valid_from as effective_from
from snap
left join base on snap.channel_id = base.channel_id
