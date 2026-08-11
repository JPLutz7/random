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
    "1_year": "1-year reserved",
    "3_year": "3-year reserved",
    "5_year": "5-year reserved",
    "savings_plan_1_year": "1-year savings plan",
    "savings_plan_3_year": "3-year savings plan",
}

# Controls the order price types appear in the dropdowns.
PRICE_TYPE_ORDER = list(PRICE_TYPE_LABELS)


def series_key(row):
    """Identifies one price line over time: a SKU at a price type in a region."""
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

    # Each provider is tracked on its own clock rather than one global snapshot.
    # Providers get collected at different moments and can fail independently,
    # so pinning the page to a single latest timestamp would silently drop
    # every provider that was not part of the most recent run.
    provider_snapshots = defaultdict(set)
    for row in rows:
        provider_snapshots[row["provider"]].add(row["snapshot_ts"])
    provider_latest = {p: max(ts) for p, ts in provider_snapshots.items()}
    provider_previous = {
        p: (sorted(ts)[-2] if len(ts) > 1 else None) for p, ts in provider_snapshots.items()
    }

    latest = max(provider_latest.values())
    previous = max([p for p in provider_previous.values() if p], default=None)

    # Price history per series, used for the change column.
    history = defaultdict(dict)
    for row in rows:
        price = to_float(row["usd_per_gpu_hour"])
        if price is not None:
            history[series_key(row)][row["snapshot_ts"]] = price

    latest_rows, unpriced = [], {}
    provider_last_updated = {}

    for row in rows:
        if row["snapshot_ts"] != provider_latest[row["provider"]]:
            continue
        # Oracle stamps the whole feed; Azure stamps each row. Keeping the most
        # recent value gives the freshest date the provider itself vouches for.
        stamp = row["provider_last_updated"]
        if stamp > provider_last_updated.get(row["provider"], ""):
            provider_last_updated[row["provider"]] = stamp

        price = to_float(row["usd_per_gpu_hour"])
        key = series_key(row)

        # Compared against that provider's own previous snapshot, not a global one.
        prior_ts = provider_previous[row["provider"]]
        prior = history[key].get(prior_ts) if prior_ts else None
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
            "basis": row.get("basis", ""),
            "change": change,
            "change_pct": change_pct,
            "notes": row["notes"],
            "key": key,
        }
        latest_rows.append(record)

        if price is None:
            # One entry per SKU, not per price type -- Azure produces up to
            # seven rows for the same unrecognized machine.
            unpriced.setdefault((row["provider"], row["sku_id"]), {
                "provider": row["provider"],
                "provider_label": record["provider_label"],
                "sku_id": row["sku_id"],
                "sku_name": row["sku_name"],
                "list_price": record["list_price"],
                "list_price_unit": row["list_price_unit"],
                "notes": row["notes"],
            })

    # ---------------------------------------------------------------------
    # Chart data
    # ---------------------------------------------------------------------
    # Azure sells the same chip in several machine sizes, so charting every
    # SKU would put 20+ lines on one chart. Each line here is instead the
    # CHEAPEST per-GPU-hour that provider offers for that chip at that price
    # type -- one line per provider, and the SKU behind it is named in the
    # tooltip so the number stays traceable.
    # A bare-accelerator price and a whole-machine price are different
    # measurements, so they are kept as separate lines. Putting Google's
    # chip-only T4 on the same line as Azure's full-machine T4 would look like
    # a price comparison and be nothing of the kind.
    best = defaultdict(dict)   # (chip, price_type, provider, basis) -> {ts: (...)}
    for row in rows:
        price = to_float(row["usd_per_gpu_hour"])
        if price is None or not row["chip_model"]:
            continue
        basis = row.get("basis", "")
        bucket = best[(row["chip_model"], row["price_type"], row["provider"], basis)]
        current = bucket.get(row["snapshot_ts"])
        if current is None or price < current[0]:
            bucket[row["snapshot_ts"]] = (price, row["sku_name"], row["region"])

    charts = defaultdict(lambda: defaultdict(list))
    for (chip, price_type, provider, basis), by_ts in best.items():
        label = PROVIDER_LABELS.get(provider, provider)
        if basis == "accelerator_only":
            label += " (chip only)"
        charts[chip][price_type].append({
            "provider": provider,
            "label": label,
            "basis": basis,
            "points": [
                {"ts": ts, "value": v, "sku": sku, "region": region}
                for ts, (v, sku, region) in sorted(by_ts.items())
            ],
        })

    price_types_present = [t for t in PRICE_TYPE_ORDER
                           if any(r["price_type"] == t for r in latest_rows)]
    price_types_present += sorted({r["price_type"] for r in latest_rows}
                                  - set(price_types_present))

    # The page is organised by provider, so each one carries its own header
    # facts: when it was pulled, the freshness date it vouches for itself, how
    # much of it landed, and which of its SKUs were left blank. Attributing the
    # blanks to the provider they came from is the point -- in one flat list,
    # 64 unrecognized SKUs read as one big failure rather than three separate
    # and quite different ones.
    provider_blocks = []
    for key in sorted(provider_latest, key=lambda p: PROVIDER_LABELS.get(p, p)):
        own = [r for r in latest_rows if r["provider"] == key]
        priced_rows = [r for r in own if r["usd_per_gpu_hour"] is not None]
        provider_blocks.append({
            "key": key,
            "label": PROVIDER_LABELS.get(key, key),
            "pulled": provider_latest[key],
            "stated": provider_last_updated.get(key, ""),
            "row_count": len(own),
            "priced_count": len(priced_rows),
            "chips": sorted({r["chip"] for r in priced_rows if r["chip"]}),
            "regions": sorted({r["region"] for r in own}),
            "price_types": [t for t in price_types_present
                            if any(r["price_type"] == t for r in own)],
            "unpriced": [u for u in unpriced.values() if u["provider"] == key],
        })

    payload = {
        "generated_at": storage.utc_now().isoformat(),
        "snapshots": snapshots,
        "latest": latest,
        "previous": previous,
        "provider_last_updated": provider_last_updated,
        "provider_latest": provider_latest,
        "provider_labels": PROVIDER_LABELS,
        "providers": provider_blocks,
        "price_type_labels": PRICE_TYPE_LABELS,
        "price_types": price_types_present,
        "rows": latest_rows,
        "unpriced": sorted(unpriced.values(), key=lambda r: (r["provider_label"], r["sku_id"])),
        "charts": charts,
    }

    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "/*__DATA__*/null",
        json.dumps(payload, separators=(",", ":")),
    )

    storage.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = storage.DOCS_DIR / "index.html"
    out.write_text(html, encoding="utf-8")

    priced = sum(1 for r in latest_rows if r["usd_per_gpu_hour"] is not None)
    print(f"{len(snapshots)} snapshot(s), latest {latest}")
    print(f"{len(latest_rows)} rows ({priced} with a per-GPU-hour figure, "
          f"{len(payload['unpriced'])} distinct SKUs left blank)")
    print(f"chips charted: {', '.join(sorted(charts))}")
    if previous is None:
        print("only one snapshot so far -- change column and charts fill in "
              "from the second run onward")
    print(f"wrote {out}")
    print(f"open it with:  file://{out}")


if __name__ == "__main__":
    build()
