with g as (
    select * from {{ ref('int_channel_growth_daily') }}
)

select
    channel_id,
    count(subscriber_delta) as growth_observations,
    avg(subscriber_delta_per_day) as mean_subscriber_delta_per_day,
    stddev_samp(subscriber_delta_per_day) as std_subscriber_delta_per_day,
    max(subscriber_delta) as max_subscriber_spike,
    avg(subscriber_growth_pct) as mean_subscriber_growth_pct,
    stddev_samp(subscriber_growth_pct) as std_subscriber_growth_pct
from g
group by channel_id
