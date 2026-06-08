with n as (
    select * from {{ ref('int_niche_metrics') }}
),

recent as (
    select
        coalesce(c.niche, 'unclassified') as niche,
        sum(r.videos_last_90d) as niche_videos_last_90d,
        avg(r.mean_engagement_rate_last_90d) as niche_mean_engagement_last_90d
    from {{ ref('int_video_recent_window') }} as r
    inner join {{ ref('stg_channels') }} as c on r.channel_id = c.channel_id
    group by coalesce(c.niche, 'unclassified')
)

select
    n.niche,
    n.channel_count,
    n.total_subscribers,
    n.mean_subscribers,
    n.mean_channel_engagement_rate,
    n.total_videos_observed,
    recent.niche_videos_last_90d,
    recent.niche_mean_engagement_last_90d,
    case
        when n.channel_count > 0
            then n.total_subscribers::numeric / n.channel_count
    end as subscribers_per_channel
from n
left join recent on n.niche = recent.niche
