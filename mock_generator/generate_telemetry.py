import os
import json
import random
import argparse
import logging
from datetime import datetime, timedelta
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

STATE_FILE = "mock_generator/fleet_state.json"
OUTPUT_DIR = "mock_generator/local_csv_drops"

# Logistics Hub Baseline (Irving, TX area)
BASE_LAT = 32.8140
BASE_LON = -96.9488

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {"last_run_date": None, "fleet": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def generate_truck_data(vehicle_id, target_date, state, error_rate_multiplier):
    start_time = datetime.strptime(f"{target_date}T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")
    
    if vehicle_id not in state["fleet"]:
        state["fleet"][vehicle_id] = {
            "health_modifier": 1.0,
            "odometer": random.uniform(500.0, 50000.0),
            "current_lat": BASE_LAT + random.uniform(-0.1, 0.1),
            "current_lon": BASE_LON + random.uniform(-0.1, 0.1),
            "heading_lat": random.choice([-1, 1]) * random.uniform(0.005, 0.015),
            "heading_lon": random.choice([-1, 1]) * random.uniform(0.005, 0.015)
        }
    
    truck = state["fleet"][vehicle_id]
    
    if truck["health_modifier"] > 1.0 and random.random() < 0.20:
        truck["health_modifier"] = 1.0
        logging.info(f"Mechanic repaired {vehicle_id}. Health restored to baseline.")

    records = []
    current_time = start_time
    end_time = start_time + timedelta(days=1)
    
    fuel_level = random.uniform(60.0, 100.0)
    coolant_temp = 20.0 
    
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
                rpm = speed * 22 + random.randint(-50, 50)
                fuel_level -= random.uniform(0.01, 0.02)
                coolant_temp = min(102.0, coolant_temp + random.uniform(0.2, 0.5))
                
                miles_driven = speed / 60.0
                truck["odometer"] += miles_driven
                
                # Brownian jitter for highway curves
                curve_jitter_lat = random.uniform(-0.0015, 0.0015)
                curve_jitter_lon = random.uniform(-0.0015, 0.0015)

                truck["current_lat"] += (truck["heading_lat"] + curve_jitter_lat) * miles_driven
                truck["current_lon"] += (truck["heading_lon"] + curve_jitter_lon) * miles_driven
        else:
            time_step_mins = 15
            speed = 0
            rpm = 0
            coolant_temp = max(20.0, coolant_temp - 2.0)
        
        if fuel_level < 10.0 and speed == 0:
            fuel_level = 100.0
            
        fuel_level = max(0.0, round(fuel_level, 2))
        
        if not (24.0 <= truck["current_lat"] <= 49.0) or not (-125.0 <= truck["current_lon"] <= -66.0):
            truck["heading_lat"] *= -1
            truck["heading_lon"] *= -1
        
        fault_code = "0"
        effective_error_chance = error_rate_multiplier * truck["health_modifier"]
        
        if coolant_temp > 100.0 and random.random() < (0.10 * effective_error_chance):
            fault_code = "ERR_ENGINE_OVERHEAT_P0217"
            if truck["health_modifier"] == 1.0:
                logging.warning(f"{vehicle_id} overheated! Health modifier degraded.")
            truck["health_modifier"] = 5.0
        elif random.random() < (0.0001 * effective_error_chance):
            fault_code = "ERR_SENSOR_MALFUNCTION_P0122"
            
        records.append({
            "Timestamp": timestamp_str,
            "VehicleID": vehicle_id,
            "EngineRPM": rpm,
            "SpeedMPH": speed,
            "FuelLevelPct": fuel_level,
            "CoolantTempC": round(coolant_temp, 1),
            "OdometerMiles": round(truck["odometer"], 2),
            "Latitude": round(truck["current_lat"], 6),
            "Longitude": round(truck["current_lon"], 6),
            "FaultCode": fault_code
        })
        
        current_time += timedelta(minutes=time_step_mins)
        
    return pd.DataFrame(records)

def main():
    parser = argparse.ArgumentParser(description="Generate stateful fleet telemetry data.")
    parser.add_argument("--trucks", type=int, default=50, help="Number of trucks in the fleet.")
    parser.add_argument("--error-rate", type=float, default=1.0, help="Multiplier for fault generation.")
    parser.add_argument("--start-date", type=str, default=datetime.utcnow().strftime("%Y-%m-%d"), help="Start date (YYYY-MM-DD).")
    parser.add_argument("--days", type=int, default=1, help="Number of consecutive days to generate.")
    args = parser.parse_args()
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = load_state()
    
    logging.info(f"Initializing telemetry generation: {args.trucks} trucks for {args.days} days.")
    
    for day_offset in range(args.days):
        if state.get("last_run_date"):
            last_date = datetime.strptime(state["last_run_date"], "%Y-%m-%d")
            target_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            if day_offset == 0:
                target_date = args.start_date
            else:
                last_date = datetime.strptime(target_date, "%Y-%m-%d")
                target_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
            
        logging.info(f"--- Starting data generation for {target_date} ---")
        
        for truck_num in range(1, args.trucks + 1):
            vehicle_id = f"TRK-{truck_num:03d}"
            df = generate_truck_data(vehicle_id, target_date, state, args.error_rate)
            
            file_path = os.path.join(OUTPUT_DIR, f"{vehicle_id}_{target_date}.csv")
            df.to_csv(file_path, index=False)
            logging.info(f"Created file: {vehicle_id}_{target_date}.csv ({len(df)} records)")
            
        state["last_run_date"] = target_date
        save_state(state)
        logging.info(f"Completed {target_date}. State file updated.")
        
    logging.info(f"Process complete. Data available in '{OUTPUT_DIR}/'")

if __name__ == "__main__":
    main()