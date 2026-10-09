"""
One small, central place that configures logging for the whole app.

Goal: make it obvious what is happening at every step -- which mode ran,
which customers were shortlisted, what each agent decided, and when a live
model call fell back to a heuristic. Every module just does:

    from app.logging_config import get_logger
    log = get_logger(__name__)
    log.info("something happened")

Logs go to the console AND to logs/traject.log so you always have a record of
a run to look back at. Messages are plain ASCII on purpose (no emojis), which
keeps them safe on Windows terminals that use the cp1252 code page.
"""

import logging
import os
import sys

_CONFIGURED = False

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"

# logs/traject.log at the project root (one level up from this app/ package).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "traject.log")


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the shared 'traject' logger once. Safe to call many times."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    handlers = [console]

    # Best-effort file log -- never let a logging problem crash the app.
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError:
        pass

    logger = logging.getLogger("traject")
    logger.setLevel(level)
    logger.handlers.clear()
    for handler in handlers:
        logger.addHandler(handler)
    logger.propagate = False

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child of the shared 'traject' logger.

    `name` is usually __name__; we strip a leading 'app.' so log lines read
    'agents.workflow' instead of the longer 'traject.app.agents.workflow'.
    """
    setup_logging()
    short_name = name
    if short_name.startswith("app."):
        short_name = short_name[len("app."):]
    elif short_name == "app":
        short_name = "app"
    return logging.getLogger(f"traject.{short_name}")
