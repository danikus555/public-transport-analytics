"""
scripts/ingest_elron.py

Fetches realtime train positions from Elron.
Saves to:
  - bronze.elron_positions (PostgreSQL)
  - IN/elron/YYYY/mmmYYYY/DDMMYYYY/DDMMYYYY_HHMM.json

Source: https://elron.ee/map_data.json
Updates every ~30 seconds on Elron side.

JSON fields:
  reis              - trip number
  liin              - route e.g. "Tallinn - Tartu"
  reisi_algus_aeg   - departure time HH:MM
  reisi_lopp_aeg    - arrival time HH:MM
  kiirus            - speed km/h
  latitude          - lat
  longitude         - lon
  rongi_suund       - bearing degrees
  erinevus_plaanist - delay minutes ('' = on time)
  reisi_staatus     - 'plaaniline', 'hilineb peatuses'
  viimane_peatus    - last known stop
  asukoha_uuendus   - position timestamp from Elron
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

import requests
import psycopg2

from logger import log, get_tech_log, log_http, log_db_connected

tech = get_tech_log("ELRON")

# ── Config — all from env ─────────────────────────────────────
ELRON_RT_URL = os.environ["ELRON_RT_URL"]
IN_BASE      = os.environ["IN_BASE"]

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

# ── Archive path ──────────────────────────────────────────────
def build_archive_path(now: datetime) -> Path:
    """IN/elron/2026/may2026/27052026/27052026_2145.json"""
    folder = (
        Path(IN_BASE) / "elron"
        / now.strftime("%Y")
        / now.strftime("%b%Y").lower()
        / now.strftime("%d%m%Y")
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (now.strftime("%d%m%Y_%H%M") + ".json")

# ── Fetch Elron data ──────────────────────────────────────────
def fetch_elron() -> list[dict]:
    """Fetch train positions from Elron API."""
    t_start = time.time()
    try:
        r = requests.get(ELRON_RT_URL, timeout=10)
        r.raise_for_status()
        ms = (time.time() - t_start) * 1000
        log_http("ELRON", ELRON_RT_URL, r.status_code, ms)
        data = r.json()
        if data.get("status") != 1:
            log.warning(f"Elron API status={data.get('status')} — no data")
            return []
        return data.get("data", [])
    except Exception as e:
        tech.error(f"Elron fetch failed: {e}")
        return []

# ── Parse one train ───────────────────────────────────────────
def parse_train(row: dict) -> dict | None:
    """Parse one train from Elron JSON. Returns dict or None."""
    try:
        lat = float(row.get("latitude", 0))
        lon = float(row.get("longitude", 0))

        # Estonia bounding box
        if not (57.5 <= lat <= 60.0 and 21.5 <= lon <= 28.5):
            return None

        erinevus_str = (row.get("erinevus_plaanist") or "").strip()
        try:
            erinevus = int(erinevus_str) if erinevus_str else None
        except ValueError:
            erinevus = None

        try:
            kiirus = int(row.get("kiirus") or 0)
        except ValueError:
            kiirus = 0

        try:
            suund = int(row.get("rongi_suund") or 0)
        except ValueError:
            suund = None

        asukoha_str = (row.get("asukoha_uuendus") or "").strip()
        try:
            asukoha_uuendus = datetime.strptime(asukoha_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            asukoha_uuendus = None

        return {
            "reis":            str(row.get("reis") or ""),
            "liin":            str(row.get("liin") or ""),
            "reisi_algus":     str(row.get("reisi_algus_aeg") or ""),
            "reisi_lopp":      str(row.get("reisi_lopp_aeg") or ""),
            "kiirus":          kiirus,
            "lat":             lat,
            "lon":             lon,
            "suund":           suund,
            "erinevus":        erinevus,
            "reisi_staatus":   str(row.get("reisi_staatus") or ""),
            "viimane_peatus":  str(row.get("viimane_peatus") or ""),
            "asukoha_uuendus": asukoha_uuendus,
        }
    except Exception as e:
        log.debug(f"Parse error: {e} — row: {row}")
        return None

# ── Save to file ──────────────────────────────────────────────
def save_to_file(trains: list[dict], raw: list[dict], now: datetime) -> Path:
    """Save raw JSON to archive file."""
    filepath = build_archive_path(now)
    data = {
        "fetched_at": now.isoformat(),
        "source":     ELRON_RT_URL,
        "count":      len(trains),
        "trains":     raw
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.debug(f"Saved to {filepath}")
    return filepath

# ── Save to DB ────────────────────────────────────────────────
def save_to_db(trains: list[dict], conn) -> int:
    """Insert train positions into bronze.elron_positions."""
    if not trains:
        return 0
    cur = conn.cursor()
    try:
        cur.executemany("""
            INSERT INTO bronze.elron_positions
                (reis, liin, reisi_algus, reisi_lopp, kiirus,
                 lat, lon, suund, erinevus, reisi_staatus,
                 viimane_peatus, asukoha_uuendus)
            VALUES
                (%(reis)s, %(liin)s, %(reisi_algus)s, %(reisi_lopp)s, %(kiirus)s,
                 %(lat)s, %(lon)s, %(suund)s, %(erinevus)s, %(reisi_staatus)s,
                 %(viimane_peatus)s, %(asukoha_uuendus)s)
        """, trains)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    return len(trains)

# ── Main entry point ──────────────────────────────────────────
def ingest_elron():
    """Fetch Elron train positions → save to file + DB."""
    now   = datetime.now()
    start = time.time()

    # 1. Fetch
    raw = fetch_elron()
    if not raw:
        log.warning("Elron fetch returned 0 trains")
        return

    # 2. Parse
    trains  = [t for t in (parse_train(r) for r in raw) if t]
    skipped = len(raw) - len(trains)
    log.debug(f"Parsed {len(trains)} trains, skipped {skipped} invalid")

    # 3. Save to file
    try:
        filepath = save_to_file(trains, raw, now)
    except Exception as e:
        log.error(f"File save failed: {e}")
        filepath = None

    # 4. Save to DB
    conn = None
    try:
        conn = get_conn()
        log_db_connected(
            os.environ["DB_HOST"],
            os.environ["DB_NAME"],
            os.environ["DB_USER"]
        )
        count   = save_to_db(trains, conn)
        elapsed = (time.time() - start) * 1000
        delayed = sum(1 for t in trains if t["erinevus"] and t["erinevus"] > 0)
        log.info(
            f"Elron ingest OK — {count} trains → bronze.elron_positions"
            f" | delayed={delayed}"
            f" | file={filepath.name if filepath else 'none'}"
            f" | {elapsed:.0f}ms"
        )
    except Exception as e:
        log.error(f"DB save failed: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    ingest_elron()