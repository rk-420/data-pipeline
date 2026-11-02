"""One shared logging format for all pipeline scripts."""
import logging


def setup_logging(level: int = logging.INFO) -> None:
    """Log lines look like: 2026-11-02 16:40:01 INFO extract: Saved 8 chunks"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
