# Bangalore AV Routing Dataset

This workspace now supports two dataset modes for:

`Connectivity-Aware Safe Routing Web Suite for Autonomous Vehicles`

## Dataset Modes

### 1. Synthetic Demo Dataset

This is the offline dataset already generated in the repo.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\generate_bangalore_dataset.ps1
```

Use this when you need a quick demo without external data sources.

### 2. Real-Data Dataset

This mode uses:

- OpenStreetMap road data through `OSMnx`
- OpenCellID tower data from a downloaded CSV export
- existing local `weak_zones.csv`
- existing local `feedback.csv`

## Files Produced

- `data/raw/road_segments.csv`
- `data/raw/towers.csv`
- `data/raw/weak_zones.csv`
- `data/raw/feedback.csv`
- `data/raw/environment_profiles.csv`
- `data/processed/segment_connectivity.csv`
- `data/processed/adaptive_signal_map.json`

## Real-Data Setup

### 1. Install Python

Install Python 3.11 or newer and make sure `python` works in PowerShell.

### 2. Install dependencies

```powershell
python -m pip install -r .\requirements.txt
```

### 3. Download OpenCellID data

- Create an account at `https://opencellid.org/`
- Download the OpenCellID CSV export you want to use
- Save it somewhere local, for example:
  - `C:\Users\srikr\Desktop\AV\downloads\opencellid_india.csv`

### 4. Optional provider mapping

If you want provider names like `Jio` and `Airtel` instead of `MCC404-MNC86`, copy:

- `config/provider_mapping.sample.json`

to your own mapping file and edit it as needed.

### 5. Run the real-data pipeline

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_real_pipeline.ps1 `
  -OpenCellIdCsvPath "C:\path\to\opencellid.csv"
```

## What Requires Your Intervention

- Python installation, because this machine currently does not have Python available
- OpenCellID account access and CSV download, because that data requires your account/token
- Optional provider-name mapping if you want branded operator names instead of MCC/MNC identifiers

## Current Workspace State

- The checked-in CSVs are still the synthetic Bangalore demo dataset
- The real-data pipeline code is present but has not been executed yet in this environment

## Notes

- `road_segments.csv` in real-data mode comes from real Bangalore OpenStreetMap roads
- `towers.csv` in real-data mode comes from your OpenCellID CSV after Bangalore-area filtering
- `weak_zones.csv` and `feedback.csv` remain your modeled AV-safety layers unless you replace them
