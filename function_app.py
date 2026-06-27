import azure.functions as func
import logging
import csv
import io
import os
import pymssql

app = func.FunctionApp()

@app.blob_trigger(
    arg_name="myblob",
    path="telemetry-data/{name}",
    connection="AzureWebJobsStorage",
    source="EventGrid"
)
def telemetry_blob_trigger(myblob: func.InputStream):
    logging.info(f"Processing new telemetry file: {myblob.name}")

    try:
        # 1. Read and parse CSV
        csv_text = myblob.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_text))

        # 2. SQL connection using pymssql (no OS driver needed)
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
        logging.info(f"SUCCESS: Ingested {row_count} rows from {myblob.name}")

    except Exception as e:
        logging.error(f"FATAL ERROR in {myblob.name}: {type(e).__name__}: {e}", exc_info=True)
        raise