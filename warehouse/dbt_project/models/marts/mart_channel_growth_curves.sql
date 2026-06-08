with h as (
    select * from {{ ref('int_channel_metrics_history') }}
),

base as (
    select
        channel_id,
        min(subscriber_count) as baseline_subscribers
    from h
    group by channel_id
)

select
    h.channel_id,
    h.metric_date,
    h.subscriber_count,
    h.view_count,
    (h.subscriber_count - h.prev_subscriber_count) as subscriber_delta,
    sum(h.subscriber_count - coalesce(h.prev_subscriber_count, h.subscriber_count))
        over (partition by h.channel_id order by h.metric_date)
        as cumulative_subscriber_growth,
    case
        when b.baseline_subscribers > 0
            then (h.subscriber_count - b.baseline_subscribers)::numeric / b.baseline_subscribers
    end as growth_index_vs_baseline
from h
left join base as b on h.channel_id = b.channel_id
