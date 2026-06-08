with e as (
    select * from {{ ref('int_video_engagement') }}
)

select
    video_id,
    channel_id,
    cast(to_char(published_at, 'YYYYMMDD') as integer) as published_date_key,
    published_at,
    duration_seconds,
    view_count,
    like_count,
    comment_count,
    engagement_rate,
    like_rate,
    comment_rate,
    comment_to_like_ratio
from e
