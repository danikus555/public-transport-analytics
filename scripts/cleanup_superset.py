"""
scripts/setup_superset.py

Automatically configures Superset after fresh install:
  1. Creates database connection (transport_db)
  2. Creates datasets from gold + bronze + silver tables
  3. Creates charts — each dashboard has its own chart instances
     (prefixed with dashboard name) so editing one does not affect others
  4. Creates 4 dashboards with charts assigned

Dashboards:
  1. Public - Public Transport Estonia  (public view)
  2. TLT - Operatiivanalüüs             (TLT analyst)
  3. Elron - Analüüs                    (Elron analyst)
  4. Admin - Pipeline Monitooring       (data engineer)

Usage:
  python scripts/setup_superset.py
  Run after: docker compose up -d
"""

import os
import time
import json
import requests

SUPERSET_URL      = os.environ["SUPERSET_URL"]
SUPERSET_USER     = os.environ["SUPERSET_ADMIN_USER"]
SUPERSET_PASSWORD = os.environ["SUPERSET_ADMIN_PASSWORD"]
DB_HOST           = os.environ["DB_HOST"]
DB_PORT           = os.environ["DB_PORT"]
DB_NAME           = os.environ["DB_NAME"]
DB_USER           = os.environ["DB_USER"]
DB_PASSWORD       = os.environ["DB_PASSWORD"]

session = requests.Session()

def wait_for_superset(retries=20, delay=5):
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
    return False

def login():
    r = session.post(f"{SUPERSET_URL}/api/v1/security/login",
        json={"username": SUPERSET_USER, "password": SUPERSET_PASSWORD,
              "provider": "db", "refresh": True})
    r.raise_for_status()
    token = r.json()["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json",
                             "Accept": "application/json"})
    r = session.get(f"{SUPERSET_URL}/api/v1/security/csrf_token/")
    r.raise_for_status()
    session.headers.update({"X-CSRFToken": r.json()["result"]})
    print(f"Logged in as {SUPERSET_USER}")

def create_database():
    uri = (f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}"
           f"@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    r = session.get(f"{SUPERSET_URL}/api/v1/database/")
    r.raise_for_status()
    for db in r.json().get("result", []):
        if db["database_name"] == DB_NAME:
            print(f"Database already exists (id={db['id']})")
            return db["id"]
    r = session.post(f"{SUPERSET_URL}/api/v1/database/",
        json={"database_name": DB_NAME, "sqlalchemy_uri": uri,
              "expose_in_sqllab": True, "allow_run_async": False})
    r.raise_for_status()
    db_id = r.json()["id"]
    print(f"Created database (id={db_id})")
    return db_id

def create_dataset(db_id, schema, table):
    r = session.get(f"{SUPERSET_URL}/api/v1/dataset/?q=(page_size:100)")
    r.raise_for_status()
    for ds in r.json().get("result", []):
        if ds["table_name"] == table and ds.get("schema") == schema:
            print(f"Dataset {schema}.{table} exists (id={ds['id']})")
            return ds["id"]
    r = session.post(f"{SUPERSET_URL}/api/v1/dataset/",
        json={"database": db_id, "schema": schema, "table_name": table})
    r.raise_for_status()
    ds_id = r.json()["id"]
    print(f"Created dataset {schema}.{table} (id={ds_id})")
    return ds_id

def refresh_dataset(ds_id):
    r = session.put(f"{SUPERSET_URL}/api/v1/dataset/{ds_id}/refresh")
    print(f"Refreshed dataset id={ds_id}" if r.ok else f"Refresh failed {ds_id}")

def get_all_charts():
    charts, page = [], 0
    while True:
        r = session.get(f"{SUPERSET_URL}/api/v1/chart/",
                        params={"q": f"(page:{page},page_size:100)"})
        r.raise_for_status()
        results = r.json().get("result", [])
        charts.extend(results)
        if len(results) < 100:
            break
        page += 1
    return charts

def create_chart(name, viz_type, ds_id, params):
    for c in get_all_charts():
        if c["slice_name"] == name:
            print(f"Chart '{name}' exists (id={c['id']})")
            return c["id"]
    r = session.post(f"{SUPERSET_URL}/api/v1/chart/",
        json={"slice_name": name, "viz_type": viz_type,
              "datasource_id": ds_id, "datasource_type": "table",
              "params": json.dumps(params)})
    if not r.ok:
        print(f"Chart error {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
    chart_id = r.json()["id"]
    print(f"Created chart '{name}' (id={chart_id})")
    return chart_id

def create_dashboard(title):
    r = session.get(f"{SUPERSET_URL}/api/v1/dashboard/?q=(page_size:100)")
    r.raise_for_status()
    for d in r.json().get("result", []):
        if d["dashboard_title"] == title:
            print(f"Dashboard '{title}' exists (id={d['id']})")
            return d["id"]
    r = session.post(f"{SUPERSET_URL}/api/v1/dashboard/",
        json={"dashboard_title": title, "published": True})
    r.raise_for_status()
    dash_id = r.json()["id"]
    print(f"Created dashboard '{title}' (id={dash_id})")
    return dash_id

def add_charts_to_dashboard(dash_id, chart_ids):
    for chart_id in chart_ids:
        session.post(f"{SUPERSET_URL}/api/v1/dashboard/{dash_id}/charts",
                     json={"chart_id": chart_id})
    print(f"  Added {len(chart_ids)} charts to dashboard {dash_id}")

# ── Filter helpers ────────────────────────────────────────────
def op_filter(operator):
    return [{
        "clause": "WHERE",
        "expressionType": "SIMPLE",
        "subject": "operator",
        "operator": "==",
        "comparator": operator
    }]

def today_filter():
    return [{
        "clause": "WHERE",
        "expressionType": "SQL",
        "sqlExpression": "snapshot_date = CURRENT_DATE"
    }]

def setup_superset():
    if not wait_for_superset():
        return
    login()
    db_id = create_database()

    print("\n--- Creating datasets ---")
    ds_latest       = create_dataset(db_id, "gold",   "latest_positions")
    ds_fleet        = create_dataset(db_id, "gold",   "fleet_summary")
    ds_fuel_cost    = create_dataset(db_id, "gold",   "fuel_cost_daily")
    ds_fuel_daily   = create_dataset(db_id, "gold",   "fuel_daily")
    ds_fuel_disc    = create_dataset(db_id, "gold",   "fuel_with_discount")
    ds_route_act    = create_dataset(db_id, "gold",   "route_activity")
    ds_route_dist   = create_dataset(db_id, "gold",   "route_distances")
    ds_elron_delays = create_dataset(db_id, "gold",   "elron_delays")
    ds_veh_delays   = create_dataset(db_id, "gold",   "vehicle_delays")
    ds_veh_speed    = create_dataset(db_id, "gold",   "vehicle_speed")
    ds_fuel         = create_dataset(db_id, "bronze", "fuel_prices")
    ds_elron        = create_dataset(db_id, "silver", "elron_positions")
    ds_route_km     = create_dataset(db_id, "gold",   "route_daily_km")

    print("\n--- Refreshing datasets ---")
    for ds_id in [ds_fuel_cost, ds_route_dist, ds_elron_delays,
                  ds_veh_speed, ds_veh_delays, ds_route_act]:
        refresh_dataset(ds_id)

    print("\n--- Creating charts ---")

    # ═══════════════════════════════════════════════════════════
    # DASHBOARD 1: PUBLIC
    # ═══════════════════════════════════════════════════════════
    pub_map = create_chart(
        "Public - Tallinn Transport Map", "deck_scatter", ds_latest,
        {"spatial": {"type": "latlong", "lonCol": "lon", "latCol": "lat"},
         "color_picker": {"r": 0, "g": 122, "b": 255, "a": 1},
         "dimension": "transport_type",
         "point_radius_fixed": {"type": "fix", "value": 10},
         "time_range": "No filter",
         "row_limit": 600,
         "mapbox_style": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         "viewport": {"longitude": 24.75, "latitude": 59.44,
                      "zoom": 11, "bearing": 0, "pitch": 0}})

    pub_active = create_chart(
        "Public - Active Vehicles Now", "big_number_total", ds_latest,
        {"metric": "count", "time_range": "No filter"})

    pub_types = create_chart(
        "Public - Vehicle Types", "echarts_pie", ds_latest,
        {"groupby": ["transport_type"], "metric": "count",
         "time_range": "No filter", "row_limit": 10})

    pub_tlt_table = create_chart(
        "Public - Tallinn Vehicles", "table", ds_latest,
        {"all_columns": ["vehicle_id", "line_number", "transport_type",
                         "destination", "operator"],
         "time_range": "No filter", "row_limit": 600})

    pub_elron_table = create_chart(
        "Public - Elron Trains", "table", ds_elron,
        {"all_columns": ["reis", "liin", "kiirus", "delay_min",
                         "reisi_staatus", "viimane_peatus"],
         "time_range": "No filter", "row_limit": 30})

    pub_fuel_prices = create_chart(
        "Public - Fuel Prices Today", "table", ds_fuel,
        {"all_columns": ["fuel_type", "price_eur"],
         "time_range": "No filter", "row_limit": 10})

    pub_fuel_changes = create_chart(
        "Public - Fuel Price Changes", "table", ds_fuel_daily,
        {"all_columns": ["fuel_type", "price_today", "price_yesterday",
                         "change_eur", "change_pct", "date_today"],
         "time_range": "No filter", "row_limit": 10})

    # ═══════════════════════════════════════════════════════════
    # DASHBOARD 2: TLT
    # ═══════════════════════════════════════════════════════════
    tlt_active = create_chart(
        "TLT - Active Vehicles Now", "big_number_total", ds_latest,
        {"metric": "count", "time_range": "No filter",
         "adhoc_filters": op_filter("TLT")})

    tlt_jam = create_chart(
        "TLT - Vehicles in Jam Now", "big_number_total", ds_veh_speed,
        {"metric": {"label": "in_jam_count", "expressionType": "SQL",
                    "sqlExpression": "COUNT(*) FILTER (WHERE in_jam = true)"},
         "time_range": "No filter"})

    tlt_hourly = create_chart(
        "TLT - Active Vehicles by Hour", "echarts_timeseries_bar", ds_route_act,
        {"metrics": [{"label": "vehicle_count", "expressionType": "SIMPLE",
                      "column": {"column_name": "vehicle_count"},
                      "aggregate": "SUM"}],
         "groupby": ["hour"], "columns": ["transport_type"],
         "time_range": "No filter", "row_limit": 24,
         "adhoc_filters": today_filter()})

    tlt_trend = create_chart(
        "TLT - 7-Day Vehicle Trend", "table", ds_route_act,
        {"all_columns": ["snapshot_date", "transport_type", "vehicle_count"],
         "time_range": "No filter", "row_limit": 30})

    tlt_speed = create_chart(
        "TLT - Vehicle Speed Now", "table", ds_veh_speed,
        {"all_columns": ["vehicle_id", "line_number", "transport_type",
                         "speed_kmh", "speed_category", "in_jam",
                         "destination"],
         "time_range": "No filter", "row_limit": 100})

    tlt_stops = create_chart(
        "TLT - Stop Proximity", "table", ds_veh_delays,
        {"all_columns": ["vehicle_id", "line_number", "transport_type",
                         "stop_name", "delay_category"],
         "time_range": "No filter", "row_limit": 100})

    tlt_fuel_cost = create_chart(
        "TLT - Daily Fuel Cost", "table", ds_fuel_cost,
        {"all_columns": ["transport_type", "fuel_type", "active_today",
                         "fleet_total", "utilization_pct",
                         "estimated_km_per_vehicle",
                         "estimated_daily_cost_eur", "methodology_note"],
         "time_range": "No filter", "row_limit": 10,
         "adhoc_filters": op_filter("TLT")})

    tlt_cost_bar = create_chart(
        "TLT - Cost by Transport Type", "echarts_timeseries_bar", ds_fuel_cost,
        {"metrics": [{"label": "estimated_daily_cost_eur",
                      "expressionType": "SIMPLE",
                      "column": {"column_name": "estimated_daily_cost_eur"},
                      "aggregate": "SUM"}],
         "groupby": ["transport_type"],
         "time_range": "No filter", "row_limit": 10,
         "adhoc_filters": op_filter("TLT")})

    tlt_utilization = create_chart(
        "TLT - Fleet Utilization", "table", ds_fuel_cost,
        {"all_columns": ["transport_type", "active_today",
                         "fleet_total", "utilization_pct"],
         "time_range": "No filter", "row_limit": 10,
         "adhoc_filters": op_filter("TLT")})

    tlt_fleet = create_chart(
        "TLT - Fleet Summary", "table", ds_fleet,
        {"all_columns": ["transport_type", "model", "fuel_type",
                         "consumption", "consumption_unit", "vehicle_amount"],
         "time_range": "No filter", "row_limit": 20,
         "adhoc_filters": op_filter("TLT")})

    tlt_routes = create_chart(
        "TLT - Route Distances", "table", ds_route_dist,
        {"all_columns": ["route_long_name", "transport_type",
                         "avg_one_way_km", "avg_round_trip_km"],
         "time_range": "No filter", "row_limit": 90,
         "adhoc_filters": op_filter("TLT")})

    # ═══════════════════════════════════════════════════════════
    # DASHBOARD 3: ELRON
    # ═══════════════════════════════════════════════════════════
    elron_map = create_chart(
        "Elron - Rongid kaardil", "deck_scatter", ds_elron,
        {"spatial": {"type": "latlong", "lonCol": "lon", "latCol": "lat"},
         "dimension": "liin",
         "point_radius_fixed": {"type": "fix", "value": 15},
         "time_range": "No filter",
         "row_limit": 100,
         "mapbox_style": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
         "viewport": {"longitude": 25.5, "latitude": 58.8,
                      "zoom": 7, "bearing": 0, "pitch": 0}})

    elron_ontime = create_chart(
        "Elron - On-Time Rate", "big_number_total", ds_elron_delays,
        {"metric": {"label": "on_time_pct", "expressionType": "SQL",
                    "sqlExpression": (
                        "ROUND(100.0 * COUNT(*) FILTER "
                        "(WHERE delay_category = 'on_time') "
                        "/ NULLIF(COUNT(*), 0), 1)")},
         "time_range": "No filter"})

    elron_trains = create_chart(
        "Elron - Trains Now", "table", ds_elron,
        {"all_columns": ["reis", "liin", "kiirus", "delay_min",
                         "reisi_staatus", "viimane_peatus"],
         "time_range": "No filter", "row_limit": 30})

    elron_delays = create_chart(
        "Elron - Delays Detail", "table", ds_elron_delays,
        {"all_columns": ["reis", "liin", "fuel_type", "vehicle_model",
                         "delay_min", "delay_category", "reisi_staatus",
                         "last_stop", "speed_kmh", "hour"],
         "time_range": "No filter", "row_limit": 50})

    elron_avg_delay = create_chart(
        "Elron - Average Delay by Route", "echarts_timeseries_bar", ds_elron_delays,
        {"metrics": [{"label": "avg_delay", "expressionType": "SIMPLE",
                      "column": {"column_name": "delay_min"},
                      "aggregate": "AVG"}],
         "groupby": ["liin"],
         "time_range": "No filter", "row_limit": 30})

    elron_delay_cat = create_chart(
        "Elron - Delay Categories", "echarts_pie", ds_elron_delays,
        {"groupby": ["delay_category"], "metric": "count",
         "time_range": "No filter", "row_limit": 10})

    elron_delay_hour = create_chart(
        "Elron - Delay by Hour", "echarts_timeseries_line", ds_elron_delays,
        {"metrics": [{"label": "avg_delay", "expressionType": "SIMPLE",
                      "column": {"column_name": "delay_min"},
                      "aggregate": "AVG"}],
         "groupby": ["hour"],
         "time_range": "No filter", "row_limit": 24})

    elron_routes = create_chart(
        "Elron - Route Distances", "table", ds_route_dist,
        {"all_columns": ["route_long_name", "transport_type",
                         "avg_one_way_km", "avg_round_trip_km"],
         "time_range": "No filter", "row_limit": 35,
         "adhoc_filters": op_filter("Elron")})

    elron_fuel_cost = create_chart(
        "Elron - Daily Cost Electric vs Diesel", "table", ds_fuel_cost,
        {"all_columns": ["fuel_type", "vehicle_model", "active_today",
                         "utilization_pct", "estimated_km_per_vehicle",
                         "estimated_daily_cost_eur"],
         "time_range": "No filter", "row_limit": 10,
         "adhoc_filters": op_filter("Elron")})

    elron_fleet = create_chart(
        "Elron - Fleet Summary", "table", ds_fleet,
        {"all_columns": ["transport_type", "model", "fuel_type",
                         "consumption", "consumption_unit", "vehicle_amount"],
         "time_range": "No filter", "row_limit": 10,
         "adhoc_filters": op_filter("Elron")})

    # ═══════════════════════════════════════════════════════════
    # DASHBOARD 4: ADMIN
    # ═══════════════════════════════════════════════════════════
    admin_fleet = create_chart(
        "Admin - Full Fleet Summary", "table", ds_fleet,
        {"all_columns": ["operator", "transport_type", "model", "fuel_type",
                         "consumption", "consumption_unit", "vehicle_amount"],
         "time_range": "No filter", "row_limit": 30})

    admin_fuel_cost = create_chart(
        "Admin - Full Daily Cost", "table", ds_fuel_cost,
        {"all_columns": ["operator", "transport_type", "fuel_type",
                         "active_today", "fleet_total", "utilization_pct",
                         "estimated_km_per_vehicle", "km_source",
                         "estimated_daily_cost_eur", "methodology_note"],
         "time_range": "No filter", "row_limit": 20})

    admin_discounts = create_chart(
        "Admin - Fuel Prices with Discounts", "table", ds_fuel_disc,
        {"all_columns": ["company", "fuel_type", "pump_price_eur",
                         "discount_eur", "effective_price_eur",
                         "saving_vs_private_pct", "price_method",
                         "price_basis"],
         "time_range": "No filter", "row_limit": 20})

    admin_eff_price = create_chart(
        "Admin - Effective Price by Company", "table", ds_fuel_disc,
        {"all_columns": ["company_label", "fuel_type",
                         "effective_price_eur", "saving_vs_private_pct"],
         "time_range": "No filter", "row_limit": 20})

    admin_routes = create_chart(
        "Admin - All Route Distances", "table", ds_route_dist,
        {"all_columns": ["operator", "transport_type", "route_long_name",
                         "avg_one_way_km", "avg_round_trip_km",
                         "shape_count"],
         "time_range": "No filter", "row_limit": 120})

    admin_route_km = create_chart(
        "Admin - Scheduled km Today", "table", ds_route_km,
        {"all_columns": ["operator", "transport_type", "route_long_name",
                         "total_trips_scheduled", "scheduled_km_per_day"],
         "time_range": "No filter", "row_limit": 120})

    admin_fuel_daily = create_chart(
        "Admin - Fuel Price History", "table", ds_fuel_daily,
        {"all_columns": ["fuel_type", "price_today", "price_today_avg",
                         "price_yesterday", "change_eur",
                         "change_pct", "date_today"],
         "time_range": "No filter", "row_limit": 10})

    print("\n--- Creating dashboards ---")

    dash_public = create_dashboard("Public Transport - Estonia")
    add_charts_to_dashboard(dash_public, [
        pub_map, elron_map,
        pub_active, pub_types, pub_tlt_table,
        pub_elron_table, pub_fuel_prices, pub_fuel_changes,
    ])

    dash_tlt = create_dashboard("TLT - Operatiivanalüüs")
    add_charts_to_dashboard(dash_tlt, [
        pub_map,
        tlt_active, tlt_jam, tlt_hourly, tlt_trend,
        tlt_speed, tlt_stops,
        tlt_fuel_cost, tlt_cost_bar, tlt_utilization,
        tlt_fleet, tlt_routes,
    ])

    dash_elron = create_dashboard("Elron - Analüüs")
    add_charts_to_dashboard(dash_elron, [
        elron_map, elron_ontime, elron_trains, elron_delays,
        elron_avg_delay, elron_delay_cat, elron_delay_hour,
        elron_routes, elron_fuel_cost, elron_fleet,
    ])

    dash_admin = create_dashboard("Admin - Pipeline Monitooring")
    add_charts_to_dashboard(dash_admin, [
        admin_fleet, admin_fuel_cost, admin_discounts,
        admin_eff_price, admin_routes, admin_route_km,
        admin_fuel_daily,
    ])

    print(f"\n{'='*50}")
    print(f"Setup complete! 4 dashboards created.")
    print(f"  Public: http://localhost:8088/superset/dashboard/{dash_public}/")
    print(f"  TLT:    http://localhost:8088/superset/dashboard/{dash_tlt}/")
    print(f"  Elron:  http://localhost:8088/superset/dashboard/{dash_elron}/")
    print(f"  Admin:  http://localhost:8088/superset/dashboard/{dash_admin}/")
    print(f"\nNOTE: Tallinn Transport Map (deck.gl) requires manual setup.")
    print(f"  Charts → + Chart → deck.gl Scatter Plot → gold.latest_positions")
    print(f"  Longitude: lon | Latitude: lat | Color: transport_type")

if __name__ == "__main__":
    setup_superset()