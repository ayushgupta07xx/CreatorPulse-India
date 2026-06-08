with src as (
    select * from {{ source('staging', 'channels') }}
)

select
    channel_id,
    title,
    nullif(trim(custom_url), '') as custom_url,
    description,
    upper(nullif(trim(country), '')) as country,
    lower(nullif(trim(default_language), '')) as default_language,
    nullif(trim(niche), '') as niche,
    published_at,
    subscriber_count,
    view_count,
    video_count,
    thumbnail_url,
    updated_at
from src
