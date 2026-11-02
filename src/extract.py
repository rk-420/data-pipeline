"""Extract hourly electricity price and generation data from the SMARD API."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://www.smard.de/app/chart_data"
RESOLUTION = "hour"

# name: (filter_id, region)
SERIES = {
    "price_eur_mwh": (4169, "DE-LU"),     # day-ahead price
    "solar_mwh": (4068, "DE"),            # photovoltaic generation
    "wind_onshore_mwh": (4067, "DE"),     # onshore wind generation
}

# Build paths from this file's location, so the script works from any folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def get_latest_timestamp(filter_id: int, region: str) -> int:
    """SMARD stores data in weekly chunks; the index lists their start timestamps."""
    url = f"{BASE_URL}/{filter_id}/{region}/index_{RESOLUTION}.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()["timestamps"][-1]


def fetch_series(filter_id: int, region: str) -> dict:
    ts = get_latest_timestamp(filter_id, region)
    url = f"{BASE_URL}/{filter_id}/{region}/{filter_id}_{region}_{RESOLUTION}_{ts}.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def save_raw(data: dict, name: str) -> Path:
    """Keep the untouched API response, so the pipeline can always be rerun."""
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = RAW_DIR / run_date
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(data))
    return path


def to_dataframe(data: dict, name: str) -> pd.DataFrame:
    df = pd.DataFrame(data["series"], columns=["ts_ms", name])
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df.drop(columns="ts_ms")


def run() -> pd.DataFrame:
    frames = []
    for name, (filter_id, region) in SERIES.items():
        data = fetch_series(filter_id, region)
        path = save_raw(data, name)
        print(f"Saved {name} -> {path}")
        frames.append(to_dataframe(data, name).set_index("timestamp"))

    combined = pd.concat(frames, axis=1).dropna(how="all")
    print(combined.tail())
    return combined


if __name__ == "__main__":
    run()