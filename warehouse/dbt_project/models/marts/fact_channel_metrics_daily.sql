with m as (
    select * from {{ ref('int_channel_metrics_history') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['channel_id', 'metric_date']) }} as metrics_key,
    channel_id,
    metric_date,
    cast(to_char(metric_date, 'YYYYMMDD') as integer) as date_key,
    subscriber_count,
    view_count,
    video_count,
    (subscriber_count - prev_subscriber_count) as subscriber_delta,
    (view_count - prev_view_count) as view_delta,
    days_since_prev
from m
