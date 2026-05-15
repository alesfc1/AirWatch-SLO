#!/usr/bin/env python3
"""Validate regional NO2 aggregation output JSON."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Optional


EXPECTED_REGION_COUNT = 12
EXPECTED_UNIT = "mol/m²"
EXPECTED_QA_THRESHOLD = 0.75
ALLOWED_QUALITY_STATUSES = {"valid", "no_valid_pixels", "processing_error"}
REQUIRED_FIELDS = {
    "region_code",
    "region_name",
    "value_mean",
    "value_min",
    "value_max",
    "pixel_count_valid",
    "qa_threshold",
    "quality_status",
    "unit",
    "measurement_start_time",
    "measurement_end_time",
    "source_product_id",
    "source_product_name",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate regional NO2 aggregation output JSON."
    )
    parser.add_argument("--file", required=True, help="Path to regional NO2 JSON output")
    parser.add_argument("--expected-region-count", type=int, default=EXPECTED_REGION_COUNT)
    parser.add_argument("--expected-valid-regions", type=int)
    parser.add_argument("--expected-no-data-regions", type=int)
    parser.add_argument("--expected-assigned-valid-pixels", type=int)
    parser.add_argument("--expected-qa-threshold", type=float, default=EXPECTED_QA_THRESHOLD)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    if not path.exists():
        raise ValueError(f"File does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"File is not valid JSON: {error}") from error


def is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def is_null_or_absent(row: dict[str, Any], field: str) -> bool:
    return field not in row or row[field] is None


def validate_row(row: Any, index: int, expected_qa_threshold: float) -> list[str]:
    errors: list[str] = []
    if not isinstance(row, dict):
        return [f"Row {index} is not an object."]

    missing = sorted(REQUIRED_FIELDS - set(row.keys()))
    if missing:
        errors.append(f"Row {index} is missing required fields: {', '.join(missing)}")
        return errors

    region_label = f"row {index} ({row.get('region_code', '<unknown>')})"

    if not str(row.get("region_code") or "").strip():
        errors.append(f"{region_label}: region_code is empty.")
    if not str(row.get("region_name") or "").strip():
        errors.append(f"{region_label}: region_name is empty.")
    if row.get("unit") != EXPECTED_UNIT:
        errors.append(f"{region_label}: unit must be {EXPECTED_UNIT}.")
    if row.get("qa_threshold") != expected_qa_threshold:
        errors.append(f"{region_label}: qa_threshold must be {expected_qa_threshold}.")

    quality_status = row.get("quality_status")
    if quality_status not in ALLOWED_QUALITY_STATUSES:
        errors.append(
            f"{region_label}: quality_status must be one of "
            f"{', '.join(sorted(ALLOWED_QUALITY_STATUSES))}."
        )

    pixel_count = row.get("pixel_count_valid")
    if (
        not isinstance(pixel_count, int)
        or isinstance(pixel_count, bool)
        or pixel_count < 0
    ):
        errors.append(
            f"{region_label}: pixel_count_valid must be a non-negative integer."
        )

    if quality_status == "valid":
        if isinstance(pixel_count, int) and pixel_count <= 0:
            errors.append(f"{region_label}: valid row must have pixel_count_valid > 0.")
        for field in ("value_mean", "value_min", "value_max"):
            if not is_number(row.get(field)):
                errors.append(f"{region_label}: {field} must be a finite number.")
        if all(
            is_number(row.get(field))
            for field in ("value_mean", "value_min", "value_max")
        ):
            value_min = row["value_min"]
            value_mean = row["value_mean"]
            value_max = row["value_max"]
            if not value_min <= value_mean <= value_max:
                errors.append(
                    f"{region_label}: expected value_min <= value_mean <= value_max."
                )

    if quality_status == "no_valid_pixels":
        if pixel_count != 0:
            errors.append(
                f"{region_label}: no_valid_pixels row must have pixel_count_valid == 0."
            )
        for field in ("value_mean", "value_min", "value_max"):
            if not is_null_or_absent(row, field):
                errors.append(f"{region_label}: {field} must be null or absent.")

    return errors


def validate_output(
    data: Any,
    expected_region_count: int = EXPECTED_REGION_COUNT,
    expected_valid_regions: Optional[int] = None,
    expected_no_data_regions: Optional[int] = None,
    expected_assigned_valid_pixels: Optional[int] = None,
    expected_qa_threshold: float = EXPECTED_QA_THRESHOLD,
) -> tuple[list[str], list[str], dict[str, int]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, list):
        return ["Output JSON must be a list."], warnings, {}

    seen_region_codes: set[str] = set()
    for index, row in enumerate(data):
        errors.extend(validate_row(row, index, expected_qa_threshold))
        if isinstance(row, dict):
            region_code = str(row.get("region_code") or "")
            if region_code in seen_region_codes:
                errors.append(f"Duplicate region_code: {region_code}")
            seen_region_codes.add(region_code)

    valid_regions = sum(
        1 for row in data if isinstance(row, dict) and row.get("quality_status") == "valid"
    )
    no_data_regions = sum(
        1
        for row in data
        if isinstance(row, dict) and row.get("quality_status") == "no_valid_pixels"
    )
    processing_error_regions = sum(
        1
        for row in data
        if isinstance(row, dict) and row.get("quality_status") == "processing_error"
    )
    assigned_valid_pixels = sum(
        row.get("pixel_count_valid", 0)
        for row in data
        if isinstance(row, dict) and row.get("quality_status") == "valid"
    )

    if len(data) != expected_region_count:
        errors.append(f"Expected {expected_region_count} regions, found {len(data)}.")
    if expected_valid_regions is not None and valid_regions != expected_valid_regions:
        errors.append(
            f"Expected {expected_valid_regions} valid regions, found {valid_regions}."
        )
    if (
        expected_no_data_regions is not None
        and no_data_regions != expected_no_data_regions
    ):
        errors.append(
            f"Expected {expected_no_data_regions} no_valid_pixels regions, "
            f"found {no_data_regions}."
        )
    if (
        expected_assigned_valid_pixels is not None
        and assigned_valid_pixels != expected_assigned_valid_pixels
    ):
        errors.append(
            f"Expected {expected_assigned_valid_pixels} assigned valid pixels, "
            f"found {assigned_valid_pixels}."
        )
    if processing_error_regions:
        warnings.append(f"Found {processing_error_regions} processing_error regions.")

    summary = {
        "total_regions": len(data),
        "valid_regions": valid_regions,
        "no_data_regions": no_data_regions,
        "processing_error_regions": processing_error_regions,
        "assigned_valid_pixels": assigned_valid_pixels,
    }
    return errors, warnings, summary


def print_summary(summary: dict[str, int], warnings: list[str], errors: list[str]) -> None:
    print("Regional NO2 output validation summary")
    print(f"Total regions: {summary.get('total_regions', 0)}")
    print(f"Valid regions: {summary.get('valid_regions', 0)}")
    print(f"No-data regions: {summary.get('no_data_regions', 0)}")
    print(f"Processing-error regions: {summary.get('processing_error_regions', 0)}")
    print(f"Total assigned valid pixels: {summary.get('assigned_valid_pixels', 0)}")

    print("Warnings:")
    if warnings:
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("  - none")

    print("Errors:")
    if errors:
        for error in errors:
            print(f"  - {error}")
        print("Validation status: FAIL")
    else:
        print("  - none")
        print("Validation status: PASS")


def main() -> None:
    args = parse_args()
    try:
        data = load_json(Path(args.file))
        errors, warnings, summary = validate_output(
            data,
            expected_region_count=args.expected_region_count,
            expected_valid_regions=args.expected_valid_regions,
            expected_no_data_regions=args.expected_no_data_regions,
            expected_assigned_valid_pixels=args.expected_assigned_valid_pixels,
            expected_qa_threshold=args.expected_qa_threshold,
        )
    except ValueError as error:
        summary = {}
        warnings = []
        errors = [str(error)]

    print_summary(summary, warnings, errors)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
