"""Tests for the S3 upload and the Lambda function, against a simulated S3 (moto).

moto replaces AWS in memory: nothing is sent to AWS and nothing costs money.
"""
import io
import json

import boto3
import pandas as pd
import pytest
from moto import mock_aws

import extract
import lambda_function
import s3_upload
import transform

BUCKET = "test-energy-bucket"


@pytest.fixture
def s3(monkeypatch):
    """A fresh, empty fake S3 with one bucket."""
    # Fake credentials, so a real AWS account can never be touched by accident
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket=BUCKET,
                             CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
        yield client


def keys(s3, prefix=""):
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return sorted(obj["Key"] for obj in response.get("Contents", []))


def make_raw_run(folder):
    """A fake extract run: two series with one chunk each."""
    for name in ["price_eur_mwh", "solar_mwh"]:
        (folder / name).mkdir(parents=True)
        (folder / name / "1793574000000.json").write_text(json.dumps({"series": []}))


def test_upload_raw_keeps_run_date_and_series_in_key(s3, tmp_path):
    run_folder = tmp_path / "2026-11-02"
    make_raw_run(run_folder)

    count = s3_upload.upload_raw(run_folder, BUCKET, s3)

    assert count == 2
    assert keys(s3) == [
        "raw/run_date=2026-11-02/price_eur_mwh/1793574000000.json",
        "raw/run_date=2026-11-02/solar_mwh/1793574000000.json",
    ]


def test_upload_processed_writes_one_parquet_file_per_day(s3):
    # 30 hours starting at midnight German time = 2 days (24 + 6 hours)
    index = pd.date_range("2026-10-19 22:00", periods=30, freq="h", tz="UTC", name="timestamp")
    df = transform.enrich(pd.DataFrame({
        "price_eur_mwh": 100.0, "solar_mwh": 1000.0, "wind_onshore_mwh": 2000.0,
        "wind_offshore_mwh": 500.0, "load_mwh": 50000.0,
    }, index=index))

    count = s3_upload.upload_processed(df, BUCKET, s3)

    assert count == 2
    assert keys(s3) == [
        "processed/energy_hourly/dt=2026-10-20/data.parquet",
        "processed/energy_hourly/dt=2026-10-21/data.parquet",
    ]
    body = s3.get_object(Bucket=BUCKET, Key=keys(s3)[0])["Body"].read()
    day = pd.read_parquet(io.BytesIO(body))
    assert len(day) == 24
    assert "date" not in day.columns          # stored in the folder name instead
    assert "timestamp_utc" in day.columns


def test_upload_processed_twice_overwrites_instead_of_duplicating(s3):
    index = pd.date_range("2026-10-19 22:00", periods=24, freq="h", tz="UTC", name="timestamp")
    df = transform.enrich(pd.DataFrame({
        "price_eur_mwh": 100.0, "solar_mwh": 1.0, "wind_onshore_mwh": 1.0,
        "wind_offshore_mwh": 1.0, "load_mwh": 10.0,
    }, index=index))

    s3_upload.upload_processed(df, BUCKET, s3)
    s3_upload.upload_processed(df, BUCKET, s3)

    assert len(keys(s3)) == 1


def test_lambda_handler_extracts_into_tmp_and_uploads(s3, monkeypatch, tmp_path):
    def fake_extract_run(weeks, raw_dir):
        # Instead of calling SMARD, pretend 2 files were downloaded
        assert weeks == 3
        run_folder = raw_dir / "2026-11-02"
        make_raw_run(run_folder)
        return run_folder

    monkeypatch.setattr(extract, "run", fake_extract_run)
    monkeypatch.setattr(lambda_function, "TMP_RAW_DIR", tmp_path / "raw")
    monkeypatch.setenv("WEEKS", "3")

    result = lambda_function.handler(event={}, context=None)

    assert result == {"status": "ok", "run_date": "2026-11-02", "files_uploaded": 2}
    assert len(keys(s3, "raw/run_date=2026-11-02/")) == 2


def test_missing_bucket_setting_gives_clear_error(monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)

    with pytest.raises(RuntimeError, match="S3_BUCKET is not set"):
        s3_upload.get_bucket()
