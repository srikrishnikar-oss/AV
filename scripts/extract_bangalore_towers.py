from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


BENGALURU_BOUNDS = {
    "lat_min": 12.85,
    "lat_max": 13.15,
    "lon_min": 77.45,
    "lon_max": 77.75,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract a Bengaluru towers dataset from OpenCellID India CSV files."
    )
    parser.add_argument("--csv-404", default="404.csv", help="Path to the MCC 404 CSV file.")
    parser.add_argument("--csv-405", default="405.csv", help="Path to the MCC 405 CSV file.")
    parser.add_argument(
        "--mapping-csv",
        default="MCC-MNC India.csv",
        help="Path to the MCC/MNC operator mapping CSV file.",
    )
    parser.add_argument(
        "--output",
        default="data/raw/towers.csv",
        help="Output path for the Bengaluru towers dataset.",
    )
    return parser.parse_args()


def normalize_radio_type(value: object) -> str:
    if pd.isna(value):
        return "unknown"
    text = str(value).strip().upper()
    aliases = {
        "NR": "5G",
        "LTE": "4G",
        "UMTS": "3G",
        "WCDMA": "3G",
        "GSM": "2G",
    }
    return aliases.get(text, text)


def default_signal_for_radio(radio_type: str) -> float:
    if radio_type == "5G":
        return 90.0
    if radio_type == "4G":
        return 80.0
    if radio_type == "3G":
        return 62.0
    if radio_type == "2G":
        return 45.0
    return 55.0


def default_radius_for_radio(radio_type: str) -> float:
    if radio_type == "5G":
        return 1200.0
    if radio_type == "4G":
        return 2500.0
    if radio_type == "3G":
        return 3500.0
    if radio_type == "2G":
        return 4500.0
    return 3000.0


def load_and_prepare(csv_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_path, low_memory=False)
    rename_map = {
        "long": "lon",
        "longitude": "lon",
        "mnc": "net",
        "cid": "cellid",
        "avgsignal": "averageSignal",
        "sample": "samples",
    }
    frame = frame.rename(columns={k: v for k, v in rename_map.items() if k in frame.columns})

    required = {"radio", "mcc", "net", "lat", "lon"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{csv_path} is missing required columns: {sorted(missing)}")

    frame = frame.dropna(subset=["lat", "lon"]).copy()
    frame = frame[
        frame["lat"].between(BENGALURU_BOUNDS["lat_min"], BENGALURU_BOUNDS["lat_max"])
        & frame["lon"].between(BENGALURU_BOUNDS["lon_min"], BENGALURU_BOUNDS["lon_max"])
    ].copy()
    return frame


def build_provider_lookup(mapping_csv: Path) -> dict[tuple[int, int], str]:
    mapping = pd.read_csv(mapping_csv)
    lookup: dict[tuple[int, int], str] = {}
    for row in mapping.itertuples(index=False):
        try:
            key = (int(row.mcc), int(row.mnc))
        except (TypeError, ValueError):
            continue
        lookup[key] = str(row.operator).strip()
    return lookup


def main() -> None:
    args = parse_args()
    csv_404 = Path(args.csv_404)
    csv_405 = Path(args.csv_405)
    mapping_csv = Path(args.mapping_csv)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    provider_lookup = build_provider_lookup(mapping_csv)
    towers = pd.concat([load_and_prepare(csv_404), load_and_prepare(csv_405)], ignore_index=True)
    towers["radio_type"] = towers["radio"].apply(normalize_radio_type)

    if "averageSignal" not in towers.columns:
        towers["averageSignal"] = pd.NA
    towers["base_strength"] = towers.apply(
        lambda row: float(row["averageSignal"])
        if pd.notna(row["averageSignal"]) and float(row["averageSignal"]) > 0
        else default_signal_for_radio(row["radio_type"]),
        axis=1,
    )

    if "range" not in towers.columns:
        towers["range"] = pd.NA
    towers["coverage_radius_m"] = towers.apply(
        lambda row: float(row["range"])
        if pd.notna(row["range"]) and float(row["range"]) > 0
        else default_radius_for_radio(row["radio_type"]),
        axis=1,
    )

    towers["provider"] = towers.apply(
        lambda row: provider_lookup.get(
            (int(row["mcc"]), int(row["net"])),
            f"MCC{int(row['mcc'])}-MNC{int(row['net'])}",
        ),
        axis=1,
    )

    towers = towers.drop_duplicates(subset=["lat", "lon", "provider", "radio_type"]).copy()
    towers = towers.sort_values(["provider", "radio_type", "lat", "lon"]).reset_index(drop=True)
    towers["tower_id"] = [f"T{i:05d}" for i in range(1, len(towers) + 1)]

    towers_out = towers[
        ["tower_id", "lat", "lon", "provider", "radio_type", "base_strength", "coverage_radius_m"]
    ].copy()
    towers_out.to_csv(output_path, index=False)

    print(f"Created {output_path}")
    print(f"Bengaluru towers: {len(towers_out)}")
    print(towers_out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
