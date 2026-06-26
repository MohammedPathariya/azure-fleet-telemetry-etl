import azure.functions as func
import logging
import csv
import io
import os
import pyodbc

app = func.FunctionApp()

# This decorator tells Azure to watch the 'telemetry-data' container for new CSVs
@app.blob_trigger(arg_name="myblob", path="telemetry-data/{name}", connection="AzureWebJobsStorage")
def telemetry_blob_trigger(myblob: func.InputStream):
    logging.info(f"Processing new telemetry file: {myblob.name}")
    
    # 1. Read the CSV data from the blob storage landing zone
    blob_bytes = myblob.read()
    csv_text = blob_bytes.decode('utf-8')
    csv_reader = csv.DictReader(io.StringIO(csv_text))
    
    # 2. Establish connection to your Azure SQL Database
    # (The connection string will be securely stored in environment variables)
    connection_string = os.environ["SqlConnectionString"]
    conn = pyodbc.connect(connection_string)
    cursor = conn.cursor()
    
    try:
        for row in csv_reader:
            # Extract raw metrics from the CSV row
            vehicle_id = row['VehicleID']
            recorded_at = row['RecordedAt']
            lat = float(row['Latitude'])
            lon = float(row['Longitude'])
            speed = int(row['SpeedKmph'])
            temp = float(row['EngineTempCelsius'])
            fuel = float(row['FuelLevelPercentage'])
            
            # 3. Anomaly Sorting Logic (Business Rules)
            is_anomaly = 0
            anomaly_type = None
            
            if temp > 110.0:
                is_anomaly = 1
                anomaly_type = "Engine Overheating"
            elif speed > 120:
                is_anomaly = 1
                anomaly_type = "Speed Limit Violation"
            elif fuel < 10.0:
                is_anomaly = 1
                anomaly_type = "Critical Low Fuel"

            # 4. Insert data directly into the structured table
            cursor.execute("""
                INSERT INTO VehicleTelemetry (VehicleID, RecordedAt, Latitude, Longitude, SpeedKmph, EngineTempCelsius, FuelLevelPercentage, IsAnomaly, AnomalyType)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, vehicle_id, recorded_at, lat, lon, speed, temp, fuel, is_anomaly, anomaly_type)
        
        # Commit the transaction to save changes to the database
        conn.commit()
        logging.info(f"Successfully processed and ingested {myblob.name}")
        
    except Exception as e:
        logging.error(f"Error processing file: {str(e)}")
        conn.rollback()
    finally:
        conn.close()