with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2005-01-01' as date)",
        end_date="cast('2028-01-01' as date)"
    ) }}
)

select
    cast(date_day as date) as date_day,
    cast(to_char(date_day, 'YYYYMMDD') as integer) as date_key,
    cast(extract(year from date_day) as integer) as year,
    cast(extract(quarter from date_day) as integer) as quarter,
    cast(extract(month from date_day) as integer) as month,
    trim(to_char(date_day, 'Month')) as month_name,
    cast(extract(day from date_day) as integer) as day_of_month,
    cast(extract(isodow from date_day) as integer) as iso_day_of_week,
    trim(to_char(date_day, 'Day')) as day_name,
    cast(extract(week from date_day) as integer) as iso_week,
    extract(isodow from date_day) in (6, 7) as is_weekend
from spine
