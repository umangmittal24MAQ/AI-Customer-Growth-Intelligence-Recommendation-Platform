"""
Runs two scheduled jobs:
  1. The daily recommendation pipeline (unchanged).
  2. A weekly feedback recalibration pass -- recomputes each tenant's
     min_score_threshold from logged outcomes, once enough exist. This is
     the "learns over time" piece from the calibration design: still just
     statistics over outcomes, not model retraining.

Import and call start_scheduler() from main.py at startup if you want
automatic runs, in addition to the manual /run endpoint.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from app.logging_config import get_logger
from app.pipeline import generate_recommendations
from app.calibration import recalibrate_from_feedback

log = get_logger(__name__)

scheduler = BackgroundScheduler()

DEFAULT_TENANT_ID = "default"  # swap for multi-tenant iteration once >1 tenant exists


def scheduled_run():
    log.info("Running scheduled recommendation batch...")
    results = generate_recommendations(tenant_id=DEFAULT_TENANT_ID)
    log.info("Scheduled run produced %d recommendations.", len(results))


def scheduled_recalibration():
    log.info("Running scheduled feedback recalibration...")
    profile = recalibrate_from_feedback(tenant_id=DEFAULT_TENANT_ID)
    if profile:
        log.info("Recalibration applied: min_score_threshold = %s", profile['min_score_threshold'])
    else:
        log.info("Recalibration skipped -- not enough outcome data yet.")


def start_scheduler():
    # Daily pipeline run at 6 AM server time.
    scheduler.add_job(scheduled_run, "cron", hour=6, minute=0, id="daily_upsell_run")

    # Weekly recalibration, Sunday at 5 AM -- runs before the Monday pipeline run
    # so the week's recommendations benefit from the latest calibrated threshold.
    scheduler.add_job(
        scheduled_recalibration, "cron", day_of_week="sun", hour=5, minute=0,
        id="weekly_recalibration"
    )

    scheduler.start()
    log.info("Scheduler started: daily run at 06:00, weekly recalibration Sundays at 05:00.")


def stop_scheduler():
    scheduler.shutdown()


def run_recalibration_now(tenant_id: str = DEFAULT_TENANT_ID):
    """Manual trigger, e.g. for an admin endpoint or CLI use during testing."""
    return scheduled_recalibration() if tenant_id == DEFAULT_TENANT_ID else recalibrate_from_feedback(tenant_id)
