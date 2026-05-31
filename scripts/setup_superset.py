"""
scripts/setup_superset.py

Automatically configures Superset after fresh install:
  1. Creates database connection (transport_db)
  2. Creates datasets from gold + bronze tables
  3. Creates charts
  4. Creates dashboard

Usage:
  python scripts/setup_superset.py

Run after: docker compose up -d
"""

import os
import time
import json
import requests

# ── Config — all from env ─────────────────────────────────────
SUPERSET_URL      = os.environ["SUPERSET_URL"]
SUPERSET_USER     = os.environ["SUPERSET_ADMIN_USER"]
SUPERSET_PASSWORD = os.environ["SUPERSET_ADMIN_PASSWORD"]

DB_HOST     = os.environ["DB_HOST"]
DB_PORT     = os.environ["DB_PORT"]
DB_NAME     = os.environ["DB_NAME"]
DB_USER     = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

session = requests.Session()

# ── Wait for Superset ─────────────────────────────────────────
def wait_for_superset(retries: int = 20, delay: int = 5) -> bool:
    print("Waiting for Superset...")
    for i in range(retries):
        try:
            r = session.get(f"{SUPERSET_URL}/health", timeout=5)
            if r.status_code == 200:
                print("Superset is ready.")
                return True
        except Exception:
            pass
        print(f"  Not ready ({i+1}/{retries}), retry in {delay}s...")
        time.sleep(delay)
    print("Superset unavailable.")
    return False

# ── Login ─────────────────────────────────────────────────────
def login():
    r = session.post(
        f"{SUPERSET_URL}/api/v1/security/login",
        json={
            "username": SUPERSET_USER,
            "password": SUPERSET_PASSWORD,
            "provider": "db",
            "refresh":  True,
        }
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    })
    r = session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
    r.raise_for_status()
    session.headers.update({"X-CSRFToken": r.json()["result"]})
    print(f"Logged in as {SUPERSET_USER}")

# ── Database connection ───────────────────────────────────────
def create_database() -> int:
    sqlalchemy_uri = (
        f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    r = session.get(f"{SUPERSET_URL}/api/v1/database/")
    r.raise_for_status()
    for db in r.json().get("result", []):
        if db["database_name"] == DB_NAME:
            print(f"Database already exists (id={db['id']})")
            return db["id"]

    r = session.post(
        f"{SUPERSET_URL}/api/v1/database/",
        json={
            "database_name":    DB_NAME,
            "sqlalchemy_uri":   sqlalchemy_uri,
            "expose_in_sqllab": True,
            "allow_run_async":  False,
        }
    )
    if not r.ok:
        print(f"Database error {r.status_code}: {r.text}")
        r.raise_for_status()
    db_id = r.json()["id"]
    print(f"Created database connection (id={db_id})")
    return db_id

# ── Datasets ──────────────────────────────────────────────────
def create_dataset(db_id: int, schema: str, table: str) -> int:
    r = session.get(f"{SUPERSET_URL}/api/v1/dataset/")
    r.raise_for_status()
    for ds in r.json().get("result", []):
        if ds["table_name"] == table and ds.get("schema") == schema:
            print(f"Dataset {schema}.{table} already exists (id={ds['id']})")
            return ds["id"]

    r = session.post(
        f"{SUPERSET_URL}/api/v1/dataset/",
        json={"database": db_id, "schema": schema, "table_name": table}
    )
    if not r.ok:
        print(f"Dataset error {r.status_code}: {r.text}")
        r.raise_for_status()
    ds_id = r.json()["id"]
    print(f"Created dataset {schema}.{table} (id={ds_id})")
    return ds_id

# ── Charts ────────────────────────────────────────────────────
def create_chart(name: str, viz_type: str, ds_id: int, params: dict) -> int:
    r = session.get(f"{SUPERSET_URL}/api/v1/chart/")
    r.raise_for_status()
    for chart in r.json().get("result", []):
        if chart["slice_name"] == name:
            print(f"Chart '{name}' already exists (id={chart['id']})")
            return chart["id"]

    r = session.post(
        f"{SUPERSET_URL}/api/v1/chart/",
        json={
            "slice_name":      name,
            "viz_type":        viz_type,
            "datasource_id":   ds_id,
            "datasource_type": "table",
            "params":          json.dumps(params),
        }
    )
    if not r.ok:
        print(f"Chart error {r.status_code}: {r.text}")
        r.raise_for_status()
    chart_id = r.json()["id"]
    print(f"Created chart '{name}' (id={chart_id})")
    return chart_id

# ── Dashboard ─────────────────────────────────────────────────
def create_dashboard() -> int:
    r = session.get(f"{SUPERSET_URL}/api/v1/dashboard/")
    r.raise_for_status()
    for dash in r.json().get("result", []):
        if dash["dashboard_title"] == "Public Transport Analytics - Estonia":
            print(f"Dashboard already exists (id={dash['id']})")
            return dash["id"]

    r = session.post(
        f"{SUPERSET_URL}/api/v1/dashboard/",
        json={
            "dashboard_title": "Public Transport Analytics - Estonia",
            "published":       True,
        }
    )
    if not r.ok:
        print(f"Dashboard error {r.status_code}: {r.text}")
        r.raise_for_status()
    dash_id = r.json()["id"]
    print(f"Created dashboard (id={dash_id})")
    return dash_id

# ── Main ──────────────────────────────────────────────────────
def setup_superset():
    if not wait_for_superset():
        return

    login()

    # 1. Database
    db_id = create_database()

    # 2. Datasets — gold (clean analytics) + bronze (raw for debugging)
    ds_latest     = create_dataset(db_id, "gold",   "latest_positions")
    ds_fleet      = create_dataset(db_id, "gold",   "fleet_summary")
    ds_fuel_cost  = create_dataset(db_id, "gold",   "fuel_cost_daily")
    ds_fuel_daily = create_dataset(db_id, "gold",   "fuel_daily")
    ds_fuel       = create_dataset(db_id, "bronze", "fuel_prices")
    ds_elron      = create_dataset(db_id, "silver", "elron_positions")

    # 3. Charts

    # Active vehicles — from gold.latest_positions (unique vehicles only)
    create_chart(
        "Active Vehicles Now", "big_number_total", ds_latest,
        {
            "metric":     "count",
            "time_range": "No filter",
        }
    )

    # Vehicle types — from gold.latest_positions grouped by transport_type
    create_chart(
        "Vehicle Types Now", "pie", ds_latest,
        {
            "groupby":    ["transport_type"],
            "metric":     "count",
            "time_range": "No filter",
            "row_limit":  10,
        }
    )

    # Fuel prices — from bronze.fuel_prices latest per fuel_type
    create_chart(
        "Fuel Prices Today", "table", ds_fuel,
        {
            "all_columns": ["fuel_type", "price_eur"],
            "time_range":  "No filter",
            "row_limit":   10,
        }
    )

    # Daily fuel cost — from gold.fuel_cost_daily
    create_chart(
        "Daily Fuel Cost by Type", "table", ds_fuel_cost,
        {
            "all_columns": [
                "transport_type", "fuel_type", "operator",
                "active_today", "fleet_total", "utilization_pct",
                "fuel_price_eur", "estimated_daily_cost_eur"
            ],
            "time_range":  "No filter",
            "row_limit":   20,
        }
    )

    # Fleet summary — from gold.fleet_summary
    create_chart(
        "Fleet Summary", "table", ds_fleet,
        {
            "all_columns": [
                "operator", "transport_type", "model",
                "fuel_type", "consumption", "consumption_unit", "vehicle_amount"
            ],
            "time_range":  "No filter",
            "row_limit":   30,
        }
    )

    # Elron trains now — from silver.elron_positions latest
    create_chart(
        "Elron Trains Now", "table", ds_elron,
        {
            "all_columns": [
                "reis", "liin", "fuel_type", "kiirus",
                "delay_min", "reisi_staatus", "viimane_peatus"
            ],
            "time_range":  "No filter",
            "row_limit":   30,
        }
    )

    # Fuel price change — from gold.fuel_daily
    create_chart(
        "Fuel Price Changes", "table", ds_fuel_daily,
        {
            "all_columns": [
                "fuel_type", "price_today", "price_yesterday",
                "change_eur", "change_pct", "date_today"
            ],
            "time_range":  "No filter",
            "row_limit":   10,
        }
    )

    # Tallinn transport table
    create_chart(
        "Tallinn Transport Now", "table", ds_latest,
        {
            "all_columns": [
                "vehicle_id", "line_number", "transport_type",
                "destination", "fuel_type", "operator"
            ],
            "time_range":  "No filter",
            "row_limit":   600,
        }
    )

    # 4. Dashboard
    # NOTE: Tallinn Transport Map must be created manually in Superset:
    # Charts → + Chart → deck.gl Scatter Plot → gold.latest_positions
    # Longitude & Latitude: lon | lat
    # Map Style: https://tile.openstreetmap.org/{z}/{x}/{y}.png
    # Point Color → dimension: transport_type
    # Row limit: 500
    dash_id = create_dashboard()

    print(f"\nSetup complete!")
    print(f"Open: http://localhost:8088/superset/dashboard/{dash_id}/")
    print(f"Drag charts onto the dashboard manually.")


if __name__ == "__main__":
    setup_superset()