# GPU price tracker

Records what Microsoft Azure, Google Cloud and Oracle publicly charge to rent a
GPU, once a day, and builds a local page from the result.

Cloud providers publish today's prices but not yesterday's, so no public price
history exists. **The archive is the point.** The page is the visible part, but
the reason to run this daily is that a day not collected is a day gone for good.

AWS is deliberately excluded. Meta publishes no rate card, so there is nothing
to pull.

Status: **Oracle is live. Azure and Google are not built yet.**

## Running it

Two commands. The first takes the snapshot, the second rebuilds the page.

```
cd gpu-price-tracker
python3 collect.py
python3 build_page.py
```

Then open `docs/index.html` — double-click it, or drag it into a browser
window. There is no server to start.

`collect.py` prints what it found, including any SKU it could not identify.

## What each run writes

Nothing is ever overwritten. Filenames carry a full UTC timestamp, so even two
runs on the same day sit side by side.

| Path | What it is |
|---|---|
| `data/raw/<provider>/<provider>-<timestamp>.json.gz` | the provider's response, byte-for-byte, gzipped |
| `data/normalized/<timestamp>-<provider>.csv` | one row per price, reduced to USD per GPU-hour |
| `docs/index.html` | the page, rebuilt from every snapshot so far |

The raw archive is what makes mistakes survivable. If a normalization choice
turns out to be wrong, fix the provider file and run:

```
python3 reprocess.py            # preview
python3 reprocess.py --write    # apply, then rebuild the page
```

Every past day is recomputed from the original bytes. The raw files are never
modified.

## The number the page shows

Everything is reduced to **US dollars per GPU per hour**, because the three
providers quote differently — Oracle per GPU, Azure per whole multi-GPU
machine, Google split across separate accelerator/CPU/RAM line items.

Price type (`on_demand`, `spot`, `1_year`, `3_year`) is its own column and is
never mixed into one blended number.

**Where a figure cannot be derived honestly, it is left blank** and the SKU is
listed on the page. A wrong number that looks plausible is worse than a blank.
Right now that applies to five older Oracle SKUs named by hardware generation
("GPU Standard - V2", "GPU - E3") rather than by chip.

## Traps handled

These are documented in code where the filtering happens, not only here.

**Oracle software licences.** The feed contains rows like
`OCI - NVIDIA AI Enterprise - H100` at $2.50/GPU/hr. That is a software licence
billed on top of compute, not the price of the chip — the real H100 row is
$10.00. It sits in the same service category and carries the same
`GPU Per Hour` unit, so filtering on the unit alone pulls it in and reports an
H100 at a quarter of its true price. Excluded in `providers/oracle.py`.

**Azure reservation totals.** *(applies once Azure is added)* Reservation rows
carry `unitOfMeasure` of `1 Hour`, but the value is the total for the entire
term — taken at face value it produces roughly $65,000 per GPU-hour. Divide by
8760 for a 1-year term, 26280 for 3-year.

## Adding a chip Oracle just launched

When Oracle adds a GPU, its part number appears in the "no chip mapping" list
at the end of a `collect.py` run, and on the page. Add it to
`CHIP_BY_PART_NUMBER` in `providers/oracle.py`, then
`python3 reprocess.py --write` so the whole history picks it up.

## Notes on the sources

- **Oracle** — no authentication, one request, no pagination. Prices are
  identical across all commercial regions, so one pull covers them all; the
  region column reads `all-commercial`. The feed publishes only
  `PAY_AS_YOU_GO`, so every Oracle row is `on_demand`.
- **Azure** — not built yet. No authentication, but paginated.
- **Google** — not built yet. Needs a free API key.

## Files

| File | What it does |
|---|---|
| `collect.py` | takes a snapshot — run this daily |
| `build_page.py` | rebuilds `docs/index.html` from every snapshot |
| `reprocess.py` | recomputes the tidy files from the raw archive |
| `storage.py` | where files go, and the columns of a price row |
| `providers/oracle.py` | the Oracle feed, its filters and its chip lookup |
| `page_template.html` | the page's markup, styling and behaviour |

The page's data is embedded directly inside `docs/index.html` rather than
loaded from a separate file, because browsers block a local page from reading
another local file. Embedding is what lets it work by double-clicking, with no
server.
