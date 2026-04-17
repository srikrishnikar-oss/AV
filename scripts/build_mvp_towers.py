from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


TARGET_COUNT = 60
BOUNDS = {
    "lat_min": 12.85,
    "lat_max": 13.15,
    "lon_min": 77.45,
    "lon_max": 77.75,
}

PROVIDER_CANONICAL = {
    "AirTel": "Airtel",
    "Airtel (Old TATA DOCOMO)": "Airtel",
    "Reliance (Used for Jio in some area)": "Jio",
    "Vi (Vodafone Idea)": "Vi",
}

PROVIDER_QUOTAS = {
    "Airtel": 18,
    "Vi": 16,
    "Jio": 16,
    "BSNL": 10,
}

RADIO_PRIORITY = {
    "5G": 4.0,
    "4G": 3.0,
    "3G": 2.0,
    "2G": 1.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an MVP-sized Bengaluru towers dataset.")
    parser.add_argument("--input", default="data/raw/towers.csv", help="Path to the raw towers CSV.")
    parser.add_argument("--output", default="data/raw/towers_mvp.csv", help="Path to the MVP towers CSV.")
    parser.add_argument("--target-count", type=int, default=TARGET_COUNT, help="Number of towers to keep.")
    return parser.parse_args()


def canonicalize_provider(provider: object) -> str:
    if pd.isna(provider):
        return "Unknown"
    text = str(provider).strip()
    return PROVIDER_CANONICAL.get(text, text)


def score_row(row: pd.Series) -> float:
    radio_weight = RADIO_PRIORITY.get(str(row["radio_type"]).strip(), 0.5)
    signal = float(row["base_strength"])
    radius = float(row["coverage_radius_m"])
    return (radio_weight * 30.0) + signal + min(radius / 150.0, 20.0)


def select_quota_subset(frame: pd.DataFrame, quota: int) -> pd.DataFrame:
    if frame.empty or quota <= 0:
        return frame.head(0)

    selected = []
    used_cells: set[tuple[int, int]] = set()

    for row in frame.itertuples(index=False):
        cell = (int(row.lat_bucket), int(row.lon_bucket))
        if cell in used_cells:
            continue
        used_cells.add(cell)
        selected.append(row.Index)
        if len(selected) >= quota:
            break

    if len(selected) < quota:
        for row in frame.itertuples(index=False):
            if row.Index in selected:
                continue
            selected.append(row.Index)
            if len(selected) >= quota:
                break

    return frame.loc[selected]


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    towers = pd.read_csv(input_path)
    towers = towers[
        towers["lat"].between(BOUNDS["lat_min"], BOUNDS["lat_max"])
        & towers["lon"].between(BOUNDS["lon_min"], BOUNDS["lon_max"])
    ].copy()
    towers["provider"] = towers["provider"].apply(canonicalize_provider)
    towers = towers[towers["provider"].isin(PROVIDER_QUOTAS.keys())].copy()
    towers["radio_priority"] = towers["radio_type"].map(RADIO_PRIORITY).fillna(0.5)
    towers["selection_score"] = towers.apply(score_row, axis=1)
    towers["lat_bucket"] = pd.cut(towers["lat"], bins=8, labels=False, include_lowest=True)
    towers["lon_bucket"] = pd.cut(towers["lon"], bins=8, labels=False, include_lowest=True)
    towers = towers.drop_duplicates(subset=["lat", "lon", "provider", "radio_type"]).copy()
    towers = towers.sort_values(
        ["provider", "selection_score", "base_strength", "coverage_radius_m"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)
    towers["Index"] = towers.index

    selected_frames = []
    for provider, quota in PROVIDER_QUOTAS.items():
        provider_frame = towers[towers["provider"] == provider].copy()
        selected_frames.append(select_quota_subset(provider_frame, quota))

    selected = pd.concat(selected_frames, ignore_index=False)
    selected = selected.drop_duplicates(subset=["lat", "lon", "provider", "radio_type"]).copy()

    if len(selected) < args.target_count:
        remainder = towers[~towers["Index"].isin(selected["Index"])].copy()
        remainder = remainder.sort_values(
            ["radio_priority", "selection_score", "base_strength"],
            ascending=[False, False, False],
        )
        needed = args.target_count - len(selected)
        selected = pd.concat([selected, remainder.head(needed)], ignore_index=False)

    selected = selected.sort_values(["provider", "radio_priority", "selection_score"], ascending=[True, False, False])
    selected = selected.head(args.target_count).copy()
    selected = selected.reset_index(drop=True)
    selected["tower_id"] = [f"MVP_T{i:03d}" for i in range(1, len(selected) + 1)]

    output_columns = [
        "tower_id",
        "lat",
        "lon",
        "provider",
        "radio_type",
        "base_strength",
        "coverage_radius_m",
    ]
    selected[output_columns].to_csv(output_path, index=False)

    print(f"Created {output_path}")
    print(f"MVP towers: {len(selected)}")
    print(selected[output_columns].groupby(["provider", "radio_type"]).size().reset_index(name="count").to_string(index=False))


if __name__ == "__main__":
    main()
