# Azure Fleet Telemetry ETL

## Project Overview
This project is an event-driven, serverless data pipeline built on Microsoft Azure. It simulates nightly data dumps from a fleet of commercial trucks and processes their engine telemetry. 

Using an Azure Blob Storage trigger, an Azure Function App automatically scales out to ingest, clean, and load the incoming CSV files into an Azure SQL Database. The architecture is designed to handle bursty, high-volume workloads while maintaining a near-zero cost during idle hours.

## Architecture Phases

* **Phase 1: Mock Data Generation** A local Python script that generates realistic J1939/OBD-II engine telemetry data (RPM, Speed, Fuel, Fault Codes) for a fleet of 50 vehicles, outputting thousands of rows into daily CSV drop files.
* **Phase 2: Azure SQL Destination** Provisioning and configuring a relational database on Azure SQL (Basic DTU tier) to serve as the structured destination for the processed data.
* **Phase 3: Serverless ETL Engine** Developing an Azure Function App (Consumption Plan) to act as the pipeline. It triggers upon file upload, parses the telemetry, filters out nominal operational noise, and executes SQL inserts for flagged fault codes.

## Local Startup Process

To replicate the current local development environment on a macOS machine using Conda, follow these steps:

1. **Clone the repository and navigate to the root directory:**

   ```bash
   git clone <your-repo-url>
   cd azure-fleet-telemetry-etl
2. **Create and activate the Conda virtual environment:**

    ```bash
    conda create --name fleet-telemetry-env python=3.11 -y
    conda activate fleet-telemetry-env
3. **Install the required dependencies:**

    ```bash
    pip install -r requirements.txt
(Note: Ensure you have Azure Functions Core Tools installed locally before running the function app.)

## Tech Stack & Architecture

* **Compute:** Azure Functions (Consumption Plan / Serverless Python V2 Model)
* **Storage & Ingestion:** Azure Blob Storage (Event-Driven Trigger)
* **Database:** Azure SQL Database (Relational Store)
* **Languages & Libraries:** Python 3.11, Pandas, PyODBC
* **DevOps & Tooling:** Git, GitHub Actions, VS Code, Conda