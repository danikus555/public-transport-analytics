"""
scripts/ingest_gps.py

Fetches live GPS data from Tallinn public transport feed.
Saves to:
  - bronze.vehicle_positions (PostgreSQL)
  - IN/gps/YYYY/mmmYYYY/DDMMYYYY/DDMMYYYY_HHMM.txt

GPS feed format (comma-separated, no header):
  cols[0] = operator_type  (2=regional/other, 3=TLT)
  cols[1] = line_number    (36, 12, 5, 42 etc)
  cols[2] = lon * 1000000
  cols[3] = lat * 1000000
  cols[4] = empty
  cols[5] = bearing
  cols[6] = vehicle_id
  cols[7] = low_floor      (Z=yes, false=no)
  cols[8] = ??? (seems unused)
  cols[9] = destination

Operator types:
  2 = regional/suburban buses
  3 = TLT city transport (tram, bus, trolleybus)
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("GPS")

# ── Config ───────────────────────────────────────────────────
GPS_URL  = os.getenv("GPS_URL", "https://transport.tallinn.ee/gps.txt")
OPERATOR = os.getenv("GPS_OPERATOR", "TLT")
IN_BASE  = os.getenv("IN_BASE", "IN")

ESTONIA_BOUNDS = {
    "lat_min": 57.50, "lat_max": 60.00,
    "lon_min": 21.50, "lon_max": 28.50,
}

# ── DB connection ─────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST",         "localhost"),
        port=int(os.getenv("DB_PORT",     5432)),
        dbname=os.getenv("DB_NAME",       "transport_db"),
        user=os.getenv("DB_USER",         "transport_user"),
        password=os.getenv("DB_PASSWORD", "changeme")
    )

# ── Archive path ──────────────────────────────────────────────
def build_archive_path(now: datetime) -> Path:
    """IN/gps/2026/may2026/27052026/27052026_1000.txt"""
    folder = (
        Path(IN_BASE) / "gps"
        / now.strftime("%Y")
        / now.strftime("%b%Y").lower()
        / now.strftime("%d%m%Y")
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (now.strftime("%d%m%Y_%H%M") + ".txt")

# ── Parse one GPS line ────────────────────────────────────────
def parse_line(line: str) -> dict | None:
    """
    Parse one CSV line from GPS feed.
    Returns dict or None if invalid.
    """
    try:
        cols = line.strip().split(",")
        if len(cols) < 10:
            return None

        lon = int(cols[2]) / 1_000_000
        lat = int(cols[3]) / 1_000_000

        # validate coordinates within Estonia
        if not (
            ESTONIA_BOUNDS["lat_min"] <= lat <= ESTONIA_BOUNDS["lat_max"] and
            ESTONIA_BOUNDS["lon_min"] <= lon <= ESTONIA_BOUNDS["lon_max"]
        ):
            return None

        return {
            "vehicle_id":  int(cols[6]) if cols[6].strip() else None,
            "line_type":   int(cols[0]),    # operator type: 2=regional, 3=TLT
            "line_number": cols[1].strip(), # line number: 36, 12, 5 etc
            "destination": cols[9].strip(),
            "lat":         lat,
            "lon":         lon,
            "bearing":     int(cols[5]) if cols[5].strip() else None,
            "low_floor":   cols[7].strip().upper() == "Z",
            "operator":    OPERATOR,
        }

    except (ValueError, IndexError):
        return None

# ── Fetch GPS feed ────────────────────────────────────────────
def fetch_gps() -> list[dict]:
    """Fetch and parse GPS feed. Returns list of vehicle dicts."""
    t_start = time.time()
    try:
        r = requests.get(GPS_URL, timeout=10)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("GPS", GPS_URL, r.status_code, ms)
    except Exception as e:
        tech.error(f"Fetch failed: {e}")
        return []

    rows    = []
    skipped = 0
    for line in r.text.splitlines():
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed:
            rows.append(parsed)
        else:
            skipped += 1

    log.debug(f"Parsed {len(rows)} rows, skipped {skipped} invalid")
    return rows

# ── Save to file ──────────────────────────────────────────────
def save_to_file(rows: list[dict], now: datetime) -> Path:
    """Save rows to archive file."""
    filepath  = build_archive_path(now)
    timestamp = now.isoformat()

    with open(filepath, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                f"{timestamp},"
                f"{row['vehicle_id']},"
                f"{row['line_type']},"
                f"{row['line_number']},"
                f"{row['destination']},"
                f"{row['lat']},"
                f"{row['lon']},"
                f"{row['bearing']},"
                f"{row['low_floor']},"
                f"{row['operator']}\n"
            )

    log.debug(f"Saved to {filepath}")
    return filepath

# ── Save to DB ────────────────────────────────────────────────
def save_to_db(rows: list[dict], conn) -> int:
    """Insert rows into bronze.vehicle_positions."""
    if not rows:
        return 0

    cur = conn.cursor()
    cur.executemany("""
        INSERT INTO bronze.vehicle_positions
            (vehicle_id, line_type, line_number, destination,
             lat, lon, bearing, low_floor, operator)
        VALUES
            (%(vehicle_id)s, %(line_type)s, %(line_number)s, %(destination)s,
             %(lat)s, %(lon)s, %(bearing)s, %(low_floor)s, %(operator)s)
    """, rows)
    conn.commit()
    return len(rows)

# ── Replay from files ─────────────────────────────────────────
def replay_from_files(folder: str = None) -> int:
    """
    Read all saved GPS files from IN/gps/ and insert to DB.
    Use this to rebuild DB from file archive after truncate.

    Usage:
        docker exec transport-pipeline python scripts/ingest_gps.py --replay
    """
    if folder is None:
        folder = os.path.join(os.getenv("IN_BASE", "IN"), "gps")

    log.info(f"Replaying GPS data from {folder}...")
    conn  = get_conn()
    total = 0

    for root, dirs, files in os.walk(folder):
        for fname in sorted(files):
            if not fname.endswith(".txt"):
                continue
            filepath = os.path.join(root, fname)
            rows = []

            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    cols = line.strip().split(",")
                    if len(cols) < 10:
                        continue
                    try:
                        rows.append({
                            "vehicle_id":  int(cols[1]) if cols[1].strip() not in ("None", "") else None,
                            "line_type":   int(cols[2]),
                            "line_number": cols[3].strip(),
                            "destination": cols[4].strip(),
                            "lat":         float(cols[5]),
                            "lon":         float(cols[6]),
                            "bearing":     int(cols[7]) if cols[7].strip() not in ("None", "") else None,
                            "low_floor":   cols[8].strip() == "True",
                            "operator":    cols[9].strip(),
                        })
                    except (ValueError, IndexError):
                        continue

            if rows:
                count = save_to_db(rows, conn)
                total += count
                log.info(f"Replayed {count} rows from {fname}")

    conn.close()
    log.info(f"Replay complete — {total} total rows inserted")
    return total

# ── Main entry point ──────────────────────────────────────────
def ingest_gps():
    """Fetch GPS feed → save to file archive + DB."""
    now   = datetime.now()
    start = time.time()

    rows = fetch_gps()
    if not rows:
        log.warning("GPS fetch returned 0 rows — skipping")
        return

    try:
        filepath = save_to_file(rows, now)
    except Exception as e:
        log.error(f"File save failed: {e}")
        filepath = None

    try:
        conn    = get_conn()
        log_db_connected(
            os.getenv("DB_HOST", "localhost"),
            os.getenv("DB_NAME", "transport_db"),
            os.getenv("DB_USER", "transport_user")
        )
        count   = save_to_db(rows, conn)
        conn.close()
        elapsed = (time.time() - start) * 1000
        log.info(
            f"GPS ingest OK — {count} vehicles → bronze.vehicle_positions"
            f" | file={filepath.name if filepath else 'none'}"
            f" | {elapsed:.0f}ms"
        )
    except Exception as e:
        log.error(f"DB save failed: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--replay":
        replay_from_files()
    else:
        ingest_gps()