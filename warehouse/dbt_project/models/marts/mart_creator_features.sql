with base as (select * from {{ ref('int_channel_base') }}),

vel as (select * from {{ ref('int_channel_growth_velocity') }}),

vid as (select * from {{ ref('int_channel_video_agg') }}),

dist as (select * from {{ ref('int_channel_engagement_distribution') }}),

cad as (select * from {{ ref('int_channel_cadence') }}),

rec as (select * from {{ ref('int_video_recent_window') }})

select
    base.channel_id,
    base.niche,
    base.country,
    base.subscriber_count,
    base.view_count,
    base.video_count,
    base.days_since_last_upload,

    -- growth-velocity features (fraud inputs; thin until the time series fills)
    vel.growth_observations,
    vel.mean_subscriber_delta_per_day,
    vel.std_subscriber_delta_per_day,
    vel.max_subscriber_spike,
    vel.mean_subscriber_growth_pct,
    vel.std_subscriber_growth_pct,

    -- engagement aggregates
    vid.videos_observed,
    vid.mean_views,
    vid.median_views,
    vid.mean_engagement_rate,
    vid.median_engagement_rate,
    vid.mean_like_rate,
    vid.mean_comment_rate,
    vid.mean_comment_to_like_ratio,
    vid.mean_duration_seconds,

    -- distribution / unevenness signals
    dist.engagement_cv,
    dist.mean_to_median_er_ratio,

    -- cadence
    cad.mean_inter_video_days,
    cad.std_inter_video_days,

    -- recency
    rec.videos_last_30d,
    rec.videos_last_90d,
    rec.mean_views_last_90d,
    rec.mean_engagement_rate_last_90d
from base
left join vel on base.channel_id = vel.channel_id
left join vid on base.channel_id = vid.channel_id
left join dist on base.channel_id = dist.channel_id
left join cad on base.channel_id = cad.channel_id
left join rec on base.channel_id = rec.channel_id
