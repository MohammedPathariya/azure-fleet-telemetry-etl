# Data Generation Module (Simulation Spec)

## Overview
This module simulates high-fidelity telemetry from a commercial long-haul trucking fleet. It is designed to model the stateful behavior of physical assets over time, rather than producing independent random data points.

## Design Choices & Realism Enhancements

### 1. Stateful Memory (`fleet_state.json`)
The script uses a persistent "JSON Brain" to maintain continuity across multiple runs.
* **Odometer Continuity:** Mileage accumulates based on actual vehicle speed.
* **Geographical Continuity:** The truck resumes travel from its previous night's parking coordinates.
* **History Tracking:** The state file tracks the last simulated date to ensure consecutive, chronological data generation.

### 2. Tiered Telemetry Heartbeats
The simulation mimics enterprise cellular bandwidth constraints by shifting transmission frequency based on vehicle status:
* **Active Mode (06:00 - 18:00):** High-resolution streaming (1 record/minute) to capture precise speed, RPM, and location data.
* **Parked Mode (18:00 - 06:00):** Low-power heartbeat ping (1 record/15 minutes) to monitor basic asset health.

### 3. Spatial Realism (Brownian Jitter)
To prevent the "airplane flight path" effect (perfectly straight lines), the generator injects **Brownian Jitter** into the coordinate updates. Every minute, a small randomized variance is applied to the truck's heading vector. This simulates natural highway curves, lane changes, and road irregularities when plotted on a map.

### 4. Fault Degradation Momentum
Fault codes are linked to thermodynamic states (Coolant Temp). An `ERR_ENGINE_OVERHEAT_P0217` event triggers a persistent degradation of the truck's `health_modifier`. This forces the system to simulate a "lemon truck" that remains prone to failure until a randomized overnight mechanic intervention resets the health status.

## Execution Syntax
To perform a historical backfill from a specific date for a set number of days:

```bash
python mock_generator/generate_telemetry.py --trucks [N] --start-date YYYY-MM-DD --days [N]