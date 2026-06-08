with metrics as (
    select * from {{ ref('stg_channel_metrics_daily') }}
)

select
    channel_id,
    metric_date,
    subscriber_count,
    view_count,
    video_count,
    captured_at,
    lag(subscriber_count) over w as prev_subscriber_count,
    lag(view_count) over w as prev_view_count,
    lag(video_count) over w as prev_video_count,
    lag(metric_date) over w as prev_metric_date,
    (metric_date - lag(metric_date) over w) as days_since_prev
from metrics
window w as (partition by channel_id order by metric_date)
