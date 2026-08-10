#!/usr/bin/env python3
"""
Build the page from every snapshot collected so far.

    python3 build_page.py

Writes docs/index.html. The data is embedded inside that file rather than
loaded from a separate data.json, because browsers block a local page from
reading another local file -- a page that fetched its data would come up
empty when opened straight from the file manager. Embedding keeps it a
double-click-and-it-works file with no server.
"""

import json
from collections import defaultdict
from pathlib import Path

import storage

TEMPLATE = Path(__file__).resolve().parent / "page_template.html"

PROVIDER_LABELS = {"oracle": "Oracle", "azure": "Azure", "gcp": "Google Cloud"}
PRICE_TYPE_LABELS = {
    "on_demand": "On-demand",
    "spot": "Spot",
    "1_year": "1-year",
    "3_year": "3-year",
}


def series_key(row):
    """Identifies one price line over time: a SKU at a given price type."""
    return "|".join([row["provider"], row["sku_id"], row["price_type"], row["region"]])


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build():
    rows = storage.load_all_normalized()
    if not rows:
        raise SystemExit("no snapshots yet -- run  python3 collect.py  first")

    snapshots = sorted({r["snapshot_ts"] for r in rows})
    latest, previous = snapshots[-1], (snapshots[-2] if len(snapshots) > 1 else None)

    # Price history per series, used for the charts and the change column.
    history = defaultdict(dict)
    for row in rows:
        price = to_float(row["usd_per_gpu_hour"])
        if price is not None:
            history[series_key(row)][row["snapshot_ts"]] = price

    latest_rows, unpriced = [], []
    provider_last_updated = {}

    for row in rows:
        if row["snapshot_ts"] != latest:
            continue
        provider_last_updated[row["provider"]] = row["provider_last_updated"]

        price = to_float(row["usd_per_gpu_hour"])
        key = series_key(row)

        prior = history[key].get(previous) if previous else None
        change = round(price - prior, 6) if (price is not None and prior is not None) else None
        change_pct = round((price - prior) / prior * 100, 2) if (change is not None and prior) else None

        record = {
            "provider": row["provider"],
            "provider_label": PROVIDER_LABELS.get(row["provider"], row["provider"]),
            "chip": row["chip_model"],
            "sku_id": row["sku_id"],
            "sku_name": row["sku_name"],
            "region": row["region"],
            "price_type": row["price_type"],
            "price_type_label": PRICE_TYPE_LABELS.get(row["price_type"], row["price_type"]),
            "gpu_count": row["gpu_count"],
            "list_price": to_float(row["list_price"]),
            "list_price_unit": row["list_price_unit"],
            "usd_per_gpu_hour": price,
            "change": change,
            "change_pct": change_pct,
            "notes": row["notes"],
            "key": key,
        }
        latest_rows.append(record)
        if price is None:
            unpriced.append(record)

    # Chart data: one chart per chip, one line per provider + price type.
    charts = defaultdict(list)
    for record in latest_rows:
        if not record["chip"] or record["usd_per_gpu_hour"] is None:
            continue
        points = sorted(history[record["key"]].items())
        charts[record["chip"]].append({
            "label": f'{record["provider_label"]} · {record["price_type_label"]}',
            "provider": record["provider"],
            "price_type": record["price_type"],
            "points": [{"ts": ts, "value": value} for ts, value in points],
        })

    payload = {
        "generated_at": storage.utc_now().isoformat(),
        "snapshots": snapshots,
        "latest": latest,
        "previous": previous,
        "provider_last_updated": provider_last_updated,
        "provider_labels": PROVIDER_LABELS,
        "rows": latest_rows,
        "unpriced": unpriced,
        "charts": charts,
    }

    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null",
        json.dumps(payload, separators=(",", ":")),
    )

    storage.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = storage.DOCS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")

    print(f"{len(snapshots)} snapshot(s), latest {latest}")
    print(f"{len(latest_rows)} rows on the latest snapshot "
          f"({len(unpriced)} without a per-GPU-hour figure)")
    if previous is None:
        print("only one snapshot so far -- change column and charts fill in "
              "from the second run onward")
    print(f"wrote {out}")
    print(f"open it with:  file://{out}")


if __name__ == "__main__":
    build()
