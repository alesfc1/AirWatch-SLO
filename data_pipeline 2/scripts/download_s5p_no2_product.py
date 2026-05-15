#!/usr/bin/env python3
"""Download one Sentinel-5P product into data_pipeline/sample_data."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests

from get_copernicus_token import get_access_token


CATALOGUE_PRODUCT_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "sample_data"


def safe_filename(name: str, default_extension: str = ".nc") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not cleaned:
        cleaned = "copernicus_product"
    if not cleaned.endswith((".nc", ".zip")):
        cleaned += default_extension
    return cleaned


def get_product_name(product_id: str, token: str) -> str:
    response = requests.get(
        f"{CATALOGUE_PRODUCT_URL}({product_id})?$select=Name",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("Name") or product_id


def download_product(product_id: str) -> Path:
    token = get_access_token()
    product_name = get_product_name(product_id, token)
    output_path = OUTPUT_DIR / safe_filename(product_name)
    tmp_path = output_path.with_suffix(output_path.suffix + ".part")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers.update({"Authorization": f"Bearer {token}"})
        response = session.get(
            f"{DOWNLOAD_URL}({product_id})/$value",
            stream=True,
            allow_redirects=True,
            timeout=120,
        )
        response.raise_for_status()
        with tmp_path.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)

    tmp_path.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", required=True)
    args = parser.parse_args()

    output_path = download_product(args.product_id)
    print(f"Downloaded product to: {output_path}")


if __name__ == "__main__":
    main()
