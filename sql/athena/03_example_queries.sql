-- Example Athena queries. Athena charges per byte scanned (minimum 10 MB per
-- query = about $0.00005 at $5/TB). Filtering on dt means only those days'
-- files are read, so always filter on dt when you can.


-- 1. Overview of the last 7 days
SELECT dt,
       round(avg(price_eur_mwh), 2)                    AS avg_price_eur_mwh,
       round(sum(renewable_mwh) / sum(load_mwh) * 100, 1) AS renewable_share_pct
FROM energy.energy_hourly
WHERE dt >= date_format(current_date - interval '7' day, '%Y-%m-%d')
GROUP BY dt
ORDER BY dt;


-- 2. Average price by hour of day (German local time)
SELECT hour,
       round(avg(price_eur_mwh), 2) AS avg_price_eur_mwh,
       round(avg(solar_mwh), 0)     AS avg_solar_mwh
FROM energy.energy_hourly
GROUP BY hour
ORDER BY hour;


-- 3. Price by renewable share: 0-20 %, 20-40 %, ... of consumption
SELECT least(floor(renewable_share * 5), 5) * 20 AS share_from_pct,
       count(*)                                   AS hours,
       round(avg(price_eur_mwh), 2)               AS avg_price_eur_mwh
FROM energy.energy_hourly
GROUP BY 1
ORDER BY 1;


-- 4. Correlation between price and solar + wind
SELECT round(corr(price_eur_mwh, renewable_mwh), 2) AS corr_price_renewables
FROM energy.energy_hourly;


-- 5. Hours with negative prices
SELECT timestamp_utc AT TIME ZONE 'Europe/Berlin' AS local_time,
       price_eur_mwh, solar_mwh, renewable_share
FROM energy.energy_hourly
WHERE price_eur_mwh < 0
ORDER BY price_eur_mwh;
