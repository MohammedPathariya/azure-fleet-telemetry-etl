import os
import json
import random
import argparse
import logging
from datetime import datetime, timedelta
import pandas as pd

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


def generate_truck_data(vehicle_id, target_date, state, error_rate_multiplier=1.0):
    start_time = datetime.strptime(f"{target_date}T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")

    # Initialize new trucks fresh near Irving TX base
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

    # Gradual overnight recovery — health improves slowly each day
    if truck["health_modifier"] > 1.0:
        recovery = random.uniform(0.05, 0.15)
        truck["health_modifier"] = max(1.0, round(truck["health_modifier"] - recovery, 2))
        if truck["health_modifier"] == 1.0:
            logging.info(f"{vehicle_id} fully recovered. Health back to baseline.")
        else:
            logging.info(f"{vehicle_id} recovering: health={truck['health_modifier']:.2f}")

    records = []
    current_time = start_time
    end_time = start_time + timedelta(days=1)

    # Fleet always fully refuels overnight — realistic for managed fleet
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

        # Safety floor — should rarely trigger given full overnight refuel
        if fuel_level < 8.0 and speed == 0:
            fuel_level = random.uniform(85.0, 100.0)

        fuel_level = max(0.0, round(fuel_level, 2))

        # Boundary check — reverse heading if truck leaves continental US
        if not (24.0 <= truck["current_lat"] <= 49.0) or not (-125.0 <= truck["current_lon"] <= -66.0):
            truck["heading_lat"] *= -1
            truck["heading_lon"] *= -1

        # ── Fault Code Logic (priority order matters) ────────────────────────
        fault_code = "0"
        hm = truck["health_modifier"]

        # 1. ENGINE OVERHEAT — thermal condition, highest priority
        #    2% base chance when coolant > 100°C, scales with health degradation
        if coolant_temp > 100.0 and random.random() < (0.02 * hm * error_rate_multiplier):
            fault_code = "ERR_ENGINE_OVERHEAT_P0217"
            truck["health_modifier"] = min(3.0, round(hm + 0.3, 2))
            logging.warning(f"{vehicle_id} overheat {coolant_temp}°C. Health={truck['health_modifier']:.2f}")

        # 2. HIGH RPM — mechanical stress while driving
        elif rpm > 1750 and speed > 0:
            fault_code = "ERR_HIGH_RPM_P0219"

        # 3. TRANSMISSION FAULT — only when health is degraded
        elif hm > 2.0 and random.random() < (0.001 * hm * error_rate_multiplier):
            fault_code = "ERR_TRANSMISSION_P0700"

        # 4. SENSOR MALFUNCTION — completely random, rare
        elif random.random() < (0.0005 * error_rate_multiplier):
            fault_code = "ERR_SENSOR_MALFUNCTION_P0122"

        # 5. TIRE PRESSURE — rare, once per day max, only while moving
        elif not tire_fault_issued_today and speed > 0 and random.random() < (0.0003 * error_rate_multiplier):
            fault_code = "ERR_TIRE_PRESSURE_P0847"
            tire_fault_issued_today = True

        # 6. BATTERY VOLTAGE — fires during startup window (6am)
        #    Common in commercial trucks from overnight aux system drain
        elif not battery_fault_issued_today and hour == 6 and random.random() < (0.003 * hm * error_rate_multiplier):
            fault_code = "ERR_BATTERY_VOLTAGE_P0562"
            battery_fault_issued_today = True

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
    parser.add_argument("--trucks", type=int, default=5, help="Number of trucks in the fleet.")
    parser.add_argument("--error-rate", type=float, default=1.0, help="Multiplier for fault generation.")
    parser.add_argument("--start-date", type=str, default=datetime.utcnow().strftime("%Y-%m-%d"),
                        help="Start date (YYYY-MM-DD). Ignored if state file has last_run_date.")
    parser.add_argument("--days", type=int, default=1, help="Number of consecutive days to generate.")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = load_state()

    logging.info(f"Initializing: {args.trucks} trucks for {args.days} days.")

    target_date = None

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

        logging.info(f"--- Generating {target_date} ---")

        for truck_num in range(1, args.trucks + 1):
            vehicle_id = f"TRK-{truck_num:03d}"
            df = generate_truck_data(vehicle_id, target_date, state, args.error_rate)
            file_path = os.path.join(OUTPUT_DIR, f"{vehicle_id}_{target_date}.csv")
            df.to_csv(file_path, index=False)
            logging.info(f"Created: {vehicle_id}_{target_date}.csv ({len(df)} records)")

        state["last_run_date"] = target_date
        save_state(state)
        logging.info(f"Completed {target_date}. State saved.")

    logging.info(f"Done. Data in '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()