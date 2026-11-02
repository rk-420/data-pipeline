"""Clean, validate and enrich the raw SMARD data and save it as Parquet."""
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_FILE = PROCESSED_DIR / "energy_hourly.parquet"

PRICE_COLUMN = "price_eur_mwh"
LOAD_COLUMN = "load_mwh"
GENERATION_COLUMNS = ["solar_mwh", "wind_onshore_mwh", "wind_offshore_mwh"]
PRICE_MIN, PRICE_MAX = -500, 4000  # EUR/MWh, the day-ahead market's price limits
LOCAL_TZ = "Europe/Berlin"


def latest_raw_folder() -> Path:
    """Raw folders are named YYYY-MM-DD, so sorting by name gives the newest last."""
    folders = sorted(p for p in RAW_DIR.iterdir() if p.is_dir())
    if not folders:
        raise FileNotFoundError(f"No raw data found in {RAW_DIR}")
    return folders[-1]


def load_chunk(path: Path, name: str) -> pd.Series:
    """Read one raw weekly chunk into a Series indexed by UTC timestamp."""
    data = json.loads(path.read_text())
    df = pd.DataFrame(data["series"], columns=["ts_ms", name])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df.set_index("timestamp")[name]


def load_series(folder: Path) -> pd.Series:
    """Combine all weekly chunks of one series into a single Series.

    The column name comes from the folder name, e.g. solar_mwh/ -> solar_mwh.
    """
    chunks = [load_chunk(path, folder.name) for path in sorted(folder.glob("*.json"))]
    if not chunks:
        raise FileNotFoundError(f"No JSON files in {folder}")
    series = pd.concat(chunks).sort_index()
    # The same hour can appear twice if chunks overlap. A missing value (NaN)
    # must not win over a real one, so drop NaNs first, then keep the last value.
    series = series.dropna()
    return series[~series.index.duplicated(keep="last")]


def load_raw(folder: Path) -> pd.DataFrame:
    """Combine all series in a run folder into one table (one row per hour)."""
    series = [load_series(sub) for sub in sorted(folder.iterdir()) if sub.is_dir()]
    if not series:
        raise FileNotFoundError(f"No series folders in {folder}")
    return pd.concat(series, axis=1).sort_index()


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop hours where any value is missing.

    The newest hours usually have a price (published a day ahead) but no
    generation yet, so they are incomplete and are removed here.
    """
    return df.dropna(how="any")


def validate(df: pd.DataFrame) -> None:
    """Raise an error if the data looks wrong, so bad data never gets loaded."""
    if df.empty:
        raise ValueError("No complete hours left after cleaning")

    if not df.index.is_unique:
        raise ValueError("Duplicate timestamps found")

    prices = df[PRICE_COLUMN]
    out_of_range = prices[(prices < PRICE_MIN) | (prices > PRICE_MAX)]
    if not out_of_range.empty:
        raise ValueError(f"Prices outside {PRICE_MIN}..{PRICE_MAX}:\n{out_of_range}")

    if (df[GENERATION_COLUMNS] < 0).any().any():
        raise ValueError("Negative generation values found")

    # Load is used as a divisor for the renewable share, so it must be positive
    if (df[LOAD_COLUMN] <= 0).any():
        raise ValueError("Load must be greater than zero")

    # Every hour between the first and last timestamp must be present
    expected = pd.date_range(df.index.min(), df.index.max(), freq="h")
    missing = expected.difference(df.index)
    if not missing.empty:
        raise ValueError(f"{len(missing)} missing hours, first: {missing[0]}")


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add columns that make analysis easier."""
    df = df.copy()
    df["renewable_mwh"] = df[GENERATION_COLUMNS].sum(axis=1)
    # Share of consumption covered by solar + wind (0.6 = 60 %). It can go
    # above 1 in very windy, sunny hours when Germany exports the surplus.
    df["renewable_share"] = df["renewable_mwh"] / df[LOAD_COLUMN]

    # Analysis is done in German local time (handles summer/winter time)
    local = df.index.tz_convert(LOCAL_TZ)
    df["date"] = local.date
    df["hour"] = local.hour
    df["weekday"] = local.day_name()
    return df


def run() -> pd.DataFrame:
    folder = latest_raw_folder()
    print(f"Reading raw data from {folder}")

    df = load_raw(folder)
    rows_before = len(df)
    df = clean(df)
    print(f"Kept {len(df)} of {rows_before} hours (dropped incomplete hours)")

    validate(df)
    df = enrich(df)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_FILE)
    print(f"Saved {len(df)} rows -> {OUTPUT_FILE}")
    print(df.head())
    return df


if __name__ == "__main__":
    run()
