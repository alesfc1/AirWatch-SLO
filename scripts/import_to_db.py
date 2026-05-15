#!/usr/bin/env python3
import os
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import psycopg2


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def env(name: str, default: str) -> str:
  return os.getenv(name, os.getenv(name.replace("DATABASE_", "POSTGRES_"), default))


def connect_with_retry():
  params = {
    "host": env("DATABASE_HOST", "127.0.0.1"),
    "port": env("DATABASE_PORT", "5433"),
    "database": env("DATABASE_NAME", "airwatch"),
    "user": env("DATABASE_USER", "airwatch"),
    "password": env("DATABASE_PASSWORD", "airwatch"),
  }

  last_error = None
  for _ in range(30):
    try:
      return psycopg2.connect(**params)
    except psycopg2.OperationalError as exc:
      last_error = exc
      time.sleep(1)

  raise last_error


def load_data() -> gpd.GeoDataFrame:
  data = pd.read_csv(PROJECT_ROOT / "outputs" / "final_v2.csv")
  data = data.loc[:, ~data.columns.str.startswith("Unnamed")]
  data = data.rename(columns={
    "NUTS_ID": "nuts_id",
    "NO2": "no2",
    "GDP_per_capita": "gdp_per_ca",
    "O3_quality": "o3_quality",
    "CO_quality": "co_quality",
    "NO2_quality": "no2_qualit",
    "SO2_quality": "so2_qualit",
    "PM25_quality": "pm25_quali",
    "HCHO_quality": "hcho_quali",
    "Index": "index",
    "Country": "country",
    "Air_Inequity_Index": "air_inequi",
  })

  shapes = gpd.read_file(PROJECT_ROOT / "shapefiles" / "NUTS_SL_01m_2024.shp")
  shapes = shapes.to_crs(epsg=4326)
  shapes = shapes[["NUTS_ID", "NUTS_NAME", "geometry"]].rename(columns={
    "NUTS_ID": "nuts_id",
    "NUTS_NAME": "nuts_name",
  })

  return gpd.GeoDataFrame(data.merge(shapes, on="nuts_id", how="left"), geometry="geometry", crs=shapes.crs)


def value(row, key):
  item = row.get(key)
  if pd.isna(item):
    return None
  return item


def import_data():
  gdf = load_data()
  rows = []

  for _, row in gdf.iterrows():
    rows.append((
      value(row, "nuts_id"),
      value(row, "nuts_name"),
      int(value(row, "year")),
      int(value(row, "month")),
      value(row, "no2"),
      value(row, "gdp_per_ca"),
      value(row, "o3_quality"),
      value(row, "co_quality"),
      value(row, "no2_qualit"),
      value(row, "so2_qualit"),
      value(row, "pm25_quali"),
      value(row, "hcho_quali"),
      value(row, "index"),
      value(row, "country"),
      value(row, "air_inequi"),
      row.geometry.wkt if row.geometry is not None else None,
    ))

  with connect_with_retry() as conn:
    with conn.cursor() as cur:
      cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
      cur.execute("DROP TABLE IF EXISTS final;")
      cur.execute("""
        CREATE TABLE final (
          id SERIAL PRIMARY KEY,
          nuts_id TEXT NOT NULL,
          nuts_name TEXT,
          year INTEGER NOT NULL,
          month INTEGER NOT NULL,
          no2 DOUBLE PRECISION,
          gdp_per_ca DOUBLE PRECISION,
          o3_quality INTEGER,
          co_quality INTEGER,
          no2_qualit INTEGER,
          so2_qualit INTEGER,
          pm25_quali INTEGER,
          hcho_quali INTEGER,
          index DOUBLE PRECISION,
          country TEXT,
          air_inequi DOUBLE PRECISION,
          geom geometry(Geometry, 4326)
        );
      """)
      cur.executemany("""
        INSERT INTO final (
          nuts_id,
          nuts_name,
          year,
          month,
          no2,
          gdp_per_ca,
          o3_quality,
          co_quality,
          no2_qualit,
          so2_qualit,
          pm25_quali,
          hcho_quali,
          index,
          country,
          air_inequi,
          geom
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326));
      """, rows)
      cur.execute("CREATE INDEX final_geom_idx ON final USING GIST (geom);")
      cur.execute("CREATE INDEX final_region_time_idx ON final (nuts_id, year, month);")
    conn.commit()

  print(f"Imported {len(rows)} rows into PostGIS table final.")


if __name__ == "__main__":
  import_data()
