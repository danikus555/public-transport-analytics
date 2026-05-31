"""
scripts/scheduler.py

Main entry point for the pipeline container.
Waits for DB, runs initial setup, then schedules all ingestion jobs.

Startup sequence:
  1. wait_for_db
  2. load_reference   (operators, fuel_types, vehicle_models)
  3. load_gtfs        (TLT + Elron routes, stops, trips)
  4. ingest_gps       (first TLT GPS snapshot)
  5. ingest_fuel      (fuel prices)
  6. ingest_elron     (first Elron train snapshot)
  7. scheduler.start  (all jobs running)

Scheduled jobs:
  ingest_gps       — every GPS_INTERVAL_SEC          (default 60s)
  ingest_elron     — every ELRON_INTERVAL_SEC         (default 30s)
  ingest_fuel      — daily  FUEL_CRON_HOUR            (default 08:00)
  load_gtfs_tlt    — weekly GTFS_TLT_CRON_DAY/HOUR    (default Sunday 03:00)
  load_gtfs_elron  — monthly GTFS_ELRON_CRON_DAY/HOUR (default 1st 03:30)
  load_reference   — weekly Sunday 03:00

Note: dbt runs in its own container (Dockerfile.dbt) every 5 minutes in a loop
"""

import os
import sys
import time
from datetime import datetime

import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from ingest_gps     import ingest_gps
from ingest_fuel    import ingest_fuel
from ingest_elron   import ingest_elron
from load_gtfs      import load_gtfs
from load_reference import main as load_reference
from logger         import log, get_tech_log, log_startup, log_db_connected

tech = get_tech_log("SCHEDULER")

# ── Config — all from env ─────────────────────────────────────
GPS_INTERVAL    = int(os.environ.get("GPS_INTERVAL_SEC",   60))
ELRON_INTERVAL  = int(os.environ.get("ELRON_INTERVAL_SEC", 30))
FUEL_HOUR       = int(os.environ.get("FUEL_CRON_HOUR",      8))
GTFS_TLT_DAY    = os.environ.get("GTFS_TLT_CRON_DAY",  "sun")
GTFS_TLT_HOUR   = int(os.environ.get("GTFS_TLT_CRON_HOUR",  3))
GTFS_ELRON_DAY  = int(os.environ.get("GTFS_ELRON_CRON_DAY", 1))
GTFS_ELRON_HOUR = int(os.environ.get("GTFS_ELRON_CRON_HOUR", 3))

# ── Night mode ────────────────────────────────────────────────
NIGHT_START = int(os.environ.get("NIGHT_START_HOUR", 0))   # 00:00
NIGHT_END   = int(os.environ.get("NIGHT_END_HOUR",   6))   # 06:00

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    try:
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"]
        )
    except KeyError as e:
        tech.error(f"Missing env variable: {e}")
        raise
    except psycopg2.OperationalError as e:
        tech.error(f"DB connection failed: {e}")
        raise

# ── Wait for DB ───────────────────────────────────────────────
def wait_for_db(retries: int = 20, delay: int = 5) -> None:
    """Block until PostgreSQL is accepting connections."""
    tech.info("Waiting for database...")
    for i in range(retries):
        conn = None
        try:
            conn = get_conn()
            log_db_connected(
                os.environ["DB_HOST"],
                os.environ["DB_NAME"],
                os.environ["DB_USER"]
            )
            return
        except Exception as e:
            tech.warning(f"DB not ready ({i+1}/{retries}), retry in {delay}s — {e}")
            time.sleep(delay)
        finally:
            if conn:
                conn.close()
    tech.error("Database unavailable after all retries. Exiting.")
    sys.exit(1)

# ── Night mode check ──────────────────────────────────────────
def is_night() -> bool:
    """Return True between NIGHT_START and NIGHT_END."""
    hour = datetime.now().hour
    return NIGHT_START <= hour < NIGHT_END

# ── Job wrappers ──────────────────────────────────────────────
def job_load_gtfs_tlt():
    """Weekly TLT GTFS update."""
    load_gtfs(tlt=True, elron=False)

def job_load_gtfs_elron():
    """Monthly Elron GTFS update."""
    load_gtfs(tlt=False, elron=True)

def job_ingest_gps():
    """GPS ingest — skip at night."""
    if is_night():
        log.debug("Night mode — skipping GPS ingest")
        return
    ingest_gps()

def job_ingest_elron():
    """Elron ingest — skip at night."""
    if is_night():
        log.debug("Night mode — skipping Elron ingest")
        return
    ingest_elron()

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
        DB_HOST=os.environ["DB_HOST"],
        GPS_URL=os.environ["GPS_URL"],
        ELRON_RT_URL=os.environ["ELRON_RT_URL"],
        GTFS_TLT_URL=os.environ["GTFS_TLT_URL"],
    )

    # 1. Wait for DB
    wait_for_db()

    # 2. Load reference data
    log.info("Running initial reference data load...")
    try:
        load_reference()
    except Exception as e:
        log.error(f"Reference load failed: {e}")

    # 3. Load GTFS (TLT + Elron)
    log.info("Running initial GTFS load...")
    try:
        load_gtfs(tlt=True, elron=True)
    except Exception as e:
        log.error(f"GTFS load failed: {e}")

    # 4. First GPS snapshot
    log.info("Running initial GPS ingest...")
    try:
        ingest_gps()
    except Exception as e:
        log.error(f"GPS ingest failed: {e}")

    # 5. Fuel prices
    log.info("Running initial fuel ingest...")
    try:
        ingest_fuel()
    except Exception as e:
        log.error(f"Fuel ingest failed: {e}")

    # 6. First Elron snapshot
    log.info("Running initial Elron ingest...")
    try:
        ingest_elron()
    except Exception as e:
        log.error(f"Elron ingest failed: {e}")

    # 7. Start scheduler
    scheduler = BlockingScheduler(timezone="Europe/Tallinn")
    scheduler.add_listener(job_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # GPS — every GPS_INTERVAL_SEC (skipped at night)
    scheduler.add_job(
        job_ingest_gps,
        "interval",
        seconds=GPS_INTERVAL,
        id="ingest_gps",
        max_instances=1,
        misfire_grace_time=30
    )

    # Elron — every ELRON_INTERVAL_SEC (skipped at night)
    scheduler.add_job(
        job_ingest_elron,
        "interval",
        seconds=ELRON_INTERVAL,
        id="ingest_elron",
        max_instances=1,
        misfire_grace_time=15
    )

    # Fuel — daily at FUEL_CRON_HOUR
    scheduler.add_job(
        ingest_fuel,
        "cron",
        hour=FUEL_HOUR,
        minute=0,
        id="ingest_fuel",
        max_instances=1
    )

    # GTFS TLT — weekly on GTFS_TLT_CRON_DAY at GTFS_TLT_CRON_HOUR
    scheduler.add_job(
        job_load_gtfs_tlt,
        "cron",
        day_of_week=GTFS_TLT_DAY,
        hour=GTFS_TLT_HOUR,
        minute=0,
        id="load_gtfs_tlt",
        max_instances=1
    )

    # GTFS Elron — monthly on GTFS_ELRON_CRON_DAY at GTFS_ELRON_CRON_HOUR
    scheduler.add_job(
        job_load_gtfs_elron,
        "cron",
        day=GTFS_ELRON_DAY,
        hour=GTFS_ELRON_HOUR,
        minute=30,
        id="load_gtfs_elron",
        max_instances=1
    )

    # Reference data — every Sunday at 03:00
    scheduler.add_job(
        load_reference,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="load_reference",
        max_instances=1
    )

    tech.info("Scheduler started")
    tech.info(f"  ingest_gps      — every {GPS_INTERVAL}s (night off {NIGHT_START:02d}:00-{NIGHT_END:02d}:00)")
    tech.info(f"  ingest_elron    — every {ELRON_INTERVAL}s (night off {NIGHT_START:02d}:00-{NIGHT_END:02d}:00)")
    tech.info(f"  ingest_fuel     — daily {FUEL_HOUR:02d}:00")
    tech.info(f"  load_gtfs_tlt   — {GTFS_TLT_DAY} {GTFS_TLT_HOUR:02d}:00")
    tech.info(f"  load_gtfs_elron — day {GTFS_ELRON_DAY} {GTFS_ELRON_HOUR:02d}:30")
    tech.info(f"  load_reference  — sunday 03:00")
    tech.info(f"  dbt             — every 5min (Dockerfile.dbt loop)")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        tech.info("Scheduler stopped.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()