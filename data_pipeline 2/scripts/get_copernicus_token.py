#!/usr/bin/env python3
"""Request a Copernicus Data Space access token without printing it fully."""

from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)


def load_credentials() -> tuple[str, str]:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")

    username = os.getenv("COPERNICUS_USERNAME")
    password = os.getenv("COPERNICUS_PASSWORD")
    if not username or not password:
        raise SystemExit(
            "Missing COPERNICUS_USERNAME or COPERNICUS_PASSWORD in .env"
        )
    return username, password


def get_access_token() -> str:
    username, password = load_credentials()
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": "cdse-public",
            "username": username,
            "password": password,
            "grant_type": "password",
        },
        timeout=30,
    )
    response.raise_for_status()

    token = response.json().get("access_token")
    if not token:
        raise SystemExit("Token response did not include access_token")
    return token


def preview_token(token: str) -> str:
    if len(token) <= 16:
        return "<token received, too short to preview safely>"
    return f"{token[:8]}...{token[-4:]}"


def main() -> None:
    token = get_access_token()
    print("Copernicus access token received.")
    print(f"Token preview: {preview_token(token)}")
    print("Full token intentionally not printed.")


if __name__ == "__main__":
    main()
