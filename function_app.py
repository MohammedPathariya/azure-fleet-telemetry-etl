import azure.functions as func
import logging
import csv
import io
import os
import json
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

        # 2. Fetch the blob content using the connection string
        connect_str = os.environ["AzureWebJobsStorage"]
        blob_service = BlobServiceClient.from_connection_string(connect_str)

        # Parse container and blob name from URL
        # URL format: https://<account>.blob.core.windows.net/<container>/<blobname>
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
            vehicle_id  = row['VehicleID']
            recorded_at = row['RecordedAt']
            lat         = float(row['Latitude'])
            lon         = float(row['Longitude'])
            speed       = int(row['SpeedKmph'])
            temp        = float(row['EngineTempCelsius'])
            fuel        = float(row['FuelLevelPercentage'])

            is_anomaly   = 0
            anomaly_type = None

            if temp > 110.0:
                is_anomaly   = 1
                anomaly_type = "Engine Overheating"
            elif speed > 120:
                is_anomaly   = 1
                anomaly_type = "Speed Limit Violation"
            elif fuel < 10.0:
                is_anomaly   = 1
                anomaly_type = "Critical Low Fuel"

            cursor.execute("""
                INSERT INTO VehicleTelemetry
                    (VehicleID, RecordedAt, Latitude, Longitude,
                     SpeedKmph, EngineTempCelsius, FuelLevelPercentage,
                     IsAnomaly, AnomalyType)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (vehicle_id, recorded_at, lat, lon,
                  speed, temp, fuel, is_anomaly, anomaly_type))
            row_count += 1

        conn.commit()
        conn.close()
        logging.info(f"SUCCESS: Ingested {row_count} rows from {blob_name}")

    except Exception as e:
        logging.error(f"FATAL ERROR: {type(e).__name__}: {e}", exc_info=True)
        raise