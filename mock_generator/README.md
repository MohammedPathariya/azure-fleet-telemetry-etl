# Data Generation Module (Simulation Spec)

## Overview
This module simulates real-world continuous data streams originating from an enterprise long-haul commercial trucking fleet. Instead of isolated, independent random numbers, this data generator operates as a stateful system.

## Design Choices & Realism Enhancements

### 1. Stateful Memory (`fleet_state.json`)
To mimic a physical asset moving through time and space, the script logs vehicle conditions to a localized JSON state file at the conclusion of every execution cycle. 
* **Odometer Continuity:** Mileage accumulates naturally based on vehicle speed.
* **Geographical Continuity:** The truck resumes travel from the exact GPS coordinates where it was parked the previous night.

### 2. Tiered Telemetry Heartbeats
To simulate enterprise bandwidth and energy-conservation constraints, data frequencies shift based on vehicle states:
* **Active Mode (06:00 - 18:00):** 1 record per minute (high resolution for speed, RPM, spatial routing).
* **Parked Mode (18:00 - 06:00):** 1 record every 15 minutes (low-power "heartbeat" safety check).
* **Total Density:** ~768 records per vehicle per 24 hours.

### 3. Fault Degradation Momentum ("Lemon Trucks")
Fault codes are tied to internal thermodynamic states (coolant spikes above 100°C). When a critical anomaly (`ERR_ENGINE_OVERHEAT_P0217`) triggers, the truck's internal `health_modifier` scales up. It enters a degraded status, making it exponentially more prone to secondary or continuous failure cycles until a simulated overnight mechanic intervention clears the modifier back to baseline.

## Execution Syntax
Execute a multi-day historical backfill by setting a past start date and a consecutive day volume parameter:
```bash
python mock_generator/generate_telemetry.py --trucks 10 --start-date 2026-06-19 --days 7