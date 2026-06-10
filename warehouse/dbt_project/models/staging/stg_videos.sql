with src as (
    select * from {{ source('staging', 'videos') }}
),

deduped as (
    select
        *,
        row_number() over (
            partition by video_id
            order by updated_at desc
        ) as rn
    from src
)

select
    video_id,
    channel_id,
    title,
    description,
    published_at,
    view_count,
    like_count,
    comment_count,
    duration_seconds,
    tags,
    thumbnail_url,
    updated_at
from deduped
where
    rn = 1
    and channel_id in (
        select sc.channel_id from {{ ref('stg_channels') }} as sc
    )
