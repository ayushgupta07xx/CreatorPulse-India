with hist as (
    select * from {{ ref('int_channel_metrics_history') }}
)

select
    channel_id,
    metric_date,
    days_since_prev,
    subscriber_count,
    (subscriber_count - prev_subscriber_count) as subscriber_delta,
    (view_count - prev_view_count) as view_delta,
    (video_count - prev_video_count) as video_delta,
    case
        when days_since_prev is null or days_since_prev = 0 then null
        else (subscriber_count - prev_subscriber_count)::numeric / days_since_prev
    end as subscriber_delta_per_day,
    case
        when prev_subscriber_count is null or prev_subscriber_count = 0 then null
        else (subscriber_count - prev_subscriber_count)::numeric / prev_subscriber_count
    end as subscriber_growth_pct
from hist
