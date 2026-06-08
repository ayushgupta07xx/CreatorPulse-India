with v as (
    select
        channel_id,
        video_id,
        published_at
    from {{ ref('stg_videos') }}
    where published_at is not null
),

gaps as (
    select
        channel_id,
        published_at,
        (published_at - lag(published_at) over (
            partition by channel_id order by published_at
        )) as gap_interval
    from v
),

gap_days as (
    select
        channel_id,
        extract(epoch from gap_interval) / 86400.0 as gap_days
    from gaps
    where gap_interval is not null
)

select
    channel_id,
    count(*) as gap_observations,
    avg(gap_days) as mean_inter_video_days,
    stddev_samp(gap_days) as std_inter_video_days,
    min(gap_days) as min_inter_video_days,
    max(gap_days) as max_inter_video_days
from gap_days
group by channel_id
