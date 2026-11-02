-- Analysis queries for the energy_hourly table.
-- Key question: how do solar and wind generation affect electricity prices?
-- Run all: docker compose exec -T postgres psql -U energy -d energy < sql/analysis.sql


-- 1. Overview: time range, number of hours, average price and renewables
SELECT
    min(date)                        AS first_day,
    max(date)                        AS last_day,
    count(*)                         AS hours,
    round(avg(price_eur_mwh), 2)     AS avg_price_eur_mwh,
    round(avg(renewable_mwh), 0)     AS avg_renewable_mwh
FROM energy_hourly;


-- 2. Average price by hour of day (German local time).
--    Expect a dip around midday (solar) and peaks in the morning and evening.
SELECT
    hour,
    round(avg(price_eur_mwh), 2)     AS avg_price_eur_mwh,
    round(avg(solar_mwh), 0)         AS avg_solar_mwh
FROM energy_hourly
GROUP BY hour
ORDER BY hour;


-- 3. Price vs. renewable generation: group hours into 5 buckets from
--    lowest to highest renewable output and compare the average price.
SELECT
    bucket,
    round(min(renewable_mwh), 0)     AS from_mwh,
    round(max(renewable_mwh), 0)     AS to_mwh,
    count(*)                         AS hours,
    round(avg(price_eur_mwh), 2)     AS avg_price_eur_mwh
FROM (
    SELECT *, ntile(5) OVER (ORDER BY renewable_mwh) AS bucket
    FROM energy_hourly
) AS bucketed
GROUP BY bucket
ORDER BY bucket;


-- 4. Correlation between price and each generation type
--    (-1 = perfectly opposite, 0 = no relation, +1 = perfectly together)
SELECT
    round(corr(price_eur_mwh, renewable_mwh)::numeric, 2)     AS corr_renewable,
    round(corr(price_eur_mwh, solar_mwh)::numeric, 2)         AS corr_solar,
    round(corr(price_eur_mwh, wind_onshore_mwh)::numeric, 2)  AS corr_wind_onshore,
    round(corr(price_eur_mwh, wind_offshore_mwh)::numeric, 2) AS corr_wind_offshore
FROM energy_hourly;


-- 5. The 10 cheapest hours, and how much renewable power was produced then
SELECT timestamp_utc AT TIME ZONE 'Europe/Berlin' AS local_time,
       price_eur_mwh, solar_mwh, wind_onshore_mwh + wind_offshore_mwh AS wind_mwh
FROM energy_hourly
ORDER BY price_eur_mwh ASC
LIMIT 10;


-- 6. The 10 most expensive hours
SELECT timestamp_utc AT TIME ZONE 'Europe/Berlin' AS local_time,
       price_eur_mwh, solar_mwh, wind_onshore_mwh + wind_offshore_mwh AS wind_mwh
FROM energy_hourly
ORDER BY price_eur_mwh DESC
LIMIT 10;


-- 7. Daily summary: average price and renewable output per day
SELECT
    date,
    weekday,
    round(avg(price_eur_mwh), 2)     AS avg_price_eur_mwh,
    round(sum(renewable_mwh), 0)     AS renewable_mwh_total
FROM energy_hourly
GROUP BY date, weekday
ORDER BY date;
