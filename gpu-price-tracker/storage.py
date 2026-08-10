"""
Where files go, and the shape of a normalized price row.

Two things are written on every run:

  1. data/raw/<provider>/<provider>-<timestamp>.json.gz
     The provider's response, byte-for-byte, gzipped. Nothing is cleaned,
     dropped or renamed. This is the archive: if a normalization choice
     later turns out to be wrong, every past day can be reprocessed from
     these files.

  2. data/normalized/<timestamp>-<provider>.csv
     One row per price, reduced to USD per GPU per hour.

Filenames carry a full UTC timestamp, so a run never overwrites an earlier
one -- not even a second run on the same day.
"""

import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
NORMALIZED_DIR = ROOT / "data" / "normalized"
DOCS_DIR = ROOT / "docs"

# Columns of the tidy row-per-price file. Order matters: it is the CSV header.
COLUMNS = [
    "snapshot_ts",            # UTC time this run started (identifies the snapshot)
    "provider",               # oracle | azure | gcp
    "provider_last_updated",  # the provider's own freshness stamp, verbatim
    "region",                 # provider region, or "all-commercial" where price is uniform
    "sku_id",                 # provider's stable identifier for the priced item
    "sku_name",               # provider's own name for it, verbatim
    "chip_model",             # e.g. H100 -- BLANK when we could not identify it
    "gpu_count",              # chips per priced unit -- BLANK when unknown
    "price_type",             # on_demand | spot | 1_year | 3_year
    "currency",
    "list_price",             # price exactly as published
    "list_price_unit",        # what that published price is per
    "usd_per_gpu_hour",       # the normalized number -- BLANK if it can't be derived
    # What that number actually covers. Providers itemize differently:
    #   machine_inclusive -- vCPU and RAM are part of the price (Oracle, Azure,
    #                        and Google where a fixed machine shape exists)
    #   accelerator_only  -- the bare chip; Google bills vCPU and RAM apart from
    #                        it, so such a row is NOT comparable to the others
    # Kept as its own field so the page can never compare the two by accident.
    "basis",
    "notes",
]


def utc_now():
    # Truncated to whole seconds on purpose. Filenames carry the timestamp at
    # second resolution, so reprocess.py recovers it from the filename exactly.
    # Keeping microseconds here would make a reprocessed row land on a
    # fractionally different snapshot_ts than the original, and the page would
    # read one run as two separate snapshots.
    return datetime.now(timezone.utc).replace(microsecond=0)


def timestamp_for_filename(dt):
    """2026-08-10T22-33-01Z -- colons are illegal in filenames on Windows."""
    return dt.strftime("%Y-%m-%dT%H-%M-%SZ")


def save_raw(provider, payload, snapshot_ts):
    """Archive the untouched provider response, gzipped and timestamped."""
    out_dir = RAW_DIR / provider
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{provider}-{timestamp_for_filename(snapshot_ts)}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def save_normalized(provider, rows, snapshot_ts):
    """Write the tidy row-per-price file for this run."""
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    path = NORMALIZED_DIR / f"{timestamp_for_filename(snapshot_ts)}-{provider}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in COLUMNS})
    return path


def load_all_normalized():
    """Read every normalized CSV ever written, oldest first."""
    if not NORMALIZED_DIR.exists():
        return []
    rows = []
    for path in sorted(NORMALIZED_DIR.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    return rows
