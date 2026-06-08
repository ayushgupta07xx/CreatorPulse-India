with v as (
    select * from {{ ref('stg_videos') }}
)

select
    video_id,
    channel_id,
    published_at,
    duration_seconds,
    view_count,
    like_count,
    comment_count,
    case
        when view_count > 0
            then (like_count + comment_count)::numeric / view_count
    end as engagement_rate,
    case
        when view_count > 0
            then like_count::numeric / view_count
    end as like_rate,
    case
        when view_count > 0
            then comment_count::numeric / view_count
    end as comment_rate,
    case
        when like_count > 0
            then comment_count::numeric / like_count
    end as comment_to_like_ratio
from v
