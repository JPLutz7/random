#!/usr/bin/env python3
"""
Pull Google Cloud's own price history, month by month.

    python3 backfill_gcp.py --from 2023-01          # preview what it would fetch
    python3 backfill_gcp.py --from 2023-01 --write  # fetch and store

Google's Cloud Billing Catalog API accepts startTime/endTime, and with them it
returns every pricing VERSION that was in force during that window rather than
just today's. Without them it returns only the latest, which is why this was
missed at first: the plain call reports effectiveTime as today's date on all
32,242 SKUs, which looks like "no history published".

Two constraints, both from Google's documentation and both confirmed by trying:

  * the window must sit inside a single calendar month in America/Los_Angeles.
    A window of 2026-07-01T00:00Z to 2026-07-31T23:59Z FAILS, because midnight
    UTC on 1 July is 17:00 on 30 June in Los Angeles, so the range straddles
    two months. Hence the LA-aligned boundaries below.
  * timestamps cannot be in the future.

History reaches back to at least January 2017; January 2016 is rejected.

The result is stated history -- Google's account of its own past prices -- so
these rows carry a validity window and an EMPTY snapshot_ts, which marks them
as something the provider says rather than something this tracker witnessed.
Only real daily runs count as observations.
"""

import argparse
import gzip
import json
import time
from datetime import date, datetime, timedelta

import requests

import storage
from providers import gcp

def _month_window(year, month, now=None):
    """
    (startTime, endTime) sitting safely inside this calendar month in LA time.

    Los Angeles is UTC-8, or UTC-7 under daylight saving, and Google rejects any
    window that crosses a month boundary in LA. Rather than track DST -- which
    is what broke the first attempt, since November 1st is still PDT and an
    October window computed with the PST offset spilled into November -- the
    window is simply held an hour clear of both ends:

        start = 08:00 UTC on the 1st       = 00:00 PST or 01:00 PDT
        end   = 06:00 UTC on the 1st next  = 22:00 PST or 23:00 PDT, last day

    Both land inside the target month under either offset. The hour of slack
    costs nothing: a price effective at midnight on the 1st is still in force
    an hour later, and this endpoint returns every version in force during the
    window rather than only those starting inside it.
    """
    start = datetime(year, month, 1, 8)
    nxt = datetime(year + 1, 1, 1, 6) if month == 12 else datetime(year, month + 1, 1, 6)
    # Google refuses timestamps in the future, so the current month stops now.
    if now is not None and nxt > now:
        nxt = now - timedelta(minutes=5)
    return (start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            nxt.strftime("%Y-%m-%dT%H:%M:%SZ"))


def months_between(first, last):
    year, month = int(first[:4]), int(first[5:7])
    stop = (int(last[:4]), int(last[5:7]))
    while (year, month) <= stop:
        yield year, month
        month += 1
        if month == 13:
            year, month = year + 1, 1


def fetch_month(key, year, month, timeout=120):
    """Every pricing version in force during one calendar month."""
    start, end = _month_window(year, month, datetime.utcnow())
    if start >= end:
        return None      # month has not begun yet
    pages, token = [], None
    while True:
        params = {"key": key, "pageSize": 5000, "startTime": start, "endTime": end}
        if token:
            params["pageToken"] = token
        response = requests.get(gcp.ENDPOINT, params=params, timeout=timeout)
        if response.status_code == 400:
            # Google rejects windows before its retention horizon.
            return None
        response.raise_for_status()
        payload = response.json()
        pages.append(payload)
        token = payload.get("nextPageToken")
        if not token:
            return pages
        time.sleep(0.1)


def _versions(sku, allowed_units):
    """(effective date, price) for each pricing version on this SKU."""
    out = []
    for info in sku.get("pricingInfo", []):
        expression = info.get("pricingExpression", {})
        if expression.get("usageUnit") not in allowed_units:
            continue
        rates = expression.get("tieredRates")
        if not rates:
            continue
        unit = rates[-1].get("unitPrice", {})
        value = int(unit.get("units", 0)) + unit.get("nanos", 0) / 1e9
        stamp = (info.get("effectiveTime") or "")[:10]
        if stamp:
            out.append((stamp, value))
    return sorted(out)


def _rate_at(timeline, when):
    """The last rate that took effect at or before `when`."""
    live = None
    for stamp, value in timeline:
        if stamp <= when:
            live = value
    return live


def normalize_history(pages_by_month):
    """
    Turn the archived months into rows carrying validity windows.

    Mirrors providers/gcp.py -- same accelerator table, same machine shapes,
    same machine_inclusive assembly -- but walks every pricing version instead
    of only the current one.
    """
    cpu_timeline, ram_timeline = {}, {}      # (region, family, price_type) -> [(date, rate)]
    accel_rows = []
    unmapped = {}

    for pages in pages_by_month.values():
        for page in pages:
            for sku in page.get("skus", []):
                category = sku.get("category", {})
                description = sku.get("description", "")
                if gcp._skipped(description):
                    continue
                price_type = gcp.PRICE_TYPE_BY_USAGE.get(category.get("usageType"))
                if price_type is None:
                    continue
                group = category.get("resourceGroup")
                regions = [r for r in sku.get("serviceRegions", []) if r != "global"]
                if gcp.REGIONS is not None:
                    regions = [r for r in regions if r in gcp.REGIONS]
                if not regions:
                    continue

                if group in ("CPU", "RAM"):
                    match = gcp.CPU_RAM_RE.match(description)
                    if not match:
                        continue
                    family, kind = match.group(1), match.group(2).lower()
                    units = ("GiBy.h",) if kind == "ram" else ("h",)
                    target = ram_timeline if kind == "ram" else cpu_timeline
                    for stamp, value in _versions(sku, units):
                        for region in regions:
                            target.setdefault((region, family, price_type), []).append((stamp, value))
                    continue

                if group != "GPU":
                    continue
                base = gcp._strip_region(description)
                import re
                base = re.sub(r"^(Commitment v1:\s*|Spot Preemptible\s*)", "", base).strip()
                base = re.sub(r"\s+attached to .*$", "", base).strip()
                for stamp, value in _versions(sku, ("h",)):
                    if value == 0:
                        continue          # commitment placeholder, not a rate
                    for region in regions:
                        accel_rows.append((base, region, price_type, stamp, value,
                                           sku.get("skuId", "")))
                        if base not in gcp.ACCELERATORS:
                            unmapped[base] = value

    for timeline in (cpu_timeline, ram_timeline):
        for key in timeline:
            timeline[key] = sorted(set(timeline[key]))

    rows = []
    for base, region, price_type, stamp, value, sku_id in accel_rows:
        entry = gcp.ACCELERATORS.get(base)
        if entry is None:
            rows.append(_row(sku_id, region, base, "", "", price_type, value, "",
                             stamp, "", "accelerator not in the lookup table"))
            continue
        chip, fallback_basis = entry
        shapes = gcp.MACHINES.get(base)
        if not shapes:
            rows.append(_row(sku_id, region, base, chip, 1, price_type, value,
                             round(value, 6), stamp, fallback_basis,
                             "bare accelerator price" if fallback_basis == gcp.BASIS_ACCELERATOR
                             else "per-slice price already covers the machine"))
            continue
        for machine, gpus, vcpu, ram_gb, family in shapes:
            cpu = _rate_at(cpu_timeline.get((region, family, price_type), []), stamp)
            ram = _rate_at(ram_timeline.get((region, family, price_type), []), stamp)
            if cpu is None or ram is None:
                continue    # cannot assemble honestly for this date
            machine_hour = value * gpus + vcpu * cpu + ram_gb * ram
            rows.append(_row(sku_id, region, machine, chip, gpus, price_type,
                             round(machine_hour, 6), round(machine_hour / gpus, 6),
                             stamp, gcp.BASIS_INCLUSIVE,
                             f"accelerator ${value:.4f}/GPU-hr plus {vcpu} vCPU "
                             f"and {ram_gb} GB RAM"))

    # Close each version at the day before the next one for the same meter.
    by_meter = {}
    for row in rows:
        by_meter.setdefault(
            (row["sku_id"], row["region"], row["price_type"], row["sku_name"]), []
        ).append(row)
    for versions in by_meter.values():
        versions.sort(key=lambda r: r["effective_from"])
        for earlier, later in zip(versions, versions[1:]):
            ends = date.fromisoformat(later["effective_from"]) - timedelta(days=1)
            earlier["effective_to"] = ends.isoformat()

    return rows, sorted(unmapped)


def _row(sku_id, region, sku_name, chip, gpu_count, price_type,
         list_price, per_gpu, starts, basis, note):
    unit = "Machine Per Hour" if basis == gcp.BASIS_INCLUSIVE and gpu_count != 1 else "GPU Per Hour"
    return {
        # Empty on purpose: this is Google's account of a past price, not a day
        # this tracker ran. Only real runs count as observations.
        "snapshot_ts": "",
        "provider": "gcp",
        "provider_last_updated": "",
        "region": region,
        "sku_id": sku_id,
        "sku_name": sku_name,
        "chip_model": chip,
        "gpu_count": gpu_count,
        "price_type": price_type,
        "currency": "USD",
        "list_price": list_price,
        "list_price_unit": unit,
        "usd_per_gpu_hour": per_gpu,
        "basis": basis,
        "effective_from": starts,
        "effective_to": "",
        "notes": note,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="first", default="2023-01",
                        help="first month, YYYY-MM (history reaches back to 2017-01)")
    parser.add_argument("--to", dest="last",
                        default=storage.utc_now().strftime("%Y-%m"))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    key = gcp._api_key()
    raw_dir = storage.RAW_DIR / "gcp-history"
    raw_dir.mkdir(parents=True, exist_ok=True)

    wanted = list(months_between(args.first, args.last))
    print(f"{len(wanted)} month(s) from {args.first} to {args.last}\n")

    pages_by_month, fetched, reused, refused = {}, 0, 0, 0
    for year, month in wanted:
        label = f"{year:04d}-{month:02d}"
        path = raw_dir / f"gcp-history-{label}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                pages_by_month[label] = json.load(fh)
            reused += 1
            continue
        if not args.write:
            print(f"  {label}  would fetch")
            continue
        pages = fetch_month(key, year, month)
        if pages is None:
            print(f"  {label}  refused by Google (before its retention horizon)")
            refused += 1
            continue
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(pages, fh)
        pages_by_month[label] = pages
        skus = sum(len(p.get("skus", [])) for p in pages)
        print(f"  {label}  {skus:5d} SKUs -> {path.name}")
        fetched += 1

    if not args.write:
        print("\npreview only. re-run with --write to fetch and store.")
        return

    print(f"\n{fetched} month(s) fetched, {reused} reused from the archive, "
          f"{refused} refused")
    if not pages_by_month:
        return

    rows, unmapped = normalize_history(pages_by_month)
    path = storage.NORMALIZED_DIR / "stated-gcp.csv"
    storage.NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=storage.COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in storage.COLUMNS})

    priced = sum(1 for r in rows if r["usd_per_gpu_hour"] != "")
    dates = sorted({r["effective_from"] for r in rows if r["effective_from"]})
    print(f"{len(rows)} stated rows ({priced} priced) -> {path.name}")
    if dates:
        print(f"covering {dates[0]} to {dates[-1]}")
    if unmapped:
        print(f"{len(unmapped)} accelerator name(s) with no chip mapping: "
              + ", ".join(unmapped[:6]))
    print("\nnow run  python3 build_page.py")


if __name__ == "__main__":
    main()
