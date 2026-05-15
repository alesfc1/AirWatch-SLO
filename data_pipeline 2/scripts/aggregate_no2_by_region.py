#!/usr/bin/env python3
"""Aggregate Sentinel-5P NO2 point pixels by Slovenian NUTS3 regions."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import xarray as xr


DEFAULT_LAT_MIN = 45.4
DEFAULT_LAT_MAX = 46.9
DEFAULT_LON_MIN = 13.4
DEFAULT_LON_MAX = 16.6
DEFAULT_QA_THRESHOLD = 0.75
DEFAULT_OUTPUT = "data_pipeline/outputs/no2_by_region/regional_no2_results.json"
NO2_VARIABLE = "nitrogendioxide_tropospheric_column"
UNIT = "mol/m²"
REQUIRED_NETCDF_VARIABLES = ["latitude", "longitude", NO2_VARIABLE, "qa_value"]
TIME_ATTRIBUTE_PAIRS = [
    ("time_coverage_start", "time_coverage_end"),
    ("sensing_start_at", "sensing_end_at"),
    ("sensing_start", "sensing_end"),
    ("start_time", "stop_time"),
]
FILENAME_TIME_PATTERN = re.compile(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate valid Sentinel-5P NO2 pixels by Slovenian NUTS3 region."
    )
    parser.add_argument("--no2-file", required=True, help="Path to Sentinel-5P NO2 .nc file")
    parser.add_argument("--regions-file", required=True, help="Path to NUTS3 GeoJSON file")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="JSON or CSV output path")
    parser.add_argument("--qa-threshold", type=float, default=DEFAULT_QA_THRESHOLD)
    parser.add_argument("--lat-min", type=float, default=DEFAULT_LAT_MIN)
    parser.add_argument("--lat-max", type=float, default=DEFAULT_LAT_MAX)
    parser.add_argument("--lon-min", type=float, default=DEFAULT_LON_MIN)
    parser.add_argument("--lon-max", type=float, default=DEFAULT_LON_MAX)
    parser.add_argument(
        "--source-product-id",
        help="Optional Copernicus product UUID. If omitted, output value is null.",
    )
    parser.add_argument(
        "--source-product-name",
        help="Optional source product filename. Defaults to --no2-file basename.",
    )
    parser.add_argument(
        "--measurement-start-time",
        help="Optional measurement start time in ISO 8601 format.",
    )
    parser.add_argument(
        "--measurement-end-time",
        help="Optional measurement end time in ISO 8601 format.",
    )
    return parser.parse_args()


def validate_file(path: Path, label: str) -> None:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")


def validate_bbox(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> None:
    if lat_min >= lat_max:
        raise SystemExit("--lat-min must be smaller than --lat-max")
    if lon_min >= lon_max:
        raise SystemExit("--lon-min must be smaller than --lon-max")


def load_geojson(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)
    if data.get("type") != "FeatureCollection":
        raise SystemExit("Regions file must be a GeoJSON FeatureCollection.")
    validate_geojson_crs(data, path)
    return data


def validate_geojson_crs(data: dict[str, Any], path: Path) -> None:
    crs = data.get("crs")
    if not crs:
        if "4326" not in path.name:
            print(
                "Warning: GeoJSON has no CRS metadata. Assuming EPSG:4326 because "
                "GeoJSON coordinates are expected to be WGS84.",
                file=sys.stderr,
            )
        return

    properties = crs.get("properties") or {}
    crs_name = str(properties.get("name") or "").upper()
    if "4326" in crs_name or "CRS84" in crs_name:
        return

    raise SystemExit(
        f"Regions file CRS must be EPSG:4326/WGS84. Found: {properties.get('name')}"
    )


def region_name(properties: dict[str, Any]) -> str:
    name = properties.get("NUTS_NAME") or properties.get("NAME_LATN")
    if not name:
        raise SystemExit("Region feature is missing NUTS_NAME and NAME_LATN.")
    return str(name)


def load_slovenian_regions(path: Path) -> list[dict[str, Any]]:
    data = load_geojson(path)
    regions: list[dict[str, Any]] = []

    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        if properties.get("CNTR_CODE") != "SI":
            continue
        if str(properties.get("LEVL_CODE")) != "3":
            continue

        region_code = properties.get("NUTS_ID")
        geometry = feature.get("geometry")
        if not region_code:
            raise SystemExit("Region feature is missing NUTS_ID.")
        if not geometry:
            raise SystemExit(f"Region {region_code} is missing geometry.")

        regions.append(
            {
                "region_code": str(region_code),
                "region_name": region_name(properties),
                "geometry": geometry,
                "values": [],
            }
        )

    regions.sort(key=lambda item: item["region_code"])
    if len(regions) != 12:
        raise SystemExit(
            f"Expected 12 Slovenian NUTS3 regions, found {len(regions)}."
        )
    return regions


def require_netcdf_variables(dataset: xr.Dataset) -> None:
    missing = [
        name for name in REQUIRED_NETCDF_VARIABLES if name not in dataset.variables
    ]
    if missing:
        raise SystemExit(f"Missing required NetCDF variables: {', '.join(missing)}")


def load_valid_pixels(
    no2_file: Path,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    qa_threshold: float,
) -> tuple[list[tuple[float, float, float]], int, int]:
    with xr.open_dataset(no2_file, group="PRODUCT") as dataset:
        require_netcdf_variables(dataset)

        latitude = dataset["latitude"]
        longitude = dataset["longitude"]
        no2 = dataset[NO2_VARIABLE]
        qa_value = dataset["qa_value"]

        bbox_mask = (
            (latitude >= lat_min)
            & (latitude <= lat_max)
            & (longitude >= lon_min)
            & (longitude <= lon_max)
        )
        valid_mask = bbox_mask & (qa_value >= qa_threshold) & np.isfinite(no2)

        total_pixels_in_bbox = int(bbox_mask.sum().values)
        lat_values = latitude.where(valid_mask).values
        lon_values = longitude.where(valid_mask).values
        no2_values = no2.where(valid_mask).values
        valid_positions = np.isfinite(no2_values)

        pixels = [
            (
                float(lon_values[index]),
                float(lat_values[index]),
                float(no2_values[index]),
            )
            for index in zip(*np.where(valid_positions))
        ]

    return pixels, total_pixels_in_bbox, len(pixels)


def normalize_iso_time(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("time value is empty")

    parsed_value = cleaned.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(parsed_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def compact_time_to_iso(value: str) -> str:
    parsed = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def extract_times_from_filename(product_name: str) -> tuple[Optional[str], Optional[str]]:
    match = FILENAME_TIME_PATTERN.search(product_name)
    if not match:
        return None, None
    return compact_time_to_iso(match.group(1)), compact_time_to_iso(match.group(2))


def extract_times_from_netcdf(no2_file: Path) -> tuple[Optional[str], Optional[str]]:
    attrs: dict[str, Any] = {}
    for group in (None, "PRODUCT"):
        try:
            open_kwargs = {"group": group} if group else {}
            with xr.open_dataset(no2_file, **open_kwargs) as dataset:
                attrs.update(dataset.attrs)
        except (OSError, ValueError):
            continue

    for start_key, end_key in TIME_ATTRIBUTE_PAIRS:
        start_value = attrs.get(start_key)
        end_value = attrs.get(end_key)
        if start_value and end_value:
            try:
                return normalize_iso_time(str(start_value)), normalize_iso_time(str(end_value))
            except ValueError:
                continue

    return None, None


def resolve_processing_metadata(
    no2_file: Path,
    source_product_id: Optional[str],
    source_product_name: Optional[str],
    measurement_start_time: Optional[str],
    measurement_end_time: Optional[str],
) -> dict[str, Optional[str]]:
    product_name = source_product_name or no2_file.name

    start_time = (
        normalize_iso_time(measurement_start_time)
        if measurement_start_time
        else None
    )
    end_time = normalize_iso_time(measurement_end_time) if measurement_end_time else None

    if not start_time or not end_time:
        netcdf_start, netcdf_end = extract_times_from_netcdf(no2_file)
        start_time = start_time or netcdf_start
        end_time = end_time or netcdf_end

    if not start_time or not end_time:
        filename_start, filename_end = extract_times_from_filename(product_name)
        start_time = start_time or filename_start
        end_time = end_time or filename_end

    if not start_time or not end_time:
        raise SystemExit(
            "Could not determine measurement start/end time. Provide "
            "--measurement-start-time and --measurement-end-time."
        )

    return {
        "source_product_id": source_product_id,
        "source_product_name": product_name,
        "measurement_start_time": start_time,
        "measurement_end_time": end_time,
    }


def point_on_segment(
    point_lon: float,
    point_lat: float,
    start: list[float],
    end: list[float],
    epsilon: float = 1e-12,
) -> bool:
    x1, y1 = float(start[0]), float(start[1])
    x2, y2 = float(end[0]), float(end[1])
    cross = (point_lat - y1) * (x2 - x1) - (point_lon - x1) * (y2 - y1)
    if abs(cross) > epsilon:
        return False

    return (
        min(x1, x2) - epsilon <= point_lon <= max(x1, x2) + epsilon
        and min(y1, y2) - epsilon <= point_lat <= max(y1, y2) + epsilon
    )


def point_in_ring(point_lon: float, point_lat: float, ring: list[list[float]]) -> bool:
    inside = False
    point_count = len(ring)
    if point_count < 4:
        return False

    for index in range(point_count - 1):
        start = ring[index]
        end = ring[index + 1]
        if point_on_segment(point_lon, point_lat, start, end):
            return True

        x1, y1 = float(start[0]), float(start[1])
        x2, y2 = float(end[0]), float(end[1])
        intersects = (y1 > point_lat) != (y2 > point_lat)
        if intersects:
            x_at_lat = (x2 - x1) * (point_lat - y1) / (y2 - y1) + x1
            if point_lon < x_at_lat:
                inside = not inside
    return inside


def point_in_polygon(point_lon: float, point_lat: float, polygon: list[Any]) -> bool:
    exterior = polygon[0]
    holes = polygon[1:]
    if not point_in_ring(point_lon, point_lat, exterior):
        return False
    return not any(point_in_ring(point_lon, point_lat, hole) for hole in holes)


def point_in_geometry(point_lon: float, point_lat: float, geometry: dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    if geometry_type == "Polygon":
        return point_in_polygon(point_lon, point_lat, coordinates)
    if geometry_type == "MultiPolygon":
        return any(
            point_in_polygon(point_lon, point_lat, polygon)
            for polygon in coordinates
        )
    raise SystemExit(f"Unsupported geometry type: {geometry_type}")


def assign_pixels_to_regions(
    pixels: list[tuple[float, float, float]],
    regions: list[dict[str, Any]],
) -> int:
    unassigned_count = 0
    for lon, lat, value in pixels:
        assigned = False
        for region in regions:
            if point_in_geometry(lon, lat, region["geometry"]):
                region["values"].append(value)
                assigned = True
                break
        if not assigned:
            unassigned_count += 1
    return unassigned_count


def build_region_result(
    region: dict[str, Any],
    qa_threshold: float,
    source_product_id: Optional[str],
    source_product_name: str,
    measurement_start_time: Optional[str] = None,
    measurement_end_time: Optional[str] = None,
) -> dict[str, Any]:
    values = np.array(region["values"], dtype=float)

    if values.size == 0:
        return {
            "region_code": region["region_code"],
            "region_name": region["region_name"],
            "value_mean": None,
            "value_min": None,
            "value_max": None,
            "pixel_count_valid": 0,
            "qa_threshold": qa_threshold,
            "quality_status": "no_valid_pixels",
            "unit": UNIT,
            "measurement_start_time": measurement_start_time,
            "measurement_end_time": measurement_end_time,
            "source_product_id": source_product_id,
            "source_product_name": source_product_name,
        }

    return {
        "region_code": region["region_code"],
        "region_name": region["region_name"],
        "value_mean": float(np.nanmean(values)),
        "value_min": float(np.nanmin(values)),
        "value_max": float(np.nanmax(values)),
        "pixel_count_valid": int(values.size),
        "qa_threshold": qa_threshold,
        "quality_status": "valid",
        "unit": UNIT,
        "measurement_start_time": measurement_start_time,
        "measurement_end_time": measurement_end_time,
        "source_product_id": source_product_id,
        "source_product_name": source_product_name,
    }


def build_results(
    regions: list[dict[str, Any]],
    qa_threshold: float,
    source_product_id: Optional[str],
    source_product_name: str,
    measurement_start_time: Optional[str] = None,
    measurement_end_time: Optional[str] = None,
) -> list[dict[str, Any]]:
    return [
        build_region_result(
            region=region,
            qa_threshold=qa_threshold,
            source_product_id=source_product_id,
            source_product_name=source_product_name,
            measurement_start_time=measurement_start_time,
            measurement_end_time=measurement_end_time,
        )
        for region in regions
    ]


def save_results(results: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()

    if suffix == ".json":
        with output_path.open("w", encoding="utf-8") as file_handle:
            json.dump(results, file_handle, indent=2, ensure_ascii=False)
            file_handle.write("\n")
        return

    if suffix == ".csv":
        fieldnames = list(results[0].keys()) if results else []
        with output_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        return

    raise SystemExit("--output must end with .json or .csv")


def print_summary(
    region_count: int,
    total_pixels_in_bbox: int,
    valid_pixels_after_qa: int,
    unassigned_pixels: int,
    results: list[dict[str, Any]],
    output_path: Path,
    metadata: dict[str, Optional[str]],
) -> None:
    regions_with_valid_data = sum(
        1 for result in results if result["quality_status"] == "valid"
    )
    regions_without_valid_data = sum(
        1 for result in results if result["quality_status"] == "no_valid_pixels"
    )

    print("Sentinel-5P NO2 regional aggregation summary")
    print(f"Slovenian regions loaded: {region_count}")
    print(f"Total pixels in bbox before QA filter: {total_pixels_in_bbox}")
    print(f"Valid pixels after QA filter: {valid_pixels_after_qa}")
    print(f"Valid pixels assigned to regions: {valid_pixels_after_qa - unassigned_pixels}")
    print(f"Valid pixels outside all regions: {unassigned_pixels}")
    print(f"Regions with valid data: {regions_with_valid_data}")
    print(f"Regions with no valid pixels: {regions_without_valid_data}")
    print(f"Source product ID: {metadata.get('source_product_id') or 'n/a'}")
    print(f"Source product name: {metadata.get('source_product_name')}")
    print(f"Measurement start time: {metadata.get('measurement_start_time')}")
    print(f"Measurement end time: {metadata.get('measurement_end_time')}")
    print(f"Output path: {output_path}")


def main() -> None:
    args = parse_args()
    no2_file = Path(args.no2_file)
    regions_file = Path(args.regions_file)
    output_path = Path(args.output)

    validate_file(no2_file, "NO2 file")
    validate_file(regions_file, "Regions file")
    validate_bbox(args.lat_min, args.lat_max, args.lon_min, args.lon_max)

    regions = load_slovenian_regions(regions_file)
    pixels, total_pixels_in_bbox, valid_pixels_after_qa = load_valid_pixels(
        no2_file=no2_file,
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
        qa_threshold=args.qa_threshold,
    )
    metadata = resolve_processing_metadata(
        no2_file=no2_file,
        source_product_id=args.source_product_id,
        source_product_name=args.source_product_name,
        measurement_start_time=args.measurement_start_time,
        measurement_end_time=args.measurement_end_time,
    )
    unassigned_pixels = assign_pixels_to_regions(pixels, regions)
    results = build_results(
        regions=regions,
        qa_threshold=args.qa_threshold,
        source_product_id=metadata["source_product_id"],
        source_product_name=metadata["source_product_name"],
        measurement_start_time=metadata["measurement_start_time"],
        measurement_end_time=metadata["measurement_end_time"],
    )
    save_results(results, output_path)
    print_summary(
        region_count=len(regions),
        total_pixels_in_bbox=total_pixels_in_bbox,
        valid_pixels_after_qa=valid_pixels_after_qa,
        unassigned_pixels=unassigned_pixels,
        results=results,
        output_path=output_path,
        metadata=metadata,
    )


if __name__ == "__main__":
    main()
