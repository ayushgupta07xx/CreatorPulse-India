{% snapshot snap_dim_channel %}

{{
    config(
        target_schema='snapshots',
        unique_key='channel_id',
        strategy='check',
        check_cols=['title', 'subscriber_count', 'niche']
    )
}}

    select
        channel_id,
        title,
        custom_url,
        country,
        niche,
        subscriber_count,
        view_count,
        video_count
    from {{ ref('int_channel_base') }}

{% endsnapshot %}
