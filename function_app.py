import azure.functions as func
import logging
import csv
import io
import os
import pymssql
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

@app.event_grid_trigger(arg_name="event")
def telemetry_blob_trigger(event: func.EventGridEvent):
    logging.info(f"Event Grid trigger fired: {event.event_type}")

    try:
        # 1. Extract blob URL from the Event Grid event
        event_data = event.get_json()
        blob_url = event_data.get("url", "")
        logging.info(f"Blob URL: {blob_url}")

        if not blob_url.endswith(".csv"):
            logging.info(f"Skipping non-CSV file: {blob_url}")
            return

        # 2. Fetch the blob content
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

        # 3. Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        # 4. Connect to SQL
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
            fault_code   = row['FaultCode']  # string, e.g. "0" or "ERR_ENGINE_OVERHEAT_P0217"

            # Trust the generator's fault logic directly
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