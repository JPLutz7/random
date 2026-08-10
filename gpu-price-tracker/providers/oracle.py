"""
Oracle Cloud Infrastructure (OCI) list prices.

The feed needs no authentication and no pagination -- one request returns
everything. Oracle charges the same in every commercial region, so a single
pull covers them all; the region column is recorded as "all-commercial".

Oracle already quotes GPU compute per GPU per hour, so no per-machine
division is needed here. It publishes only PAY_AS_YOU_GO in this feed --
no spot and no committed-term rates -- so every Oracle row is on_demand.
"""

import requests

ENDPOINT = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"

# serviceCategory=Compute is a loose match on Oracle's side (it returns far
# more than Compute), but it still cuts the payload down substantially.
PARAMS = {"currencyCode": "USD", "serviceCategory": "Compute"}

# Oracle's GPU compute lives in these two categories. Notably this EXCLUDES
# "Compute Cloud@Customer", which is hardware Oracle installs in your own
# datacentre -- a different product from renting a GPU in their cloud.
GPU_SERVICE_CATEGORIES = {"Compute - GPU", "Compute - GPU - Other"}

GPU_METRIC = "GPU Per Hour"

# ---------------------------------------------------------------------------
# TRAP: software licences priced per GPU-hour
# ---------------------------------------------------------------------------
# The feed contains rows like "OCI - NVIDIA AI Enterprise - H100" ($2.50) and
# "OCI - NVIDIA AI Enterprise - A100 80" ($1.00). These are NVIDIA software
# licences billed ON TOP OF the compute you are already renting -- they are
# not the price of the chip. They sit in serviceCategory "Compute - GPU" and
# carry the same "GPU Per Hour" metric as real compute, so filtering on the
# unit alone sweeps them in.
#
# The damage is not a rounding error: the real H100 row (B98415) is $10.00
# per GPU-hour, while the licence row for the same chip is $2.50. Including
# the licence rows reports an H100 at roughly a quarter of its true price.
#
# They are excluded here. If Oracle ever renames the product line this
# substring will stop matching -- the unmapped-chip report is the safety net,
# since a newly-included licence row would appear there as an unknown SKU.
LICENCE_NAME_MARKER = "nvidia ai enterprise"

# ---------------------------------------------------------------------------
# Which chip is in which SKU
# ---------------------------------------------------------------------------
# Keyed on partNumber rather than displayName, because the names are not
# typed consistently ("OCI- Compute" with a missing space, "Compute  - GPU -
# A10" with a doubled one). Part numbers are stable.
#
# Only SKUs whose name literally states the chip are listed. Oracle's older
# SKUs are named by hardware generation instead ("GPU Standard - V2",
# "GPU - E3"), and mapping those to a chip would be a guess -- so they are
# deliberately absent. Their prices are still recorded; they just carry a
# blank chip_model and get reported as unmapped, which is the honest outcome.
#
# When Oracle adds a GPU, its part number shows up in the unmapped report at
# the end of a run. Add it here and the history reprocesses cleanly.
CHIP_BY_PART_NUMBER = {
    "B88517": None,            # Bare Metal GPU Standard - X7   (generation-coded)
    "B88518": None,            # Virtual Machine GPU Standard - X7
    "B89734": None,            # GPU Standard - V2
    "B92740": None,            # GPU - E3
    "B93544": None,            # GPU - E4
    "B95909": "A10",
    "B95907": "A100",          # named "A100 - v2"; memory size not stated, so not split 40/80
    "B98415": "H100",
    "B109479": "L40S",
    "B109480": "H100T",
    "B109485": "MI300X",
    "B110519": "H200",
    "B110978": "B200",
    "B110979": "GB200",
    "B111758": "MI355X",
    "B112140": "GB300",
    "B112237": "B300",
    "B112613": "RTX PRO 6000",
}


def fetch(timeout=60):
    """One unauthenticated GET. Returns the parsed JSON exactly as received."""
    response = requests.get(ENDPOINT, params=PARAMS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _usd_pay_as_you_go(item):
    """Pull the USD PAY_AS_YOU_GO value out of the nested price structure."""
    for localization in item.get("currencyCodeLocalizations", []):
        if localization.get("currencyCode") != "USD":
            continue
        for price in localization.get("prices", []):
            if price.get("model") == "PAY_AS_YOU_GO":
                return price.get("value")
    return None


def normalize(payload, snapshot_ts):
    """
    Turn the raw feed into normalized rows.

    Returns (rows, unmapped) where `unmapped` lists GPU SKUs whose chip we
    could not identify. Those SKUs are still present in `rows`, with a blank
    chip_model and a blank usd_per_gpu_hour -- never a guessed value.
    """
    provider_last_updated = payload.get("lastUpdated", "")
    rows = []
    unmapped = []

    for item in payload.get("items", []):
        if item.get("serviceCategory") not in GPU_SERVICE_CATEGORIES:
            continue
        if item.get("metricName") != GPU_METRIC:
            continue

        name = item.get("displayName", "")
        if LICENCE_NAME_MARKER in name.lower():
            continue  # software licence, not the price of the chip -- see above

        part_number = item.get("partNumber", "")
        price = _usd_pay_as_you_go(item)
        if price is None:
            continue

        known = part_number in CHIP_BY_PART_NUMBER
        chip = CHIP_BY_PART_NUMBER.get(part_number)

        if chip:
            per_gpu_hour = price   # Oracle already quotes per GPU per hour
            note = ""
        else:
            per_gpu_hour = ""      # blank, never guessed
            note = (
                "chip named by hardware generation, not model -- not mapped"
                if known
                else "SKU not in chip lookup table -- add it to oracle.py"
            )
            unmapped.append({"sku_id": part_number, "sku_name": name, "list_price": price})

        rows.append({
            "snapshot_ts": snapshot_ts.isoformat(),
            "provider": "oracle",
            "provider_last_updated": provider_last_updated,
            "region": "all-commercial",   # Oracle list price is uniform across commercial regions
            "sku_id": part_number,
            "sku_name": name,
            "chip_model": chip or "",
            "gpu_count": 1,               # the priced unit IS one GPU
            "price_type": "on_demand",    # the feed carries no spot or committed rates
            "currency": "USD",
            "list_price": price,
            "list_price_unit": "GPU Per Hour",
            "usd_per_gpu_hour": per_gpu_hour,
            "notes": note,
        })

    return rows, unmapped
