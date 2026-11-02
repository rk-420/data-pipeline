-- Hourly German electricity market data from SMARD.
-- One row per hour. Safe to run many times (IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS energy_hourly (
    -- Start of the hour in UTC. Primary key: each hour exists exactly once,
    -- which is what makes the upsert in load.py possible.
    timestamp_utc      TIMESTAMPTZ   PRIMARY KEY,

    -- NUMERIC stores exact decimals (SMARD delivers 2 decimal places),
    -- unlike FLOAT, which can turn 0.1 into 0.1000000000000000055...
    price_eur_mwh      NUMERIC(8, 2)  NOT NULL CHECK (price_eur_mwh BETWEEN -500 AND 4000),
    solar_mwh          NUMERIC(10, 2) NOT NULL CHECK (solar_mwh >= 0),
    wind_onshore_mwh   NUMERIC(10, 2) NOT NULL CHECK (wind_onshore_mwh >= 0),
    wind_offshore_mwh  NUMERIC(10, 2) NOT NULL CHECK (wind_offshore_mwh >= 0),
    renewable_mwh      NUMERIC(10, 2) NOT NULL CHECK (renewable_mwh >= 0),
    load_mwh           NUMERIC(10, 2) NOT NULL CHECK (load_mwh > 0),
    -- renewable_mwh / load_mwh, e.g. 0.6234 = 62.34 % (can exceed 1)
    renewable_share    NUMERIC(6, 4)  NOT NULL CHECK (renewable_share >= 0),

    -- Local German time (Europe/Berlin), for grouping by day/hour/weekday
    date               DATE           NOT NULL,
    hour               SMALLINT       NOT NULL CHECK (hour BETWEEN 0 AND 23),
    weekday            TEXT           NOT NULL,

    -- When this row was first inserted / last changed by the pipeline
    loaded_at          TIMESTAMPTZ    NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ    NOT NULL DEFAULT now()
);

-- The dashboard filters by date, so an index makes those queries fast
CREATE INDEX IF NOT EXISTS idx_energy_hourly_date ON energy_hourly (date);

-- One LLM-generated market summary per day (written by src/summary.py)
CREATE TABLE IF NOT EXISTS daily_summary (
    date        DATE         PRIMARY KEY,   -- the day that is summarized (German time)
    summary     TEXT         NOT NULL,
    model       TEXT         NOT NULL,      -- which model wrote it
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
