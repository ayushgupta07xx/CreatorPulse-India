select
    niche,
    {{ dbt_utils.generate_surrogate_key(['niche']) }} as niche_key,
    channel_count,
    total_subscribers,
    mean_subscribers,
    mean_channel_engagement_rate,
    total_videos_observed
from {{ ref('int_niche_metrics') }}
