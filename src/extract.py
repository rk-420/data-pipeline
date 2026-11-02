"""Extract hourly electricity price and generation data from the SMARD API.

SMARD stores each series in weekly chunks. An index file lists the start
timestamp of every chunk, so we take the last N timestamps and download
those chunks. Each response is saved unchanged as raw JSON.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://www.smard.de/app/chart_data"
RESOLUTION = "hour"
DEFAULT_WEEKS = 8
REQUEST_TIMEOUT = 30  # seconds
DELAY_BETWEEN_REQUESTS = 0.5  # seconds, to be polite to the free API

# name: (filter_id, region)
SERIES = {
    "price_eur_mwh": (4169, "DE-LU"),     # day-ahead price
    "solar_mwh": (4068, "DE"),            # photovoltaic generation
    "wind_onshore_mwh": (4067, "DE"),     # onshore wind generation
    "wind_offshore_mwh": (1225, "DE"),    # offshore wind generation
    "load_mwh": (410, "DE"),              # total electricity consumption (grid load)
}

# Build paths from this file's location, so the script works from any folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def create_session() -> requests.Session:
    """HTTP session that retries failed requests with increasing wait times.

    Retries on rate limiting (429) and server errors (5xx): waits 1s, 2s, 4s.
    """
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "energy-data-pipeline (student project)"
    return session


def get_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    time.sleep(DELAY_BETWEEN_REQUESTS)
    return response.json()


def get_chunk_timestamps(session: requests.Session, filter_id: int, region: str, weeks: int) -> list[int]:
    """Start timestamps (ms since 1970, UTC) of the last `weeks` weekly chunks."""
    url = f"{BASE_URL}/{filter_id}/{region}/index_{RESOLUTION}.json"
    return get_json(session, url)["timestamps"][-weeks:]


def fetch_chunk(session: requests.Session, filter_id: int, region: str, ts: int) -> dict:
    url = f"{BASE_URL}/{filter_id}/{region}/{filter_id}_{region}_{RESOLUTION}_{ts}.json"
    return get_json(session, url)


def save_raw(data: dict, run_folder: Path, name: str, ts: int) -> Path:
    """Keep the untouched API response, so the pipeline can always be rerun.

    Layout: data/raw/<run date>/<series name>/<chunk timestamp>.json
    """
    folder = run_folder / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ts}.json"
    path.write_text(json.dumps(data))
    return path


def run(weeks: int = DEFAULT_WEEKS) -> Path:
    """Download the last `weeks` chunks of every series. Returns the run folder."""
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_folder = RAW_DIR / run_date
    session = create_session()

    for name, (filter_id, region) in SERIES.items():
        timestamps = get_chunk_timestamps(session, filter_id, region, weeks)
        for ts in timestamps:
            data = fetch_chunk(session, filter_id, region, ts)
            save_raw(data, run_folder, name, ts)
        print(f"Saved {len(timestamps)} chunks of {name}")

    print(f"Raw data saved to {run_folder}")
    return run_folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download SMARD data")
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS,
                        help=f"number of weekly chunks to load (default {DEFAULT_WEEKS})")
    args = parser.parse_args()
    run(args.weeks)
