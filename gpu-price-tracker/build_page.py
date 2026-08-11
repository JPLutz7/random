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

# ---------------------------------------------------------------------------
# Geography groups
# ---------------------------------------------------------------------------
# A single region control has to mean the same thing for all three providers,
# and they name regions nothing alike: Azure "eastus2", Google "us-east4",
# Oracle nothing at all. Picking a raw region name would leave exactly one
# provider on screen and hide the other two, which defeats the comparison.
#
# So regions are grouped by geography, and the toggle selects a geography.
# Every name below is mapped by hand from the provider's own naming; anything
# unrecognized falls into "Other" and is reported at build time rather than
# being guessed into a bucket it might not belong in.
#
# Oracle is the special case: it charges one price in every commercial region,
# so its single pseudo-region belongs to ALL geographies. WORLDWIDE marks it,
# and the page treats such a row as matching whichever geography is selected.
WORLDWIDE = "*"

REGION_GROUPS = {
    "US East": [
        "eastus", "eastus2", "southeastus", "attatlanta1",
        "us-east1", "us-east4", "us-east5", "us-east7",
    ],
    "US Central": [
        "centralus", "northcentralus", "southcentralus", "southcentralus2",
        "westcentralus", "attdallas1",
        "us-central1", "us-south1",
    ],
    "US West": [
        "westus", "westus2", "westus3",
        "us-west1", "us-west2", "us-west3", "us-west4", "us-west8",
    ],
    "US Government": ["usgovarizona", "usgovvirginia"],
    "Canada": [
        "canadacentral", "canadaeast",
        "northamerica-northeast1", "northamerica-northeast2",
    ],
    "Mexico": ["mexicocentral", "northamerica-south1"],
    "South America": [
        "brazilsouth", "chilecentral",
        "southamerica-east1", "southamerica-west1",
    ],
    "UK": ["uksouth", "ukwest", "europe-west2"],
    "Europe": [
        "northeurope", "westeurope", "francecentral", "francesouth",
        "germanynorth", "germanywestcentral", "italynorth", "norwayeast",
        "norwaywest", "polandcentral", "spaincentral", "swedencentral",
        "switzerlandnorth", "switzerlandwest",
        "europe-central2", "europe-north1", "europe-southwest1",
        "europe-west1", "europe-west3", "europe-west4", "europe-west5",
        "europe-west6", "europe-west8", "europe-west9", "europe-west10",
        "europe-west12",
    ],
    "Middle East": [
        "israelcentral", "qatarcentral", "uaecentral", "uaenorth",
        "me-central1", "me-central2", "me-west1",
    ],
    "Africa": ["southafricanorth", "southafricawest", "africa-south1"],
    "India": [
        "centralindia", "southindia", "jioindiacentral", "jioindiawest",
        "asia-south1", "asia-south2",
    ],
    "Japan": ["japaneast", "japanwest", "asia-northeast1", "asia-northeast2"],
    "Korea": ["koreacentral", "koreasouth", "asia-northeast3"],
    "Asia Pacific": [
        "eastasia", "southeastasia", "indonesiacentral", "malaysiawest",
        "sgxsingapore1",
        "asia-east1", "asia-east2", "asia-southeast1", "asia-southeast2",
    ],
    "Australia": [
        "australiacentral", "australiacentral2", "australiaeast",
        "australiasoutheast",
        "australia-southeast1", "australia-southeast2",
    ],
}

# Flattened for lookup, and the order the toggle lists them in.
GROUP_ORDER = list(REGION_GROUPS)
GROUP_BY_REGION = {r: g for g, names in REGION_GROUPS.items() for r in names}
GROUP_BY_REGION["all-commercial"] = WORLDWIDE   # Oracle, everywhere at once

# The geography the page opens on: all three providers sell GPUs there.
DEFAULT_GROUP = "US East"

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


    # Each provider is tracked on its own clock rather than one global snapshot.
    # Providers get collected at different moments and can fail independently,
    # so pinning the page to a single latest timestamp would silently drop
    # every provider that was not part of the most recent run.
    #
    # The history is a DAILY series, so a day gets one point however many times
    # collect.py ran that day -- the last run wins. Without this, testing runs
    # or a re-run after a failure would put several points on one date, repeat
    # the date along the x-axis, and make "change since last time" mean "change
    # in the last few minutes" rather than since yesterday.
    provider_day_ts = defaultdict(dict)     # provider -> {date: chosen snapshot_ts}
    for row in rows:
        day = row["snapshot_ts"][:10]
        chosen = provider_day_ts[row["provider"]].get(day)
        if chosen is None or row["snapshot_ts"] > chosen:
            provider_day_ts[row["provider"]][day] = row["snapshot_ts"]

    provider_days = {p: sorted(days) for p, days in provider_day_ts.items()}
    provider_latest = {p: provider_day_ts[p][days[-1]] for p, days in provider_days.items()}
    provider_previous = {
        p: (provider_day_ts[p][days[-2]] if len(days) > 1 else None)
        for p, days in provider_days.items()
    }
    # Only the per-day winners count as snapshots anywhere on the page.
    kept_ts = {ts for chosen in provider_day_ts.values() for ts in chosen.values()}
    snapshots = sorted(kept_ts)
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

        # Kept deliberately lean: with every region collected this is ~11,000
        # rows, and anything stored per row is multiplied by that. Labels are
        # looked up in the browser from the maps below rather than repeated
        # here, and `key` stays out of the payload since only Python uses it.
        record = {
            "provider": row["provider"],
            "chip": row["chip_model"],
            "sku_id": row["sku_id"],
            "sku_name": row["sku_name"],
            "region": row["region"],
            "price_type": row["price_type"],
            "gpu_count": row["gpu_count"],
            "list_price": to_float(row["list_price"]),
            "list_price_unit": row["list_price_unit"],
            "usd_per_gpu_hour": price,
            "basis": row.get("basis", ""),
            "change": change,
            "change_pct": change_pct,
            "notes": row["notes"],
        }
        latest_rows.append(record)

        if price is None:
            # One entry per SKU, not per price type -- Azure produces up to
            # seven rows for the same unrecognized machine.
            unpriced.setdefault((row["provider"], row["sku_id"]), {
                "provider": row["provider"],
                "provider_label": PROVIDER_LABELS.get(row["provider"], row["provider"]),
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
    # Series are cut by geography as well, so the region toggle moves the charts
    # and the tables together. Within a geography the cheapest row wins, which
    # keeps a line from jumping when a provider opens another datacentre in the
    # same part of the world.
    #
    # The empty-string price type is the "all price types" case: the lowest
    # posted rate of any kind. It is a real number -- the cheapest way to rent
    # that chip -- but it mixes spot with committed terms, so the caption says so.
    best = defaultdict(dict)   # (chip, price_type, group, provider, basis) -> {ts: (...)}
    unmapped_regions = set()

    for row in rows:
        price = to_float(row["usd_per_gpu_hour"])
        if price is None or not row["chip_model"]:
            continue
        # Skip runs superseded by a later one on the same day.
        if row["snapshot_ts"] not in kept_ts:
            continue
        group = GROUP_BY_REGION.get(row["region"])
        if group is None:
            unmapped_regions.add(row["region"])
            continue
        basis = row.get("basis", "")
        chip, provider = row["chip_model"], row["provider"]
        day = row["snapshot_ts"][:10]
        for price_type in (row["price_type"], ""):
            bucket = best[(chip, price_type, group, provider, basis)]
            current = bucket.get(day)
            if current is None or price < current[0]:
                bucket[day] = (price, row["sku_name"], row["region"])

    charts = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for (chip, price_type, group, provider, basis), by_ts in best.items():
        label = PROVIDER_LABELS.get(provider, provider)
        if basis == "accelerator_only":
            label += " (chip only)"
        charts[chip][price_type][group].append({
            "provider": provider,
            "label": label,
            "basis": basis,
            "points": [
                {"ts": day, "value": v, "sku": sku, "region": region}
                for day, (v, sku, region) in sorted(by_ts.items())
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
        regions = sorted({r["region"] for r in own})
        provider_blocks.append({
            "key": key,
            "label": PROVIDER_LABELS.get(key, key),
            "pulled": provider_latest[key],
            "stated": provider_last_updated.get(key, ""),
            "row_count": len(own),
            "priced_count": len(priced_rows),
            "chips": sorted({r["chip"] for r in priced_rows if r["chip"]}),
            "regions": regions,
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
        "group_by_region": GROUP_BY_REGION,
        "group_order": [g for g in GROUP_ORDER
                        if any(GROUP_BY_REGION.get(r["region"]) == g for r in latest_rows)],
        "default_group": DEFAULT_GROUP,
        "worldwide": WORLDWIDE,
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

    stray = sorted({r["region"] for r in latest_rows
                    if r["region"] not in GROUP_BY_REGION})
    if stray:
        print(f"WARNING: {len(stray)} region(s) not in the geography map, so they "
              f"are absent from the region toggle. Add them to REGION_GROUPS:")
        for name in stray:
            print(f"           {name}")

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
