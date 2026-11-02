"""Load the processed Parquet file into PostgreSQL with an idempotent upsert.

Idempotent means: running the load twice gives the same result as running it
once. New hours are inserted, existing hours are updated, nothing is duplicated.
"""
import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "energy_hourly.parquet"
SCHEMA_FILE = PROJECT_ROOT / "sql" / "schema.sql"

# Columns written to the database, in this order (timestamp_utc comes first)
VALUE_COLUMNS = [
    "price_eur_mwh", "solar_mwh", "wind_onshore_mwh", "wind_offshore_mwh",
    "renewable_mwh", "load_mwh", "renewable_share", "date", "hour", "weekday",
]
ALL_COLUMNS = ["timestamp_utc"] + VALUE_COLUMNS

# ON CONFLICT: if the hour already exists, update it instead of failing.
# EXCLUDED is the row we tried to insert. The WHERE clause skips rows whose
# values did not change, so updated_at only moves when data really changed.
UPSERT_SQL = f"""
    INSERT INTO energy_hourly ({", ".join(ALL_COLUMNS)})
    VALUES ({", ".join(["%s"] * len(ALL_COLUMNS))})
    ON CONFLICT (timestamp_utc) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in VALUE_COLUMNS)},
        updated_at = now()
    WHERE ({", ".join(f"energy_hourly.{c}" for c in VALUE_COLUMNS)})
        IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in VALUE_COLUMNS)})
"""


def get_connection() -> psycopg.Connection:
    """Connect using the settings from .env (never hard-code passwords)."""
    load_dotenv(PROJECT_ROOT / ".env")
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


def to_rows(df: pd.DataFrame) -> list[tuple]:
    """Turn the DataFrame into plain Python values that psycopg understands."""
    df = df.reset_index().rename(columns={"timestamp": "timestamp_utc"})
    rows = []
    for r in df[ALL_COLUMNS].itertuples(index=False):
        rows.append((
            r.timestamp_utc.to_pydatetime(),
            float(r.price_eur_mwh), float(r.solar_mwh),
            float(r.wind_onshore_mwh), float(r.wind_offshore_mwh),
            float(r.renewable_mwh), float(r.load_mwh), float(r.renewable_share),
            r.date, int(r.hour), str(r.weekday),
        ))
    return rows


def count_rows(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM energy_hourly").fetchone()[0]


def run() -> None:
    df = pd.read_parquet(PROCESSED_FILE)
    rows = to_rows(df)

    # "with" commits the transaction at the end, or rolls everything back on
    # an error, so the table is never left half-loaded
    with get_connection() as conn:
        conn.execute(SCHEMA_FILE.read_text())
        before = count_rows(conn)
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
            changed = cur.rowcount
        after = count_rows(conn)

    print(f"Rows in file: {len(rows)}")
    print(f"Inserted: {after - before}, updated: {changed - (after - before)}, "
          f"unchanged: {len(rows) - changed}")
    print(f"Rows in table: {after}")


if __name__ == "__main__":
    run()
