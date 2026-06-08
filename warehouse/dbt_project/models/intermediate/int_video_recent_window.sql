with e as (
    select * from {{ ref('int_video_engagement') }}
)

select
    channel_id,
    count(*) filter (where published_at >= current_date - interval '90 days')
        as videos_last_90d,
    count(*) filter (where published_at >= current_date - interval '30 days')
        as videos_last_30d,
    avg(view_count) filter (where published_at >= current_date - interval '90 days')
        as mean_views_last_90d,
    avg(engagement_rate) filter (where published_at >= current_date - interval '90 days')
        as mean_engagement_rate_last_90d
from e
group by channel_id
