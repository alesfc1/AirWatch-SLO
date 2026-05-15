#!/usr/bin/env python3
"""Inspect the PRODUCT group in a Sentinel-5P NO2 NetCDF file."""

from __future__ import annotations

import argparse

import xarray as xr


REQUIRED_VARIABLES = {
    "latitude",
    "longitude",
    "nitrogendioxide_tropospheric_column",
    "qa_value",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to downloaded .nc product")
    args = parser.parse_args()

    with xr.open_dataset(args.file, group="PRODUCT") as dataset:
        print("Dimensions:")
        for name, size in dataset.sizes.items():
            print(f"  {name}: {size}")

        print("\nCoordinates:")
        for name in dataset.coords:
            print(f"  {name}")

        print("\nData variables:")
        for name in dataset.data_vars:
            print(f"  {name}")

        available = set(dataset.variables)
        print("\nRequired variable check:")
        for variable in sorted(REQUIRED_VARIABLES):
            status = "OK" if variable in available else "MISSING"
            print(f"  {variable}: {status}")


if __name__ == "__main__":
    main()
