import azure.functions as func
import logging
import csv
import io
import os
import json
import random
import pymssql
import pandas as pd
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


# ============================================================
# FUNCTION 1 — Ingest trigger (Event Grid → SQL)
# Fires automatically when a CSV lands in telemetry-data
# ============================================================
@app.event_grid_trigger(arg_name="event")
def telemetry_blob_trigger(event: func.EventGridEvent):
    logging.info(f"Event Grid trigger fired: {event.event_type}")

    try:
        event_data = event.get_json()
        blob_url = event_data.get("url", "")
        logging.info(f"Blob URL: {blob_url}")

        if not blob_url.endswith(".csv"):
            logging.info(f"Skipping non-CSV file: {blob_url}")
            return

        connect_str = os.environ["AzureWebJobsStorage"]
        blob_service = BlobServiceClient.from_connection_string(connect_str)

        url_parts = blob_url.replace("https://", "").split("/")
        container_name = url_parts[1]
        blob_name = "/".join(url_parts[2:])

        logging.info(f"Fetching blob: container={container_name}, blob={blob_name}")
        blob_client = blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )
        csv_text = blob_client.download_blob().readall().decode("utf-8")

        csv_reader = csv.DictReader(io.StringIO(csv_text))

        conn = pymssql.connect(
            server=os.environ["SQL_SERVER"],
            user=os.environ["SQL_USER"],
            password=os.environ["SQL_PASSWORD"],
            database=os.environ["SQL_DATABASE"],
            port=1433,
            tds_version="7.4"
        )
        cursor = conn.cursor()

        row_count = 0
        for row in csv_reader:
            vehicle_id   = row['VehicleID']
            timestamp    = row['Timestamp']
            engine_rpm   = int(row['EngineRPM'])
            speed_mph    = float(row['SpeedMPH'])
            fuel_pct     = float(row['FuelLevelPct'])
            coolant_temp = float(row['CoolantTempC'])
            odometer     = float(row['OdometerMiles'])
            lat          = float(row['Latitude'])
            lon          = float(row['Longitude'])
            fault_code   = row['FaultCode']

            is_anomaly   = 0
            anomaly_type = None

            if fault_code != "0":
                is_anomaly   = 1
                anomaly_type = fault_code

            cursor.execute("""
                INSERT INTO VehicleTelemetry
                    (VehicleID, Timestamp, EngineRPM, SpeedMPH, FuelLevelPct,
                     CoolantTempC, OdometerMiles, Latitude, Longitude,
                     FaultCode, IsAnomaly, AnomalyType)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (vehicle_id, timestamp, engine_rpm, speed_mph, fuel_pct,
                  coolant_temp, odometer, lat, lon,
                  fault_code, is_anomaly, anomaly_type))
            row_count += 1

        conn.commit()
        conn.close()
        logging.info(f"SUCCESS: Ingested {row_count} rows from {blob_name}")

    except Exception as e:
        logging.error(f"FATAL ERROR: {type(e).__name__}: {e}", exc_info=True)
        raise


# ============================================================
# FUNCTION 2 — HTTP trigger (Dashboard API)
# GET /api/fleet-stats?days=7
# Returns fleet telemetry summary as JSON for the dashboard
# ============================================================
@app.route(route="fleet-stats", methods=["GET"])
def fleet_stats(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Fleet stats API called")

    try:
        days = int(req.params.get("days", 7))
        days = max(1, min(days, 365))  # clamp between 1 and 365

        conn = pymssql.connect(
            server=os.environ["SQL_SERVER"],
            user=os.environ["SQL_USER"],
            password=os.environ["SQL_PASSWORD"],
            database=os.environ["SQL_DATABASE"],
            port=1433,
            tds_version="7.4"
        )
        cursor = conn.cursor(as_dict=True)

        # ── Stats ──────────────────────────────────────────────────────────
        cursor.execute("""
            SELECT
                COUNT(*)                          AS totalRows,
                SUM(CAST(IsAnomaly AS INT))        AS totalAnomalies,
                COUNT(DISTINCT VehicleID)          AS trucks,
                MAX(Timestamp)                     AS latest
            FROM VehicleTelemetry
            WHERE Timestamp >= DATEADD(day, -%s, GETUTCDATE())
        """, (days,))
        stats_row = cursor.fetchone()

        stats = {
            "totalRows":      stats_row["totalRows"] or 0,
            "totalAnomalies": stats_row["totalAnomalies"] or 0,
            "trucks":         stats_row["trucks"] or 0,
            "latest":         str(stats_row["latest"]) if stats_row["latest"] else None
        }

        # ── Fault breakdown ────────────────────────────────────────────────
        cursor.execute("""
            SELECT FaultCode, COUNT(*) AS cnt
            FROM VehicleTelemetry
            WHERE IsAnomaly = 1
              AND Timestamp >= DATEADD(day, -%s, GETUTCDATE())
            GROUP BY FaultCode
            ORDER BY cnt DESC
        """, (days,))
        fault_rows = cursor.fetchall()
        fault_data = {
            "labels": [r["FaultCode"] for r in fault_rows],
            "values": [r["cnt"] for r in fault_rows]
        }

        # ── Anomalies per truck ────────────────────────────────────────────
        cursor.execute("""
            SELECT VehicleID, SUM(CAST(IsAnomaly AS INT)) AS anomalies
            FROM VehicleTelemetry
            WHERE Timestamp >= DATEADD(day, -%s, GETUTCDATE())
            GROUP BY VehicleID
            ORDER BY VehicleID
        """, (days,))
        truck_rows = cursor.fetchall()
        anomaly_per_truck = {
            "labels": [r["VehicleID"] for r in truck_rows],
            "values": [r["anomalies"] for r in truck_rows]
        }

        # ── Temp time series — hourly sample per truck ─────────────────────
        cursor.execute("""
            SELECT
                VehicleID,
                DATEADD(hour, DATEDIFF(hour, 0, Timestamp), 0) AS hour_bucket,
                AVG(CoolantTempC) AS avg_temp
            FROM VehicleTelemetry
            WHERE Timestamp >= DATEADD(day, -%s, GETUTCDATE())
            GROUP BY VehicleID, DATEADD(hour, DATEDIFF(hour, 0, Timestamp), 0)
            ORDER BY VehicleID, hour_bucket
        """, (days,))
        temp_rows = cursor.fetchall()

        truck_colors = {
            "TRK-001": "#1B5EF7",
            "TRK-002": "#17A76C",
            "TRK-003": "#E87D1B",
            "TRK-004": "#E84040",
            "TRK-005": "#8B5CF6"
        }

        temp_by_truck = {}
        for row in temp_rows:
            vid = row["VehicleID"]
            if vid not in temp_by_truck:
                temp_by_truck[vid] = []
            temp_by_truck[vid].append({
                "x": str(row["hour_bucket"]).replace(" ", "T"),
                "y": round(float(row["avg_temp"]), 1)
            })

        temp_datasets_by_truck = {
            vid: {
                "label": vid,
                "data": points,
                "borderColor": truck_colors.get(vid, "#999"),
                "backgroundColor": "transparent",
                "borderWidth": 2,
                "pointRadius": 0,
                "tension": 0.3
            }
            for vid, points in temp_by_truck.items()
        }

        # ── Recent anomaly events ──────────────────────────────────────────
        cursor.execute("""
            SELECT TOP 25
                VehicleID, Timestamp, FaultCode,
                CoolantTempC, SpeedMPH, EngineRPM
            FROM VehicleTelemetry
            WHERE IsAnomaly = 1
              AND Timestamp >= DATEADD(day, -%s, GETUTCDATE())
            ORDER BY Timestamp DESC
        """, (days,))
        event_rows = cursor.fetchall()
        events = [
            {
                "vehicle":   r["VehicleID"],
                "timestamp": str(r["Timestamp"]),
                "fault":     r["FaultCode"],
                "temp":      float(r["CoolantTempC"]),
                "speed":     float(r["SpeedMPH"]),
                "rpm":       int(r["EngineRPM"])
            }
            for r in event_rows
        ]

        conn.close()

        # ── Build response ─────────────────────────────────────────────────
        truck_list = sorted(temp_datasets_by_truck.keys())
        response = {
            "stats":               stats,
            "tempDatasetsByTruck": temp_datasets_by_truck,
            "truckList":           truck_list,
            "faultData":           fault_data,
            "anomalyPerTruck":     anomaly_per_truck,
            "events":              events
        }

        return func.HttpResponse(
            body=json.dumps(response),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
            status_code=200
        )

    except Exception as e:
        logging.error(f"API ERROR: {type(e).__name__}: {e}", exc_info=True)
        return func.HttpResponse(
            body=json.dumps({"error": str(e)}),
            mimetype="application/json",
            status_code=500
        )


# ============================================================
# GENERATOR LOGIC — synced with mock_generator/generate_telemetry.py
# ============================================================
def generate_truck_data(vehicle_id, target_date, state, error_rate_multiplier=1.0):
    start_time = datetime.strptime(f"{target_date}T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")

    if vehicle_id not in state["fleet"]:
        state["fleet"][vehicle_id] = {
            "health_modifier": 1.0,
            "odometer": random.uniform(5000.0, 30000.0),
            "current_lat": BASE_LAT + random.uniform(-0.5, 0.5),
            "current_lon": BASE_LON + random.uniform(-0.5, 0.5),
            "heading_lat": random.choice([-1, 1]) * random.uniform(0.005, 0.015),
            "heading_lon": random.choice([-1, 1]) * random.uniform(0.005, 0.015)
        }

    truck = state["fleet"][vehicle_id]

    if truck["health_modifier"] > 1.0:
        recovery = random.uniform(0.05, 0.15)
        truck["health_modifier"] = max(1.0, round(truck["health_modifier"] - recovery, 2))
        if truck["health_modifier"] == 1.0:
            logging.info(f"{vehicle_id} fully recovered.")
        else:
            logging.info(f"{vehicle_id} recovering: health={truck['health_modifier']:.2f}")

    records = []
    current_time = start_time
    end_time = start_time + timedelta(days=1)

    fuel_level = random.uniform(85.0, 100.0)
    coolant_temp = 20.0
    tire_fault_issued_today = False
    battery_fault_issued_today = False

    while current_time < end_time:
        hour = current_time.hour
        timestamp_str = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        is_active_shift = 6 <= hour < 18
        is_lunch_break = 12 <= hour < 13

        if is_active_shift:
            time_step_mins = 1

            if is_lunch_break:
                speed = 0
                rpm = 800
                fuel_level -= 0.005
                coolant_temp = max(60.0, coolant_temp - 0.5)
            else:
                speed = random.randint(55, 75)
                rpm = speed * 22 + random.randint(-100, 150)
                fuel_level -= random.uniform(0.01, 0.025)
                coolant_temp = min(102.0, coolant_temp + random.uniform(0.1, 0.4))

                miles_driven = speed / 60.0
                truck["odometer"] += miles_driven

                curve_jitter_lat = random.uniform(-0.0015, 0.0015)
                curve_jitter_lon = random.uniform(-0.0015, 0.0015)
                truck["current_lat"] += (truck["heading_lat"] + curve_jitter_lat) * miles_driven
                truck["current_lon"] += (truck["heading_lon"] + curve_jitter_lon) * miles_driven
        else:
            time_step_mins = 15
            speed = 0
            rpm = 0
            coolant_temp = max(20.0, coolant_temp - 2.0)

        if fuel_level < 8.0 and speed == 0:
            fuel_level = random.uniform(85.0, 100.0)

        fuel_level = max(0.0, round(fuel_level, 2))

        if not (24.0 <= truck["current_lat"] <= 49.0) or not (-125.0 <= truck["current_lon"] <= -66.0):
            truck["heading_lat"] *= -1
            truck["heading_lon"] *= -1

        fault_code = "0"
        hm = truck["health_modifier"]

        if coolant_temp > 100.0 and random.random() < (0.02 * hm * error_rate_multiplier):
            fault_code = "ERR_ENGINE_OVERHEAT_P0217"
            truck["health_modifier"] = min(3.0, round(hm + 0.3, 2))

        elif rpm > 1750 and speed > 0:
            fault_code = "ERR_HIGH_RPM_P0219"

        elif hm > 2.0 and random.random() < (0.001 * hm * error_rate_multiplier):
            fault_code = "ERR_TRANSMISSION_P0700"

        elif random.random() < (0.0005 * error_rate_multiplier):
            fault_code = "ERR_SENSOR_MALFUNCTION_P0122"

        elif not tire_fault_issued_today and speed > 0 and random.random() < (0.0003 * error_rate_multiplier):
            fault_code = "ERR_TIRE_PRESSURE_P0847"
            tire_fault_issued_today = True

        elif not battery_fault_issued_today and hour == 6 and random.random() < (0.003 * hm * error_rate_multiplier):
            fault_code = "ERR_BATTERY_VOLTAGE_P0562"
            battery_fault_issued_today = True

        records.append({
            "Timestamp":    timestamp_str,
            "VehicleID":    vehicle_id,
            "EngineRPM":    rpm,
            "SpeedMPH":     speed,
            "FuelLevelPct": fuel_level,
            "CoolantTempC": round(coolant_temp, 1),
            "OdometerMiles":round(truck["odometer"], 2),
            "Latitude":     round(truck["current_lat"], 6),
            "Longitude":    round(truck["current_lon"], 6),
            "FaultCode":    fault_code
        })

        current_time += timedelta(minutes=time_step_mins)

    return pd.DataFrame(records)


# ============================================================
# FUNCTION 3 — Timer trigger (once every day)
# ============================================================
BASE_LAT = 32.8140
BASE_LON = -96.9488

@app.timer_trigger(
    arg_name="mytimer",
    schedule="0 0 0 * * *"
)
def telemetry_generator(mytimer: func.TimerRequest):
    logging.info("Timer fired: starting telemetry generation")

    try:
        connect_str = os.environ["AzureWebJobsStorage"]
        blob_service = BlobServiceClient.from_connection_string(connect_str)

        # 1. Read fleet_state.json from blob
        state_client = blob_service.get_blob_client(
            container="fleet-state",
            blob="fleet_state.json"
        )
        state_json = state_client.download_blob().readall().decode("utf-8")
        state = json.loads(state_json)
        logging.info(f"Loaded fleet state. Last run date: {state.get('last_run_date')}")

        # 2. Determine next date to generate
        if state.get("last_run_date"):
            last_date = datetime.strptime(state["last_run_date"], "%Y-%m-%d")
            target_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            target_date = "2026-01-01"

        # 3. STOPGAP — don't generate beyond today UTC
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if target_date > today:
            logging.info(f"Pipeline caught up to today ({today}). Nothing to generate.")
            return

        logging.info(f"Generating telemetry for date: {target_date}")

        # 4. Generate and upload CSV for each truck
        trucks = ["TRK-001", "TRK-002", "TRK-003", "TRK-004", "TRK-005"]

        for vehicle_id in trucks:
            df = generate_truck_data(vehicle_id, target_date, state)
            csv_buffer = io.StringIO()
            df.to_csv(csv_buffer, index=False)
            csv_bytes = csv_buffer.getvalue().encode("utf-8")

            blob_name = f"{vehicle_id}_{target_date}.csv"
            csv_client = blob_service.get_blob_client(
                container="telemetry-data",
                blob=blob_name
            )
            csv_client.upload_blob(csv_bytes, overwrite=True)
            logging.info(f"Uploaded {blob_name} ({len(df)} rows)")

        # 5. Save updated fleet_state.json back to blob
        state["last_run_date"] = target_date
        updated_state = json.dumps(state, indent=4)
        state_client.upload_blob(
            updated_state.encode("utf-8"),
            overwrite=True
        )
        logging.info(f"State updated. Next run will generate: day after {target_date}")

    except Exception as e:
        logging.error(f"FATAL ERROR in generator: {type(e).__name__}: {e}", exc_info=True)
        raise