#!/usr/bin/env python3
"""Inspect a GeoJSON boundary file for Slovenian statistical regions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional


def load_geojson(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)
    if data.get("type") != "FeatureCollection":
        raise SystemExit("Expected a GeoJSON FeatureCollection.")
    return data


def get_crs(data: dict[str, Any], path: Path) -> str:
    crs = data.get("crs")
    if isinstance(crs, dict):
        properties = crs.get("properties") or {}
        name = properties.get("name")
        if name:
            return str(name)
    if "4326" in path.name:
        return "EPSG:4326 inferred from filename"
    return "Unknown"


def filter_features(
    features: list[dict[str, Any]],
    country_code: Optional[str],
    level: Optional[int],
) -> list[dict[str, Any]]:
    filtered = features
    if country_code:
        filtered = [
            feature
            for feature in filtered
            if feature.get("properties", {}).get("CNTR_CODE") == country_code
        ]
    if level is not None:
        filtered = [
            feature
            for feature in filtered
            if str(feature.get("properties", {}).get("LEVL_CODE")) == str(level)
        ]
    return filtered


def collect_columns(features: list[dict[str, Any]]) -> list[str]:
    columns: set[str] = set()
    for feature in features:
        columns.update((feature.get("properties") or {}).keys())
    return sorted(columns)


def region_name(properties: dict[str, Any]) -> str:
    return str(
        properties.get("NUTS_NAME")
        or properties.get("NAME_LATN")
        or properties.get("name")
        or "<missing name>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to GeoJSON boundary file")
    parser.add_argument("--country-code", default="SI", help="Country code filter")
    parser.add_argument("--level", type=int, default=3, help="NUTS level filter")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"Boundary file not found: {path}")

    data = load_geojson(path)
    all_features = data.get("features") or []
    features = filter_features(all_features, args.country_code, args.level)
    columns = collect_columns(features)
    crs = get_crs(data, path)
    geometries_present = all(feature.get("geometry") for feature in features)

    print(f"File: {path}")
    print(f"All features in file: {len(all_features)}")
    print(f"Filtered features: {len(features)}")
    print(f"Country code filter: {args.country_code}")
    print(f"Level filter: {args.level}")
    print(f"CRS: {crs}")
    print(f"CRS is EPSG:4326: {'yes' if '4326' in crs else 'check needed'}")
    print(f"All filtered features have geometry: {'yes' if geometries_present else 'no'}")
    print("Available attribute columns:")
    for column in columns:
        print(f"  - {column}")

    print("Region names:")
    for feature in features:
        properties = feature.get("properties") or {}
        code = properties.get("NUTS_ID") or properties.get("id") or "<missing code>"
        print(f"  - {code}: {region_name(properties)}")

    if args.country_code == "SI" and args.level == 3 and len(features) != 12:
        print("Warning: expected 12 Slovenian NUTS3/statistical regions.")


if __name__ == "__main__":
    main()
