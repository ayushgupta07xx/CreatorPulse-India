with src as (
    select * from {{ source('staging', 'channel_metrics_daily') }}
),

deduped as (
    select
        *,
        row_number() over (
            partition by channel_id, metric_date
            order by captured_at desc
        ) as rn
    from src
)

select
    channel_id,
    metric_date,
    subscriber_count,
    view_count,
    video_count,
    captured_at
from deduped
where rn = 1
