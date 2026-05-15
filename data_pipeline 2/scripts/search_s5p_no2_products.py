#!/usr/bin/env python3
"""Search Sentinel-5P NO2 products over Slovenia with CDSE OData."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests


CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
LAT_MIN = 45.4
LAT_MAX = 46.9
LON_MIN = 13.4
LON_MAX = 16.6
SLOVENIA_BBOX_POLYGON = (
    f"POLYGON(({LON_MIN} {LAT_MIN},{LON_MAX} {LAT_MIN},"
    f"{LON_MAX} {LAT_MAX},{LON_MIN} {LAT_MAX},{LON_MIN} {LAT_MIN}))"
)


def parse_date(value: str, end_of_day: bool = False) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if end_of_day and "T" not in value:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999000)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def build_query(start_date: str, end_date: str, top: int) -> str:
    start = parse_date(start_date)
    end = parse_date(end_date, end_of_day=True)
    filters = [
        "Collection/Name eq 'SENTINEL-5P'",
        "contains(Name,'L2__NO2')",
        f"ContentDate/Start ge {start}",
        f"ContentDate/Start le {end}",
        (
            "OData.CSC.Intersects(area=geography'SRID=4326;"
            f"{SLOVENIA_BBOX_POLYGON}')"
        ),
    ]
    params = {
        "$filter": " and ".join(filters),
        "$orderby": "ContentDate/Start desc",
        "$top": str(top),
        "$select": "Id,Name,ContentDate,Online,ContentLength",
    }
    return f"{CATALOGUE_URL}?{urlencode(params)}"


def search_products(start_date: str, end_date: str, top: int) -> list[dict]:
    response = requests.get(build_query(start_date, end_date, top), timeout=60)
    response.raise_for_status()
    return response.json().get("value", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True, help="UTC date, e.g. 2024-01-01")
    parser.add_argument("--end-date", required=True, help="UTC date, e.g. 2024-01-31")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    products = search_products(args.start_date, args.end_date, args.top)
    if not products:
        print("No Sentinel-5P NO2 products found for the given date range.")
        return

    for product in products:
        content_date = product.get("ContentDate") or {}
        print(f"Name: {product.get('Name')}")
        print(f"Product ID: {product.get('Id')}")
        print(f"Start date: {content_date.get('Start')}")
        print(f"End date: {content_date.get('End')}")
        print("")


if __name__ == "__main__":
    main()
