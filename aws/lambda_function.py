"""AWS Lambda entry point: download the latest SMARD data and store it in S3 raw/.

EventBridge Scheduler calls handler() once a day. Settings come from the
Lambda environment variables:
  S3_BUCKET   bucket name (required)
  WEEKS       weekly chunks to download (default 2: this week and last week)

Packaged together with src/extract.py, src/s3_upload.py and src/logging_setup.py
by aws/build_lambda.sh.
"""
import logging
import os
import shutil
from pathlib import Path

import extract
import s3_upload

# Lambda already sends log output to CloudWatch; we only set the level
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("lambda")

# /tmp is the only folder a Lambda function may write to
TMP_RAW_DIR = Path("/tmp/raw")


def handler(event, context):
    bucket = s3_upload.get_bucket()
    weeks = int(os.environ.get("WEEKS", "2"))

    # A warm Lambda can reuse /tmp from an earlier run, so start empty
    shutil.rmtree(TMP_RAW_DIR, ignore_errors=True)

    run_folder = extract.run(weeks, raw_dir=TMP_RAW_DIR)
    files = s3_upload.upload_raw(run_folder, bucket)

    logger.info("Done: %d files uploaded for run %s", files, run_folder.name)
    return {"status": "ok", "run_date": run_folder.name, "files_uploaded": files}
