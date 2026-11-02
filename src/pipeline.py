"""Run the whole pipeline: extract -> transform -> load (-> S3 -> summary).

Run from the project root:  python src/pipeline.py [--weeks N]
Exit code 0 = success, 1 = a step failed (schedulers use this to detect failures).

The last two steps are optional and only run when they are configured in .env:
  S3_BUCKET           upload raw and processed data to the S3 data lake
  ANTHROPIC_API_KEY   write the daily market summary with an LLM
"""
import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv

import extract
import load
import transform
from logging_setup import setup_logging

logger = logging.getLogger("pipeline")


def run(weeks: int) -> None:
    start = time.perf_counter()

    logger.info("Step 1/5: extract (%d weeks)", weeks)
    raw_folder = extract.run(weeks)

    # Pass the folder on explicitly, so transform reads exactly what was just downloaded
    logger.info("Step 2/5: transform")
    df = transform.run(raw_folder)

    logger.info("Step 3/5: load into PostgreSQL")
    load.run()

    bucket = os.environ.get("S3_BUCKET")
    if bucket:
        # Imported here, so the pipeline also works without boto3/AWS set up
        import s3_upload
        logger.info("Step 4/5: upload to S3 bucket %s", bucket)
        s3_upload.upload_raw(raw_folder, bucket)
        s3_upload.upload_processed(df, bucket)
    else:
        logger.info("Step 4/5: skipped (S3_BUCKET not set in .env)")

    if os.environ.get("ANTHROPIC_API_KEY"):
        import summary
        logger.info("Step 5/5: daily summary with an LLM")
        summary.run(df)
    else:
        logger.info("Step 5/5: skipped (ANTHROPIC_API_KEY not set in .env)")

    logger.info("Pipeline finished in %.1f s", time.perf_counter() - start)


def main() -> int:
    setup_logging()
    load_dotenv(load.PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Run extract -> transform -> load")
    parser.add_argument("--weeks", type=int, default=extract.DEFAULT_WEEKS,
                        help=f"number of weekly chunks to load (default {extract.DEFAULT_WEEKS})")
    args = parser.parse_args()

    try:
        run(args.weeks)
    except Exception:
        # logger.exception also writes the full error traceback to the log
        logger.exception("Pipeline failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
