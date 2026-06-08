with c as (
    select * from {{ ref('stg_channels') }}
),

agg as (
    select * from {{ ref('int_channel_video_agg') }}
)

select
    coalesce(c.niche, 'unclassified') as niche,
    count(distinct c.channel_id) as channel_count,
    sum(c.subscriber_count) as total_subscribers,
    avg(c.subscriber_count) as mean_subscribers,
    avg(agg.mean_engagement_rate) as mean_channel_engagement_rate,
    sum(agg.videos_observed) as total_videos_observed
from c
left join agg on c.channel_id = agg.channel_id
group by coalesce(c.niche, 'unclassified')
