with c as (
    select * from {{ ref('stg_channels') }}
),

latest_metric as (
    select distinct on (channel_id)
        channel_id,
        metric_date as latest_metric_date,
        subscriber_count as latest_subscriber_count,
        view_count as latest_view_count,
        video_count as latest_video_count
    from {{ ref('stg_channel_metrics_daily') }}
    order by channel_id, metric_date desc
),

last_upload as (
    select
        channel_id,
        max(published_at) as last_published_at
    from {{ ref('stg_videos') }}
    group by channel_id
)

select
    c.channel_id,
    c.title,
    c.custom_url,
    c.country,
    c.default_language,
    coalesce(c.niche, 'unclassified') as niche,
    c.published_at,
    coalesce(lm.latest_subscriber_count, c.subscriber_count) as subscriber_count,
    coalesce(lm.latest_view_count, c.view_count) as view_count,
    coalesce(lm.latest_video_count, c.video_count) as video_count,
    lm.latest_metric_date,
    lu.last_published_at,
    case
        when lu.last_published_at is not null
            then (current_date - lu.last_published_at::date)
    end as days_since_last_upload
from c
left join latest_metric as lm on c.channel_id = lm.channel_id
left join last_upload as lu on c.channel_id = lu.channel_id
