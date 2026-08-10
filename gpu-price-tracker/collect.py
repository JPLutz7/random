#!/usr/bin/env python3
"""
Take a price snapshot. Run this once a day.

    python3 collect.py

Every run archives each provider's untouched response and writes a tidy
row-per-price file. Nothing is ever overwritten, so the history builds up
day by day.
"""

import sys

import storage
from providers import oracle

PROVIDERS = {
    "oracle": (oracle.fetch, oracle.normalize),
}


def collect_one(name, snapshot_ts):
    fetch, normalize = PROVIDERS[name]

    print(f"[{name}] fetching...")
    payload = fetch()

    raw_path = storage.save_raw(name, payload, snapshot_ts)
    print(f"[{name}] raw archived  -> {raw_path.relative_to(storage.ROOT)}")

    rows, unmapped = normalize(payload, snapshot_ts)
    csv_path = storage.save_normalized(name, rows, snapshot_ts)
    print(f"[{name}] {len(rows)} price rows -> {csv_path.relative_to(storage.ROOT)}")

    priced = [r for r in rows if r["usd_per_gpu_hour"] != ""]
    print(f"[{name}] {len(priced)} rows have a per-GPU-hour figure, "
          f"{len(rows) - len(priced)} left blank")

    if unmapped:
        print(f"[{name}] {len(unmapped)} SKU(s) with no chip mapping "
              f"(price recorded, per-GPU figure left blank):")
        for entry in unmapped:
            print(f"           {entry['sku_id']:10s} {entry['sku_name']}  "
                  f"(${entry['list_price']}/GPU/hr)")

    return rows


def main(argv):
    wanted = argv[1:] or list(PROVIDERS)
    unknown = [name for name in wanted if name not in PROVIDERS]
    if unknown:
        print(f"unknown provider(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(PROVIDERS)}", file=sys.stderr)
        return 2

    snapshot_ts = storage.utc_now()
    print(f"snapshot {snapshot_ts.isoformat()}\n")

    failures = []
    for name in wanted:
        try:
            collect_one(name, snapshot_ts)
        except Exception as exc:                      # noqa: BLE001
            # One provider being down must not lose the others' snapshot.
            failures.append(name)
            print(f"[{name}] FAILED: {exc}", file=sys.stderr)
        print()

    if failures:
        print(f"finished with failures: {', '.join(failures)}", file=sys.stderr)
        return 1

    print("done. run  python3 build_page.py  to refresh the page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
