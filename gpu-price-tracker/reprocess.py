#!/usr/bin/env python3
"""
Rebuild the tidy files from the archived raw responses.

    python3 reprocess.py            # preview what would change
    python3 reprocess.py --write    # actually rewrite them

This is the payoff for archiving raw responses. If a normalization choice
turns out to be wrong -- a chip mapped to the wrong name, a filter that let
something through, a GPU count corrected -- fix the provider file and run
this. Every past day is recomputed from the original bytes. The raw archive
itself is never touched.

The snapshot timestamp is recovered from the raw filename, so reprocessed
rows land on exactly the same dates as the originals.
"""

import argparse
import gzip
import json
import re
from datetime import datetime, timezone

import storage
from providers import azure, gcp, oracle

NORMALIZERS = {
    "oracle": oracle.normalize,
    "azure": azure.normalize,
    "gcp": gcp.normalize,
}

STAMP = re.compile(r"-(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})Z\.json\.gz$")


def snapshot_ts_from_path(path):
    """oracle-2026-08-10T22-36-10Z.json.gz -> aware datetime."""
    match = STAMP.search(path.name)
    if not match:
        raise ValueError(f"cannot read a timestamp from {path.name}")
    date, hh, mm, ss = match.groups()
    return datetime.fromisoformat(f"{date}T{hh}:{mm}:{ss}").replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true",
                        help="rewrite the normalized files (default is a preview)")
    parser.add_argument("providers", nargs="*", default=None)
    args = parser.parse_args()

    wanted = args.providers or list(NORMALIZERS)
    total = 0

    for provider in wanted:
        normalize = NORMALIZERS[provider]
        raw_files = sorted((storage.RAW_DIR / provider).glob("*.json.gz"))
        if not raw_files:
            print(f"[{provider}] no raw archives found")
            continue

        for path in raw_files:
            snapshot_ts = snapshot_ts_from_path(path)
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)

            rows, unmapped = normalize(payload, snapshot_ts)
            priced = sum(1 for r in rows if r["usd_per_gpu_hour"] != "")
            total += len(rows)

            action = "rewrote" if args.write else "would write"
            if args.write:
                storage.save_normalized(provider, rows, snapshot_ts)

            print(f"[{provider}] {path.name}: {action} {len(rows)} rows "
                  f"({priced} priced, {len(unmapped)} unmapped)")

    if not args.write:
        print(f"\npreview only -- {total} row(s) would be written. "
              f"re-run with --write to apply, then rebuild the page.")
    else:
        print(f"\n{total} row(s) rewritten. run  python3 build_page.py  next.")


if __name__ == "__main__":
    main()
