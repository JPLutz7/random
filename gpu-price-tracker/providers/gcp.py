"""
Google Cloud (Compute Engine) list prices for GPUs.

Needs a free API key for the Cloud Billing API. It is read from the
GCP_BILLING_KEY environment variable, or from ~/.gcp_billing_key. The key is
never written into the repository, and never into the raw archive.

6F81-5844-456A is the Compute Engine service id.

Google itemizes differently from the other two providers, which is the whole
difficulty here -- see "How a comparable number is assembled" below.
"""

import os
import pathlib

import requests

SERVICE_ID = "6F81-5844-456A"
ENDPOINT = f"https://cloudbilling.googleapis.com/v1/services/{SERVICE_ID}/skus"

# Google prices per region. us-central1 (Iowa) is the default US region.
REGIONS = ["us-central1"]

KEY_FILE = pathlib.Path.home() / ".gcp_billing_key"

PRICE_TYPE_BY_USAGE = {
    "OnDemand": "on_demand",
    "Preemptible": "spot",
    "Commit1Yr": "1_year",
    "Commit3Yr": "3_year",
}

# ---------------------------------------------------------------------------
# How a comparable number is assembled
# ---------------------------------------------------------------------------
# Google sells the accelerator as its own SKU, separate from the vCPU and RAM
# of the machine it attaches to. Helpfully, that accelerator SKU is ALREADY
# quoted per GPU per hour, so a number can be read straight off it.
#
# But that number is not comparable to Oracle or Azure. Both of those bake CPU
# and RAM into what they quote -- Oracle's per-GPU bare-metal price covers the
# whole node, and Azure's price is for an entire VM. Google's bare accelerator
# price therefore reads low for a structural reason rather than a commercial
# one: 12% low on an 8x H100 machine, 25% low on a 1x A100 machine.
#
# So where a machine has a fixed published shape, the comparable figure is
# assembled:
#
#     per GPU per hour = accelerator + (vCPU x core price + GB x ram price)
#                                      -------------------------------------
#                                                  GPUs in the machine
#
# Not every GPU can be treated this way. The A2/A3/G2 families have fixed
# shapes; the older chips (T4, P100, P4, V100) attach to flexible N1 machines
# where the customer picks any CPU and RAM they like, so there is no canonical
# machine to assemble and no honest bundled number to compute.
#
# Every row therefore records which of the two it is, in the `basis` column:
#
#   machine_inclusive  -- CPU and RAM included; comparable to Oracle and Azure
#   accelerator_only   -- the bare chip rental; NOT comparable to the other two
#
# Nothing is guessed, and the page never mixes the two silently.
BASIS_INCLUSIVE = "machine_inclusive"
BASIS_ACCELERATOR = "accelerator_only"

# ---------------------------------------------------------------------------
# Accelerator SKUs, by the exact wording Google uses
# ---------------------------------------------------------------------------
# Keyed on the description with the region clause stripped. Anything not listed
# keeps its price with a BLANK per-GPU figure and is reported as unrecognized.
#
# The A4 B200 SKU is a special case: Google publishes NO separate A4 Core/Ram
# SKUs, because the "1 gpu slice" price already covers the whole machine
# divided by its GPUs. So it is machine_inclusive with nothing to add.
#
# "Nvidia H100 80GB Plus GPU" is deliberately absent -- it appears on only one
# SKU, and which product it denotes is not clear from the feed.
#
# Google calls its Blackwell workstation part "RTX 6000 96GB". Oracle and Azure
# both list an "RTX PRO 6000". They are very likely the same silicon, but the
# feed does not say so, and charting two different chips as one line would be a
# plausible-looking mistake. It keeps Google's own name until that is confirmed.
ACCELERATORS = {
    # description (region stripped)          chip label        basis if unassembled
    "Nvidia Tesla A100 GPU":                 ("A100",           BASIS_ACCELERATOR),
    "Nvidia Tesla A100 80GB GPU":            ("A100",           BASIS_ACCELERATOR),
    "Nvidia H100 80GB GPU":                  ("H100",           BASIS_ACCELERATOR),
    "Nvidia H100 80GB Mega GPU":             ("H100 Mega",      BASIS_ACCELERATOR),
    "Nvidia H100 Mega 80GB GPU":             ("H100 Mega",      BASIS_ACCELERATOR),
    "H200 141GB GPU":                        ("H200",           BASIS_ACCELERATOR),
    "A4 Nvidia B200 (1 gpu slice)":          ("B200",           BASIS_INCLUSIVE),
    "Nvidia L4 GPU":                         ("L4",             BASIS_ACCELERATOR),
    "Nvidia Tesla T4 GPU":                   ("T4",             BASIS_ACCELERATOR),
    "Nvidia Tesla V100 GPU":                 ("V100",           BASIS_ACCELERATOR),
    "Nvidia Tesla P100 GPU":                 ("P100",           BASIS_ACCELERATOR),
    "Nvidia Tesla P4 GPU":                   ("P4",             BASIS_ACCELERATOR),
    "RTX 6000 96GB":                         ("RTX 6000 96GB",  BASIS_ACCELERATOR),
}

# ---------------------------------------------------------------------------
# Machine shapes, for assembling a machine-inclusive price
# ---------------------------------------------------------------------------
# (machine type, GPUs, vCPUs, RAM GB, which Core/Ram SKU family to price with).
# Only shapes Google publishes as fixed configurations are listed. The G4 line
# and the A3 sub-8-GPU shapes are absent because their published specs are not
# settled; those chips fall back to accelerator_only rather than being guessed.
MACHINES = {
    "Nvidia Tesla A100 GPU": [
        ("a2-highgpu-1g",   1, 12,   85, "A2"),
        ("a2-highgpu-2g",   2, 24,  170, "A2"),
        ("a2-highgpu-4g",   4, 48,  340, "A2"),
        ("a2-highgpu-8g",   8, 96,  680, "A2"),
        ("a2-megagpu-16g", 16, 96, 1360, "A2"),
    ],
    "Nvidia Tesla A100 80GB GPU": [
        ("a2-ultragpu-1g",  1, 12,  170, "A2"),
        ("a2-ultragpu-2g",  2, 24,  340, "A2"),
        ("a2-ultragpu-4g",  4, 48,  680, "A2"),
        ("a2-ultragpu-8g",  8, 96, 1360, "A2"),
    ],
    "Nvidia H100 80GB GPU": [
        ("a3-highgpu-8g",   8, 208, 1872, "A3"),
    ],
    "Nvidia H100 80GB Mega GPU": [
        ("a3-megagpu-8g",   8, 208, 1872, "A3Plus"),
    ],
    "H200 141GB GPU": [
        ("a3-ultragpu-8g",  8, 224, 2952, "A3Ultra"),
    ],
    "Nvidia L4 GPU": [
        ("g2-standard-4",   1,  4,   16, "G2"),
        ("g2-standard-8",   1,  8,   32, "G2"),
        ("g2-standard-12",  1, 12,   48, "G2"),
        ("g2-standard-16",  1, 16,   64, "G2"),
        ("g2-standard-24",  2, 24,   96, "G2"),
        ("g2-standard-32",  1, 32,  128, "G2"),
        ("g2-standard-48",  4, 48,  192, "G2"),
        ("g2-standard-96",  8, 96,  384, "G2"),
    ],
}

# Matches the CPU and RAM SKUs of the GPU machine families across all four
# price types. Longer family names come first so A3 cannot swallow A3Ultra.
import re  # noqa: E402  (kept next to the pattern it serves)

CPU_RAM_RE = re.compile(
    r"^(?:Commitment v1:\s*|Spot Preemptible\s*)?"
    r"(A3Ultra|A3Plus|A2|A3|G2|G4)\s+"
    r"(?:Instance\s+)?(Core|Cpu|Ram)\b",
    re.IGNORECASE,
)

# Rows that are not a plain published rate. DWS Defined Duration and Calendar
# Mode are Google's scheduled-batch and reserved-block consumption models, with
# no counterpart at Oracle or Azure; mixing them in would make the price_type
# column mean different things per provider. "Reserved ..." rows are commitment
# placeholders, many of them priced at exactly $0.00 -- kept naively they would
# report an A100 as free.
EXCLUDE_MARKERS = ("dws", "calendar mode")


def _api_key():
    key = os.environ.get("GCP_BILLING_KEY")
    if key:
        return key.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    raise RuntimeError(
        "no Google API key found. Set GCP_BILLING_KEY or write the key to "
        f"{KEY_FILE}"
    )


def fetch(timeout=90):
    """Page through every Compute Engine SKU. Returns the pages as received."""
    key = _api_key()
    pages, token = [], None
    while True:
        params = {"key": key, "pageSize": 5000}
        if token:
            params["pageToken"] = token
        response = requests.get(ENDPOINT, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        pages.append(payload)
        token = payload.get("nextPageToken")
        if not token:
            break
    return pages


def _unit_price(sku, allowed_units=("h",)):
    """
    Google splits a price into whole units and nanos (billionths).

    The unit has to be checked, and it differs by what is being priced:
    accelerators and vCPUs are quoted per "h", but RAM is quoted per "GiBy.h"
    (per gibibyte per hour). Accepting only "h" silently discards every RAM
    rate, which in turn makes every machine-inclusive price impossible to
    assemble. Rows in any other unit -- Local SSD at "GiBy.mo", for instance --
    are not hourly rates at all and are dropped.
    """
    info = sku.get("pricingInfo")
    if not info:
        return None
    expression = info[0].get("pricingExpression", {})
    if expression.get("usageUnit") not in allowed_units:
        return None
    rates = expression.get("tieredRates")
    if not rates:
        return None
    price = rates[-1].get("unitPrice", {})
    return int(price.get("units", 0)) + price.get("nanos", 0) / 1e9


def _strip_region(description):
    """'Nvidia H100 80GB GPU running in Americas' -> 'Nvidia H100 80GB GPU'."""
    return re.sub(r"\s+(running\s+)?in\s+[A-Z].*$", "", description).strip()


def _skipped(description):
    lowered = description.lower()
    if any(marker in lowered for marker in EXCLUDE_MARKERS):
        return True
    if lowered.startswith("reserved "):
        return True
    # NOTE: "<chip> attached to Spot Preemptible VMs" must NOT be filtered out.
    # It looks like a duplicate of a "Spot Preemptible <chip>" row, but that
    # prefixed form exists for only a handful of SKUs -- nearly every spot GPU
    # price is published in the "attached to" wording alone. Dropping it
    # removes almost all of Google's spot pricing. The usageType field is what
    # marks these as Preemptible; the wording is just wording.
    return False


def normalize(payload, snapshot_ts):
    """
    Turn the archived pages into normalized rows.

    Returns (rows, unmapped). Accelerators missing from ACCELERATORS keep their
    price with a blank per-GPU figure and appear in `unmapped`.
    """
    skus = [sku for page in payload for sku in page.get("skus", [])]

    # Index the CPU and RAM rates: (region, family, price_type) -> $ per unit.
    cpu_rates, ram_rates = {}, {}
    for sku in skus:
        category = sku.get("category", {})
        if category.get("resourceGroup") not in ("CPU", "RAM"):
            continue
        description = sku.get("description", "")
        if _skipped(description):
            continue
        match = CPU_RAM_RE.match(description)
        if not match:
            continue
        family, kind = match.group(1), match.group(2).lower()
        price_type = PRICE_TYPE_BY_USAGE.get(category.get("usageType"))
        # RAM is priced per gibibyte-hour, vCPU per hour.
        price = _unit_price(sku, ("GiBy.h",) if kind == "ram" else ("h",))
        if price_type is None or price is None:
            continue
        target = ram_rates if kind == "ram" else cpu_rates
        for region in sku.get("serviceRegions", []):
            target[(region, family, price_type)] = price

    rows, unmapped = [], {}

    for sku in skus:
        category = sku.get("category", {})
        if category.get("resourceGroup") != "GPU":
            continue
        description = sku.get("description", "")
        if _skipped(description):
            continue

        price_type = PRICE_TYPE_BY_USAGE.get(category.get("usageType"))
        accelerator_price = _unit_price(sku)
        if price_type is None or accelerator_price is None:
            continue
        # A commitment placeholder priced at zero is not a real rate.
        if accelerator_price == 0:
            continue

        base = _strip_region(description)
        base = re.sub(r"^(Commitment v1:\s*|Spot Preemptible\s*)", "", base).strip()
        base = re.sub(r"\s+attached to .*$", "", base).strip()

        entry = ACCELERATORS.get(base)
        regions = [r for r in sku.get("serviceRegions", []) if r in REGIONS]
        if not regions:
            continue

        for region in regions:
            if entry is None:
                unmapped[base] = {
                    "sku_id": sku.get("skuId", ""),
                    "sku_name": base,
                    "list_price": round(accelerator_price, 6),
                }
                rows.append(_row(snapshot_ts, sku, region, base, "", "",
                                 price_type, accelerator_price, "",
                                 "accelerator not in the lookup table -- add it to gcp.py",
                                 ""))
                continue

            chip, fallback_basis = entry
            shapes = MACHINES.get(base)

            if not shapes:
                # No fixed machine shape to assemble against.
                note = ("bare accelerator price; Google bills vCPU and RAM "
                        "separately, so this is NOT comparable to Oracle or Azure"
                        if fallback_basis == BASIS_ACCELERATOR else
                        "Google publishes no separate A4 vCPU/RAM SKUs -- the "
                        "per-slice price already covers the whole machine")
                rows.append(_row(snapshot_ts, sku, region, base, chip, 1,
                                 price_type, accelerator_price,
                                 round(accelerator_price, 6), note, fallback_basis))
                continue

            for machine, gpus, vcpu, ram_gb, family in shapes:
                cpu = cpu_rates.get((region, family, price_type))
                ram = ram_rates.get((region, family, price_type))
                if cpu is None or ram is None:
                    # Without both halves the bundle cannot be built honestly.
                    rows.append(_row(snapshot_ts, sku, region, machine, chip, gpus,
                                     price_type, accelerator_price, "",
                                     f"no {family} vCPU/RAM rate published for this "
                                     f"price type -- cannot assemble", ""))
                    continue
                machine_hour = accelerator_price * gpus + vcpu * cpu + ram_gb * ram
                rows.append(_row(snapshot_ts, sku, region, machine, chip, gpus,
                                 price_type, round(machine_hour, 6),
                                 round(machine_hour / gpus, 6),
                                 f"accelerator ${accelerator_price:.4f}/GPU-hr plus "
                                 f"{vcpu} vCPU and {ram_gb} GB RAM",
                                 BASIS_INCLUSIVE))

    return rows, sorted(unmapped.values(), key=lambda r: r["sku_name"])


def _row(snapshot_ts, sku, region, sku_name, chip, gpu_count,
         price_type, list_price, per_gpu, note, basis):
    effective = (sku.get("pricingInfo") or [{}])[0].get("effectiveTime", "")
    unit = "Machine Per Hour" if basis == BASIS_INCLUSIVE and gpu_count != 1 else "GPU Per Hour"
    return {
        "snapshot_ts": snapshot_ts.isoformat(),
        "provider": "gcp",
        "provider_last_updated": effective,
        "region": region,
        "sku_id": sku.get("skuId", ""),
        "sku_name": sku_name,
        "chip_model": chip,
        "gpu_count": gpu_count,
        "price_type": price_type,
        "currency": "USD",
        "list_price": round(list_price, 6) if list_price != "" else "",
        "list_price_unit": unit,
        "usd_per_gpu_hour": per_gpu,
        "basis": basis,
        "notes": note,
    }
