"""
Microsoft Azure retail list prices for GPU virtual machines.

No authentication, but paginated: follow NextPageLink until it is absent.
api-version 2023-01-01-preview is used because it also returns savings-plan
rates, which the stable version omits.

Unlike Oracle, Azure prices vary by region, so a region is part of every row.
Azure also prices the whole machine rather than the chip, so turning a row
into dollars-per-GPU-hour needs a GPU count -- which is NOT in the price feed.
That is what GPU_COUNT below is for.
"""

import time

import requests

ENDPOINT = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"   # savings-plan rates only come back on the preview version

# Azure list prices differ per region, so each region is a separate pull.
REGIONS = ["eastus"]

# GPU machines are the N-series. Narrowing server-side keeps the response to a
# fraction of the full Virtual Machines catalogue.
SKU_PREFIX = "Standard_N"

HOURS_PER_YEAR = 8760

# ---------------------------------------------------------------------------
# TRAP 1: reservation rows are term totals wearing an hourly label
# ---------------------------------------------------------------------------
# Every N-series row -- all 771 of them in eastus -- reports unitOfMeasure
# "1 Hour", including the 100 reservation rows. For a reservation the value is
# NOT hourly: it is the total for the whole term.
#
# Standard_ND96isr_H100_v5 (8x H100), 1-year reservation, reads 551221.0
# against "1 Hour". Taken at face value that is $68,900 per GPU-hour.
# Amortized over the term it is 551221 / 8760 / 8 = $7.87 per GPU-hour.
#
# Divide by the hours in the term: 8760 for 1 year, 26280 for 3 years,
# 43800 for 5 years (Azure does publish 5-year terms on some SKUs).
RESERVATION_TERM_HOURS = {
    "1 Year": 1 * HOURS_PER_YEAR,
    "3 Years": 3 * HOURS_PER_YEAR,
    "5 Years": 5 * HOURS_PER_YEAR,
}

# ---------------------------------------------------------------------------
# TRAP 2: the preview API returns superseded prices alongside current ones
# ---------------------------------------------------------------------------
# The same meterId comes back several times with different effective windows.
# Meter 000a689e... carries both a row effective 2026-04-01 to 2026-07-31 at
# $6.2616 and a row effective from 2026-08-01 with no end date at $5.785718.
# Both are "real"; only the second is today's price. Keeping every row would
# silently record a stale price and invent a price change that never happened.
#
# A row counts as current when it has already started and has not yet ended.
def _is_current(item, now_iso):
    start = item.get("effectiveStartDate")
    end = item.get("effectiveEndDate")
    if start and start > now_iso:
        return False
    if end and end <= now_iso:
        return False
    return True


# ---------------------------------------------------------------------------
# Rows deliberately left out
# ---------------------------------------------------------------------------
# Windows rows bundle a Windows Server licence into the hourly price, so they
# measure Microsoft's licensing, not the cost of the chip. Linux is the clean
# baseline (and is what Oracle and Google quote against).
#
# DevTestConsumption is a discounted rate that requires a Dev/Test
# subscription -- not a price a normal customer can buy at.
#
# "Low Priority" is Azure's deprecated pre-Spot preemptible tier, superseded
# by Spot. Recording both would double-count preemptible pricing.
def _is_excluded(item):
    if "Windows" in item.get("productName", ""):
        return True
    if item.get("type") == "DevTestConsumption":
        return True
    if "Low Priority" in item.get("skuName", ""):
        return True
    return False


# ---------------------------------------------------------------------------
# How many GPUs are in each machine
# ---------------------------------------------------------------------------
# The price feed does not carry a GPU count, so this table is hand-written and
# is the only place a per-machine price becomes a per-GPU price.
#
# Scope is the AI-relevant families: NC/ND with A100, H100 and H200, plus the
# NV A10 line, and the V100/T4 generations that preceded them. Anything absent
# keeps its machine price but gets a BLANK per-GPU figure and is reported as
# unrecognized -- never a guess.
#
# Deliberately absent, and why:
#   Standard_ND128isr_NDR_GB200_v6      -- GB200; per-VM GPU count not confirmed
#   Standard_NC*_xl_RTXPRO6000BSE_v6    -- new RTX PRO 6000 line; the "ds"/"lds"
#                                          pairs share vCPU counts, so the GPU
#                                          count is not derivable from the name
#   Standard_NP*                        -- Xilinx FPGAs, not GPUs at all
#   Standard_NM16ads_MA35D              -- media transcoding accelerator, not a GPU
#   Standard_NV*_v3 / _v4 / _V710_v5    -- M60 / MI25 / Radeon PRO graphics SKUs
#   Standard_N*_Promo                   -- retired promotional K80/M60 SKUs
#
# Fractional counts are real: the NVadsA10 v5 line sells partitioned slices of
# a single A10. A machine with 1/6 of an A10 divides by 0.1667, which
# extrapolates a whole-GPU price from a slice -- see PARTITIONED below.
GPU_COUNT = {
    # --- NVIDIA V100 ---
    "Standard_NC6s_v3": (1, "V100"),
    "Standard_NC12s_v3": (2, "V100"),
    "Standard_NC24s_v3": (4, "V100"),
    "Standard_NC24rs_v3": (4, "V100"),
    "Standard_ND40s_v2": (8, "V100"),
    "Standard_ND40rs_v2": (8, "V100"),

    # --- NVIDIA T4 ---
    "Standard_NC4as_T4_v3": (1, "T4"),
    "Standard_NC8as_T4_v3": (1, "T4"),
    "Standard_NC16as_T4_v3": (1, "T4"),
    "Standard_NC64as_T4_v3": (4, "T4"),

    # --- NVIDIA A100 ---
    "Standard_NC24ads_A100_v4": (1, "A100"),
    "Standard_NC48ads_A100_v4": (2, "A100"),
    "Standard_NC96ads_A100_v4": (4, "A100"),
    "Standard_ND96asr_v4": (8, "A100"),
    "Standard_ND96asr_A100_v4": (8, "A100"),
    "Standard_ND96ams_A100_v4": (8, "A100"),
    "Standard_ND96amsr_A100_v4": (8, "A100"),

    # --- NVIDIA H100 ---
    "Standard_NC40ads_H100_v5": (1, "H100"),
    "Standard_NC80adis_H100_v5": (2, "H100"),
    "Standard_ND96is_H100_v5": (8, "H100"),
    "Standard_ND96isr_H100_v5": (8, "H100"),
    "Standard_ND96isrf_H100_v5": (8, "H100"),
    "Standard_ND96is_flex_H100_v5": (8, "H100"),
    "Standard_ND96is_noIB_H100_v5": (8, "H100"),

    # --- NVIDIA H200 (absent from eastus; present in other regions) ---
    "Standard_ND96isr_H200_v5": (8, "H200"),

    # --- NVIDIA A10, partitioned ---
    "Standard_NV6ads_A10_v5": (1 / 6, "A10"),
    "Standard_NV12ads_A10_v5": (1 / 3, "A10"),
    "Standard_NV18ads_A10_v5": (1 / 2, "A10"),
    "Standard_NV36ads_A10_v5": (1, "A10"),
    "Standard_NV36adms_A10_v5": (1, "A10"),
    "Standard_NV72ads_A10_v5": (2, "A10"),
}

# Machines that carry only a slice of a GPU. Dividing by the fraction gives a
# whole-GPU-equivalent price, but a slice is sold at a premium per unit, so
# that figure is an extrapolation rather than a price anyone is quoted. It is
# still recorded -- the note says so on the row, and on the page.
PARTITIONED = {name for name, (count, _) in GPU_COUNT.items() if count < 1}


def fetch(timeout=60):
    """
    Pull every N-series VM price for each region, following NextPageLink.

    Returns the page payloads exactly as received, keyed by region, so the
    archive holds the provider's own bytes rather than anything reshaped.
    """
    out = {}
    for region in REGIONS:
        params = {
            "api-version": API_VERSION,
            "$filter": (
                f"serviceName eq 'Virtual Machines' "
                f"and armRegionName eq '{region}' "
                f"and startswith(armSkuName, '{SKU_PREFIX}')"
            ),
        }
        pages, url = [], ENDPOINT
        while url:
            response = requests.get(url, params=params if url == ENDPOINT else None,
                                    timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            pages.append(payload)
            url = payload.get("NextPageLink")
            if url:
                time.sleep(0.2)   # be polite across pages
        out[region] = pages
    return out


def _price_types(item):
    """
    Yield (price_type, price_per_machine_hour) for one row.

    A single row can produce several: a consumption row also carries any
    savings-plan rates that apply to it.
    """
    kind = item.get("type")
    sku_name = item.get("skuName", "")
    retail = item.get("retailPrice")

    if kind == "Reservation":
        hours = RESERVATION_TERM_HOURS.get(item.get("reservationTerm"))
        if hours and retail is not None:
            # The term total, spread across the hours of the term.
            label = item["reservationTerm"].lower().replace(" ", "_").rstrip("s")
            yield f"{label.replace('_years', '_year')}", retail / hours
        return

    if kind != "Consumption" or retail is None:
        return

    yield ("spot" if "Spot" in sku_name else "on_demand"), retail

    # Savings-plan rates are already effective hourly rates, not term totals.
    for plan in item.get("savingsPlan") or []:
        term = (plan.get("term") or "").lower().replace(" ", "_").rstrip("s")
        if plan.get("retailPrice") is not None:
            yield f"savings_plan_{term.replace('_years', '_year')}", plan["retailPrice"]


def normalize(payload, snapshot_ts):
    """
    Turn the archived pages into normalized rows.

    Returns (rows, unmapped). Machines missing from GPU_COUNT keep their
    machine price with a blank per-GPU figure and appear in `unmapped`.
    """
    now_iso = snapshot_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    unmapped = {}

    for region, pages in payload.items():
        for page in pages:
            for item in page.get("Items", []):
                if _is_excluded(item) or not _is_current(item, now_iso):
                    continue

                arm_name = item.get("armSkuName", "")
                mapping = GPU_COUNT.get(arm_name)
                gpu_count, chip = mapping if mapping else (None, "")

                for price_type, machine_hour_price in _price_types(item):
                    if gpu_count:
                        per_gpu = round(machine_hour_price / gpu_count, 6)
                        note = (
                            f"extrapolated from a partitioned GPU slice "
                            f"({gpu_count:.4f} of one {chip})"
                            if arm_name in PARTITIONED else ""
                        )
                    else:
                        per_gpu = ""      # blank, never guessed
                        note = "machine not in the GPU count table -- add it to azure.py"
                        unmapped[arm_name] = {
                            "sku_id": arm_name,
                            "sku_name": item.get("productName", arm_name),
                            "list_price": round(machine_hour_price, 6),
                        }

                    rows.append({
                        "snapshot_ts": snapshot_ts.isoformat(),
                        "provider": "azure",
                        # Azure publishes no feed-wide freshness stamp; the row's
                        # own effective date is the closest equivalent.
                        "provider_last_updated": item.get("effectiveStartDate", ""),
                        "region": region,
                        "sku_id": arm_name,
                        "sku_name": item.get("productName", ""),
                        "chip_model": chip,
                        "gpu_count": round(gpu_count, 4) if gpu_count else "",
                        "price_type": price_type,
                        "currency": item.get("currencyCode", "USD"),
                        "list_price": round(machine_hour_price, 6),
                        "list_price_unit": "Machine Per Hour",
                        "usd_per_gpu_hour": per_gpu,
                        "notes": note,
                    })

    return rows, sorted(unmapped.values(), key=lambda r: r["sku_id"])
