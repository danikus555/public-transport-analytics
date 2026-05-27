"""
scripts/scheduler.py

Main entry point for the pipeline container.
Waits for DB, runs initial setup, then schedules ingestion jobs.

Jobs:
    ingest_gps      — every 60 seconds
    ingest_fuel     — daily at 08:00
    load_reference  — weekly on Sunday at 03:00

Note: dbt runs in its own container (Dockerfile.dbt)
"""

import os
import sys
import time

import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from ingest_gps     import ingest_gps
from ingest_fuel    import ingest_fuel
from load_reference import main as load_reference
from logger         import log, get_tech_log, log_startup, log_db_connected

tech = get_tech_log("SCHEDULER")

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST",         "localhost"),
        port=int(os.getenv("DB_PORT",     5432)),
        dbname=os.getenv("DB_NAME",       "transport_db"),
        user=os.getenv("DB_USER",         "transport_user"),
        password=os.getenv("DB_PASSWORD", "changeme")
    )

# ── Wait for DB ───────────────────────────────────────────────
def wait_for_db(retries: int = 20, delay: int = 5) -> None:
    tech.info("Waiting for database...")
    for i in range(retries):
        try:
            conn = get_conn()
            conn.close()
            log_db_connected(
                os.getenv("DB_HOST", "localhost"),
                os.getenv("DB_NAME", "transport_db"),
                os.getenv("DB_USER", "transport_user")
            )
            return
        except Exception as e:
            tech.warning(f"DB not ready ({i+1}/{retries}), retry in {delay}s — {e}")
            time.sleep(delay)
    tech.error("Database unavailable after all retries. Exiting.")
    sys.exit(1)

# ── Job event listener ────────────────────────────────────────
def job_listener(event):
    if event.exception:
        log.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        log.debug(f"Job {event.job_id} completed OK")

# ── Main ──────────────────────────────────────────────────────
def main():
    log_startup(
        "PIPELINE",
        DB_HOST=os.getenv("DB_HOST"),
        GPS_URL=os.getenv("GPS_URL"),
        FUEL_URL=os.getenv("FUEL_URL"),
    )

    # 1. Wait for DB
    wait_for_db()

    # 2. Load reference data on startup
    log.info("Running initial reference data load...")
    try:
        load_reference()
    except Exception as e:
        log.error(f"Initial reference load failed: {e}")

    # 3. Run first GPS ingest immediately
    log.info("Running initial GPS ingest...")
    try:
        ingest_gps()
    except Exception as e:
        log.error(f"Initial GPS ingest failed: {e}")

    # 4. Run first fuel ingest immediately
    log.info("Running initial fuel ingest...")
    try:
        ingest_fuel()
    except Exception as e:
        log.error(f"Initial fuel ingest failed: {e}")

    # 5. Start scheduler
    scheduler = BlockingScheduler(timezone="Europe/Tallinn")
    scheduler.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # GPS — every 60 seconds
    scheduler.add_job(
        ingest_gps,
        "interval",
        seconds=60,
        id="ingest_gps",
        max_instances=1,
        misfire_grace_time=30
    )

    # Fuel — daily 08:00
    scheduler.add_job(
        ingest_fuel,
        "cron",
        hour=8, minute=0,
        id="ingest_fuel",
        max_instances=1
    )

    # Reference data — every Sunday at 03:00
    scheduler.add_job(
        load_reference,
        "cron",
        day_of_week="sun",
        hour=3, minute=0,
        id="load_reference",
        max_instances=1
    )

    tech.info("Scheduler started")
    tech.info("  ingest_gps     — every 60s")
    tech.info("  ingest_fuel    — daily 08:00")
    tech.info("  load_reference — Sunday 03:00")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        tech.info("Scheduler stopped.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()