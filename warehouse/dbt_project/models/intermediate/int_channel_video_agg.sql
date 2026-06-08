with e as (
    select * from {{ ref('int_video_engagement') }}
)

select
    channel_id,
    count(*) as videos_observed,
    avg(view_count) as mean_views,
    percentile_cont(0.5) within group (order by view_count) as median_views,
    avg(engagement_rate) as mean_engagement_rate,
    percentile_cont(0.5) within group (order by engagement_rate) as median_engagement_rate,
    avg(like_rate) as mean_like_rate,
    avg(comment_rate) as mean_comment_rate,
    avg(comment_to_like_ratio) as mean_comment_to_like_ratio,
    avg(duration_seconds) as mean_duration_seconds
from e
group by channel_id
