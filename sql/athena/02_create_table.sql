-- Table over the Parquet files in s3://YOUR_BUCKET/processed/energy_hourly/dt=YYYY-MM-DD/
-- Replace YOUR_BUCKET (twice) before running.
--
-- No Glue crawler needed: the table is defined by hand, and "partition projection"
-- tells Athena how the dt=... folders are named. New days are found automatically,
-- with no crawler runs (which cost money) and no MSCK REPAIR TABLE.
CREATE EXTERNAL TABLE IF NOT EXISTS energy.energy_hourly (
    timestamp_utc      timestamp,
    price_eur_mwh      double,
    solar_mwh          double,
    wind_onshore_mwh   double,
    wind_offshore_mwh  double,
    load_mwh           double,
    renewable_mwh      double,
    renewable_share    double,
    hour               int,
    weekday            string
)
PARTITIONED BY (dt string)   -- the day in German time, taken from the folder name
STORED AS PARQUET
LOCATION 's3://YOUR_BUCKET/processed/energy_hourly/'
TBLPROPERTIES (
    'projection.enabled'          = 'true',
    'projection.dt.type'          = 'date',
    'projection.dt.format'        = 'yyyy-MM-dd',
    'projection.dt.range'         = '2024-01-01,NOW',
    'projection.dt.interval'      = '1',
    'projection.dt.interval.unit' = 'DAYS',
    'storage.location.template'   = 's3://YOUR_BUCKET/processed/energy_hourly/dt=${dt}/'
);
