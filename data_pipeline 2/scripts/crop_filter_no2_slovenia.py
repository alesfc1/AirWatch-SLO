#!/usr/bin/env python3
"""Crop Sentinel-5P NO2 data to Slovenia bbox and apply QA filtering."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


DEFAULT_LAT_MIN = 45.4
DEFAULT_LAT_MAX = 46.9
DEFAULT_LON_MIN = 13.4
DEFAULT_LON_MAX = 16.6
DEFAULT_QA_THRESHOLD = 0.75
NO2_VARIABLE = "nitrogendioxide_tropospheric_column"
UNIT = "mol/m²"
REQUIRED_VARIABLES = ["latitude", "longitude", NO2_VARIABLE, "qa_value"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crop Sentinel-5P NO2 data to Slovenia bbox and apply QA filter."
    )
    parser.add_argument("--file", required=True, help="Path to Sentinel-5P NO2 .nc file")
    parser.add_argument("--lat-min", type=float, default=DEFAULT_LAT_MIN)
    parser.add_argument("--lat-max", type=float, default=DEFAULT_LAT_MAX)
    parser.add_argument("--lon-min", type=float, default=DEFAULT_LON_MIN)
    parser.add_argument("--lon-max", type=float, default=DEFAULT_LON_MAX)
    parser.add_argument("--qa-threshold", type=float, default=DEFAULT_QA_THRESHOLD)
    parser.add_argument(
        "--output",
        help="Optional JSON or CSV summary output path. Large arrays are not saved.",
    )
    return parser.parse_args()


def validate_inputs(
    file_path: Path,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
) -> None:
    if not file_path.exists():
        raise SystemExit(f"Input file not found: {file_path}")
    if lat_min >= lat_max:
        raise SystemExit("--lat-min must be smaller than --lat-max")
    if lon_min >= lon_max:
        raise SystemExit("--lon-min must be smaller than --lon-max")


def require_variables(dataset: xr.Dataset) -> None:
    missing = [name for name in REQUIRED_VARIABLES if name not in dataset.variables]
    if missing:
        raise SystemExit(f"Missing required NetCDF variables: {', '.join(missing)}")


def calculate_summary(
    file_path: Path,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    qa_threshold: float,
) -> dict[str, Any]:
    with xr.open_dataset(file_path, group="PRODUCT") as dataset:
        require_variables(dataset)

        return calculate_summary_from_arrays(
            input_file=str(file_path),
            latitude=dataset["latitude"].values,
            longitude=dataset["longitude"].values,
            no2=dataset[NO2_VARIABLE].values,
            qa_value=dataset["qa_value"].values,
            lat_min=lat_min,
            lat_max=lat_max,
            lon_min=lon_min,
            lon_max=lon_max,
            qa_threshold=qa_threshold,
        )


def calculate_summary_from_arrays(
    input_file: str,
    latitude: Any,
    longitude: Any,
    no2: Any,
    qa_value: Any,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    qa_threshold: float,
) -> dict[str, Any]:
    latitude_values = np.asarray(latitude)
    longitude_values = np.asarray(longitude)
    no2_values = np.asarray(no2)
    qa_values = np.asarray(qa_value)

    bbox_mask = (
        (latitude_values >= lat_min)
        & (latitude_values <= lat_max)
        & (longitude_values >= lon_min)
        & (longitude_values <= lon_max)
    )
    valid_mask = bbox_mask & (qa_values >= qa_threshold) & np.isfinite(no2_values)
    valid_values = no2_values[valid_mask]
    total_pixels_in_bbox = int(np.count_nonzero(bbox_mask))

    summary: dict[str, Any] = {
        "input_file": input_file,
        "lat_min": lat_min,
        "lat_max": lat_max,
        "lon_min": lon_min,
        "lon_max": lon_max,
        "qa_threshold": qa_threshold,
        "total_pixels_in_bbox_before_qa": total_pixels_in_bbox,
        "valid_pixels_after_qa": int(valid_values.size),
        "unit": UNIT,
    }

    if valid_values.size == 0:
        summary.update(
            {
                "value_mean": None,
                "value_min": None,
                "value_max": None,
            }
        )
        return summary

    summary.update(
        {
            "value_mean": float(np.nanmean(valid_values)),
            "value_min": float(np.nanmin(valid_values)),
            "value_max": float(np.nanmax(valid_values)),
        }
    )
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print("Sentinel-5P NO2 Slovenia crop/filter summary")
    print(f"Input file: {summary['input_file']}")
    print(
        "Bbox: "
        f"lat {summary['lat_min']}-{summary['lat_max']}, "
        f"lon {summary['lon_min']}-{summary['lon_max']}"
    )
    print(f"QA threshold: {summary['qa_threshold']}")
    print(
        "Total pixels in bbox before QA filter: "
        f"{summary['total_pixels_in_bbox_before_qa']}"
    )
    print(f"Valid pixels after QA filter: {summary['valid_pixels_after_qa']}")

    if summary["valid_pixels_after_qa"] == 0:
        print("Mean NO2: n/a")
        print("Min NO2: n/a")
        print("Max NO2: n/a")
    else:
        print(f"Mean NO2: {summary['value_mean']}")
        print(f"Min NO2: {summary['value_min']}")
        print(f"Max NO2: {summary['value_max']}")
    print(f"Unit: {summary['unit']}")


def save_summary(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()

    if suffix == ".json":
        with output_path.open("w", encoding="utf-8") as file_handle:
            json.dump(summary, file_handle, indent=2, ensure_ascii=False)
            file_handle.write("\n")
        return

    if suffix == ".csv":
        with output_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=list(summary.keys()))
            writer.writeheader()
            writer.writerow(summary)
        return

    raise SystemExit("--output must end with .json or .csv")


def main() -> None:
    args = parse_args()
    file_path = Path(args.file)
    validate_inputs(file_path, args.lat_min, args.lat_max, args.lon_min, args.lon_max)

    summary = calculate_summary(
        file_path=file_path,
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
        qa_threshold=args.qa_threshold,
    )
    print_summary(summary)

    if args.output:
        output_path = Path(args.output)
        save_summary(summary, output_path)
        print(f"Summary saved to: {output_path}")


if __name__ == "__main__":
    main()
