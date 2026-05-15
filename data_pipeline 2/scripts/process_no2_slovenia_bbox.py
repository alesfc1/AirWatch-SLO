#!/usr/bin/env python3
"""Calculate initial NO2 statistics for pixels inside Slovenia bbox."""

from __future__ import annotations

import argparse

import numpy as np
import xarray as xr


LAT_MIN = 45.4
LAT_MAX = 46.9
LON_MIN = 13.4
LON_MAX = 16.6
QA_MIN = 0.75
NO2_VARIABLE = "nitrogendioxide_tropospheric_column"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to downloaded .nc product")
    args = parser.parse_args()

    with xr.open_dataset(args.file, group="PRODUCT") as dataset:
        required = ["latitude", "longitude", NO2_VARIABLE, "qa_value"]
        missing = [name for name in required if name not in dataset.variables]
        if missing:
            raise SystemExit(f"Missing required variables: {', '.join(missing)}")

        latitude = dataset["latitude"]
        longitude = dataset["longitude"]
        no2 = dataset[NO2_VARIABLE]
        qa_value = dataset["qa_value"]

        mask = (
            (latitude >= LAT_MIN)
            & (latitude <= LAT_MAX)
            & (longitude >= LON_MIN)
            & (longitude <= LON_MAX)
            & (qa_value >= QA_MIN)
            & np.isfinite(no2)
        )
        filtered_no2 = no2.where(mask)
        values = filtered_no2.values
        valid_values = values[np.isfinite(values)]

        print(f"Valid pixel count: {valid_values.size}")
        if valid_values.size == 0:
            print("Mean NO2: n/a")
            print("Min NO2: n/a")
            print("Max NO2: n/a")
            print("Unit: mol/m²")
            return

        print(f"Mean NO2: {float(np.nanmean(valid_values))}")
        print(f"Min NO2: {float(np.nanmin(valid_values))}")
        print(f"Max NO2: {float(np.nanmax(valid_values))}")
        print("Unit: mol/m²")


if __name__ == "__main__":
    main()
