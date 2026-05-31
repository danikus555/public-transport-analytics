"""
scripts/load_gtfs.py

Downloads and loads GTFS data for TLT and Elron.
Saves to:
  - reference.gtfs_agency
  - reference.gtfs_routes
  - reference.gtfs_stops
  - reference.gtfs_trips
  - reference.gtfs_stop_times
  - reference.gtfs_feed_info  (version tracking)
  - IN/gtfs/YYYY/mmmYYYY/DDMMYYYY_tlt.zip
  - IN/gtfs/YYYY/mmmYYYY/DDMMYYYY_elron.zip

Version check: only reloads if feed_version has changed.

Sources:
  TLT:   https://eu-gtfs.remix.com/tallinn.zip
         Mobility Database: https://mobilitydatabase.org/feeds/gtfs/mdb-3047
  Elron: https://eu-gtfs.remix.com/elron.zip
         Mobility Database: https://mobilitydatabase.org/feeds/gtfs/mdb-3153

Scheduler:
  TLT   — every Sunday    at GTFS_TLT_CRON_HOUR   (default 03:00)
  Elron — every 1st of month GTFS_ELRON_CRON_HOUR (default 03:30)

Usage:
  python scripts/load_gtfs.py              # load both
  python scripts/load_gtfs.py --tlt        # TLT only
  python scripts/load_gtfs.py --elron      # Elron only
  python scripts/load_gtfs.py --force      # skip version check
"""

import os
import sys
import csv
import io
import time
import zipfile
import argparse
from datetime import datetime
from pathlib import Path

import requests
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("GTFS")

# ── Config — all from env ─────────────────────────────────────
GTFS_TLT_URL   = os.environ["GTFS_TLT_URL"]
GTFS_ELRON_URL = os.environ["GTFS_ELRON_URL"]
IN_BASE        = os.environ["IN_BASE"]

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ["DB_PORT"]),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"]
        )
        return conn
    except KeyError as e:
        tech.error(f"Missing env variable: {e}")
        raise
    except psycopg2.OperationalError as e:
        tech.error(f"DB connection failed: {e}")
        raise

# ── Archive path ──────────────────────────────────────────────
def save_zip_to_archive(data: bytes, operator: str) -> Path:
    """Save downloaded GTFS zip to IN/gtfs/YYYY/mmmYYYY/ archive."""
    now    = datetime.now()
    folder = (
        Path(IN_BASE) / "gtfs"
        / now.strftime("%Y")
        / now.strftime("%b%Y").lower()
    )
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / f"{now.strftime('%d%m%Y')}_{operator.lower()}.zip"
    with open(filepath, "wb") as f:
        f.write(data)
    log.debug(f"Saved GTFS zip to {filepath}")
    return filepath

# ── Version check ─────────────────────────────────────────────
def get_stored_version(conn, operator: str) -> str | None:
    """Get last loaded feed version from DB."""
    cur = conn.cursor()
    cur.execute("""
        SELECT feed_version FROM reference.gtfs_feed_info
        WHERE operator = %s
        ORDER BY loaded_at DESC LIMIT 1
    """, (operator,))
    row = cur.fetchone()
    return row[0] if row else None

def get_feed_version(zip_data: bytes) -> str | None:
    """Extract feed_version from feed_info.txt inside zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            if "feed_info.txt" in z.namelist():
                with z.open("feed_info.txt") as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                    for row in reader:
                        return row.get("feed_version", "").strip()
    except Exception as e:
        log.warning(f"Could not read feed_info.txt: {e}")
    return None

# ── Download GTFS zip ─────────────────────────────────────────
def download_gtfs(url: str, operator: str) -> bytes | None:
    """Download GTFS zip file. Returns raw bytes."""
    tech.info(f"Downloading GTFS for {operator} from {url}")
    t_start = time.time()
    try:
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("GTFS", url, r.status_code, ms)
        tech.info(f"Downloaded {len(r.content) / 1024 / 1024:.1f}MB for {operator}")
        return r.content
    except Exception as e:
        tech.error(f"GTFS download failed for {operator}: {e}")
        return None

# ── Parse CSV from zip ────────────────────────────────────────
def read_csv_from_zip(zip_data: bytes, filename: str) -> list[dict]:
    """Read a CSV file from GTFS zip. Returns list of dicts."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            if filename not in z.namelist():
                log.warning(f"{filename} not found in zip")
                return []
            with z.open(filename) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
                return list(reader)
    except Exception as e:
        log.error(f"Error reading {filename}: {e}")
        return []

# ── Loaders ───────────────────────────────────────────────────
def load_agency(conn, rows: list[dict], operator: str) -> int:
    cur   = conn.cursor()
    count = 0
    try:
        for r in rows:
            cur.execute("""
                INSERT INTO reference.gtfs_agency
                    (agency_id, agency_name, agency_url, agency_timezone,
                     agency_phone, agency_email, operator)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (agency_id) DO UPDATE SET
                    agency_name = EXCLUDED.agency_name,
                    operator    = EXCLUDED.operator
            """, (
                r.get("agency_id", operator),
                r.get("agency_name", ""),
                r.get("agency_url", ""),
                r.get("agency_timezone", ""),
                r.get("agency_phone", ""),
                r.get("agency_email", ""),
                operator
            ))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"load_agency failed: {e}")
    return count


def load_routes(conn, rows: list[dict], operator: str) -> int:
    cur   = conn.cursor()
    count = 0
    try:
        for r in rows:
            cur.execute("""
                INSERT INTO reference.gtfs_routes
                    (route_id, agency_id, route_short_name, route_long_name,
                     route_type, route_color, route_text_color, operator)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (route_id) DO UPDATE SET
                    route_short_name = EXCLUDED.route_short_name,
                    route_long_name  = EXCLUDED.route_long_name,
                    route_type       = EXCLUDED.route_type,
                    operator         = EXCLUDED.operator,
                    updated_at       = NOW()
            """, (
                r["route_id"],
                r.get("agency_id", ""),
                r.get("route_short_name", ""),
                r.get("route_long_name", ""),
                int(r.get("route_type", 3)),
                r.get("route_color", ""),
                r.get("route_text_color", ""),
                operator
            ))
            count += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"load_routes failed: {e}")
    return count


def load_stops(conn, rows: list[dict], operator: str) -> int:
    cur   = conn.cursor()
    count = 0
    try:
        for r in rows:
            try:
                cur.execute("""
                    INSERT INTO reference.gtfs_stops
                        (stop_id, stop_name, stop_lat, stop_lon,
                         location_type, parent_station, operator)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stop_id) DO UPDATE SET
                        stop_name  = EXCLUDED.stop_name,
                        stop_lat   = EXCLUDED.stop_lat,
                        stop_lon   = EXCLUDED.stop_lon,
                        operator   = EXCLUDED.operator,
                        updated_at = NOW()
                """, (
                    r["stop_id"],
                    r.get("stop_name", ""),
                    float(r["stop_lat"]) if r.get("stop_lat") else None,
                    float(r["stop_lon"]) if r.get("stop_lon") else None,
                    int(r.get("location_type") or 0),
                    r.get("parent_station") or None,
                    operator
                ))
                count += 1
            except (ValueError, KeyError):
                continue
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"load_stops failed: {e}")
    return count


def load_trips(conn, rows: list[dict], operator: str) -> int:
    cur   = conn.cursor()
    count = 0
    try:
        for r in rows:
            try:
                cur.execute("""
                    INSERT INTO reference.gtfs_trips
                        (trip_id, route_id, service_id, trip_headsign,
                         direction_id, operator)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (trip_id) DO UPDATE SET
                        trip_headsign = EXCLUDED.trip_headsign,
                        updated_at    = NOW()
                """, (
                    r["trip_id"],
                    r["route_id"],
                    r.get("service_id", ""),
                    r.get("trip_headsign", ""),
                    int(r.get("direction_id") or 0),
                    operator
                ))
                count += 1
            except (ValueError, KeyError):
                continue
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error(f"load_trips failed: {e}")
    return count


def load_stop_times(conn, rows: list[dict], batch_size: int = 5000) -> int:
    """Load stop_times in batches — large file."""
    cur   = conn.cursor()
    count = 0
    batch = []
    try:
        for r in rows:
            batch.append((
                r.get("trip_id", ""),
                r.get("arrival_time", ""),
                r.get("departure_time", ""),
                r.get("stop_id", ""),
                int(r.get("stop_sequence") or 0),
            ))
            if len(batch) >= batch_size:
                cur.executemany("""
                    INSERT INTO reference.gtfs_stop_times
                        (trip_id, arrival_time, departure_time,
                         stop_id, stop_sequence)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, batch)
                conn.commit()
                count += len(batch)
                log.debug(f"stop_times batch: {count} rows inserted")
                batch = []

        if batch:
            cur.executemany("""
                INSERT INTO reference.gtfs_stop_times
                    (trip_id, arrival_time, departure_time,
                     stop_id, stop_sequence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, batch)
            conn.commit()
            count += len(batch)

    except Exception as e:
        conn.rollback()
        log.error(f"load_stop_times failed: {e}")
    return count


def save_feed_info(conn, operator: str, version: str, zip_data: bytes):
    """Save feed version info to DB."""
    cur = conn.cursor()
    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            if "feed_info.txt" in z.namelist():
                with z.open("feed_info.txt") as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                    for row in reader:
                        cur.execute("""
                            INSERT INTO reference.gtfs_feed_info
                                (operator, feed_version, feed_start_date, feed_end_date)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            operator,
                            version,
                            row.get("feed_start_date") or None,
                            row.get("feed_end_date")   or None,
                        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning(f"Could not save feed_info: {e}")

# ── Main load function ────────────────────────────────────────
def load_gtfs_operator(operator: str, url: str, conn, force: bool = False):
    """Download and load GTFS for one operator."""
    start = time.time()

    # 1. Download
    zip_data = download_gtfs(url, operator)
    if not zip_data:
        return

    # 2. Save to archive
    try:
        save_zip_to_archive(zip_data, operator)
    except Exception as e:
        log.warning(f"Archive save failed: {e}")

    # 3. Version check
    new_version = get_feed_version(zip_data)
    if not force:
        stored = get_stored_version(conn, operator)
        if stored and stored == new_version:
            log.info(f"{operator} GTFS unchanged (version={new_version}) — skipping")
            return

    log.info(f"Loading {operator} GTFS version: {new_version}")

    # 4. Clear old data for this operator
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM reference.gtfs_stop_times
            WHERE trip_id IN (
                SELECT trip_id FROM reference.gtfs_trips WHERE operator = %s
            )
        """, (operator,))
        cur.execute("DELETE FROM reference.gtfs_trips  WHERE operator = %s", (operator,))
        cur.execute("DELETE FROM reference.gtfs_stops  WHERE operator = %s", (operator,))
        cur.execute("DELETE FROM reference.gtfs_routes WHERE operator = %s", (operator,))
        cur.execute("DELETE FROM reference.gtfs_agency WHERE operator = %s", (operator,))
        conn.commit()
        log.debug(f"Cleared old {operator} GTFS data")
    except Exception as e:
        conn.rollback()
        log.error(f"Clear failed: {e}")
        return

    # 5. Load each file
    n_agency = load_agency(conn,
        read_csv_from_zip(zip_data, "agency.txt"), operator)
    n_routes = load_routes(conn,
        read_csv_from_zip(zip_data, "routes.txt"), operator)
    n_stops  = load_stops(conn,
        read_csv_from_zip(zip_data, "stops.txt"),  operator)
    n_trips  = load_trips(conn,
        read_csv_from_zip(zip_data, "trips.txt"),  operator)
    n_times  = load_stop_times(conn,
        read_csv_from_zip(zip_data, "stop_times.txt"))

    # 6. Save version info
    save_feed_info(conn, operator, new_version, zip_data)

    elapsed = (time.time() - start) / 60
    log.info(
        f"{operator} GTFS loaded in {elapsed:.1f}min — "
        f"agency={n_agency} routes={n_routes} stops={n_stops} "
        f"trips={n_trips} stop_times={n_times}"
    )

# ── Public API ────────────────────────────────────────────────
def load_gtfs(tlt: bool = True, elron: bool = True, force: bool = False):
    """Load GTFS data for TLT and/or Elron."""
    conn = None
    try:
        conn = get_conn()
        log_db_connected(
            os.environ["DB_HOST"],
            os.environ["DB_NAME"],
            os.environ["DB_USER"]
        )
        if tlt:
            load_gtfs_operator("TLT", GTFS_TLT_URL, conn, force)
        if elron:
            load_gtfs_operator("Elron", GTFS_ELRON_URL, conn, force)
    except Exception as e:
        log.error(f"GTFS load failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# ── CLI ───────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load GTFS for TLT and Elron")
    parser.add_argument("--tlt",   action="store_true", help="Load TLT only")
    parser.add_argument("--elron", action="store_true", help="Load Elron only")
    parser.add_argument("--force", action="store_true", help="Skip version check")
    args = parser.parse_args()

    tlt   = args.tlt   or not (args.tlt or args.elron)
    elron = args.elron or not (args.tlt or args.elron)

    load_gtfs(tlt=tlt, elron=elron, force=args.force)