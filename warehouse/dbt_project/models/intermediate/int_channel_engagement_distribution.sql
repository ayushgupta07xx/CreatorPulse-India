with e as (
    select * from {{ ref('int_video_engagement') }}
),

agg as (
    select
        channel_id,
        avg(engagement_rate) as mean_er,
        percentile_cont(0.5) within group (order by engagement_rate) as median_er,
        stddev_samp(engagement_rate) as std_er,
        count(engagement_rate) as n_er
    from e
    group by channel_id
)

select
    channel_id,
    mean_er,
    median_er,
    std_er,
    n_er,
    case when mean_er > 0 then std_er / mean_er end as engagement_cv,
    case when median_er > 0 then mean_er / median_er end as mean_to_median_er_ratio
from agg
