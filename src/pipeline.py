"""Run the whole pipeline: extract -> transform -> load.

Run from the project root:  python src/pipeline.py [--weeks N]
Exit code 0 = success, 1 = a step failed (schedulers use this to detect failures).
"""
import argparse
import logging
import sys
import time

import extract
import load
import transform
from logging_setup import setup_logging

logger = logging.getLogger("pipeline")


def run(weeks: int) -> None:
    start = time.perf_counter()

    logger.info("Step 1/3: extract (%d weeks)", weeks)
    raw_folder = extract.run(weeks)

    # Pass the folder on explicitly, so transform reads exactly what was just downloaded
    logger.info("Step 2/3: transform")
    transform.run(raw_folder)

    logger.info("Step 3/3: load")
    load.run()

    logger.info("Pipeline finished in %.1f s", time.perf_counter() - start)


def main() -> int:
    setup_logging()
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
