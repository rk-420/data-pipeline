"""Upload pipeline data to the S3 data lake.

Layout in the bucket:
  raw/run_date=2026-11-02/solar_mwh/1793574000000.json    untouched API responses
  processed/energy_hourly/dt=2026-11-02/data.parquet       one cleaned file per day

AWS credentials are NOT in the code: boto3 finds them itself (from
`aws configure` on your laptop, or from the IAM role inside Lambda).
"""
import io
import logging
import os
from pathlib import Path

import boto3

logger = logging.getLogger("s3_upload")

RAW_PREFIX = "raw"
PROCESSED_PREFIX = "processed/energy_hourly"


def get_bucket() -> str:
    """Bucket name from the environment (.env locally, Lambda settings in AWS)."""
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise RuntimeError("S3_BUCKET is not set")
    return bucket


def upload_raw(run_folder: Path, bucket: str, s3=None) -> int:
    """Upload every raw JSON file of one run. Returns the number of files."""
    s3 = s3 or boto3.client("s3")
    count = 0
    for path in sorted(run_folder.glob("*/*.json")):
        # e.g. raw/run_date=2026-11-02/solar_mwh/1793574000000.json
        key = f"{RAW_PREFIX}/run_date={run_folder.name}/{path.parent.name}/{path.name}"
        s3.upload_file(str(path), bucket, key)
        count += 1
    logger.info("Uploaded %d raw files to s3://%s/%s/run_date=%s/",
                count, bucket, RAW_PREFIX, run_folder.name)
    return count


def upload_processed(df, bucket: str, s3=None) -> int:
    """Upload the cleaned data as one Parquet file per day ("partitioned by date").

    Athena can then skip all days a query doesn't need, which makes queries
    faster and cheaper (Athena charges per byte scanned). Each day always gets
    the same file name, so uploading again overwrites it: no duplicates.
    """
    s3 = s3 or boto3.client("s3")
    data = df.reset_index().rename(columns={"timestamp": "timestamp_utc"})
    count = 0
    for day, rows in data.groupby("date"):
        # The day is stored in the folder name (dt=...), so drop it from the file
        buffer = io.BytesIO()
        # Milliseconds: a timestamp precision every Athena version reads correctly
        rows.drop(columns="date").to_parquet(buffer, index=False, coerce_timestamps="ms")
        key = f"{PROCESSED_PREFIX}/dt={day}/data.parquet"
        s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
        count += 1
    logger.info("Uploaded %d daily Parquet files to s3://%s/%s/", count, bucket, PROCESSED_PREFIX)
    return count
