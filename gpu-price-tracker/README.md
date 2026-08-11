# GPU price tracker

Records what Microsoft Azure, Google Cloud and Oracle publicly charge to rent a
GPU, once a day, and builds a local page from the result.

Cloud providers publish today's prices but not yesterday's, so no public price
history exists. **The archive is the point.** The page is the visible part, but
the reason to run this daily is that a day not collected is a day gone for good.

AWS is deliberately excluded. Meta publishes no rate card, so there is nothing
to pull.

Status: **All three providers are live.**

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

Price type (`on_demand`, `spot`, `1_year`, `3_year`, plus Azure's `5_year` and
savings-plan rates) is its own column and is never mixed into one blended
number.

There is a second column that matters just as much, **`basis`**, because the
providers do not all measure the same thing:

| basis | meaning |
|---|---|
| `machine_inclusive` | vCPU and RAM are inside the price — Oracle, Azure, and Google wherever a fixed machine shape exists |
| `accelerator_only` | the bare chip; Google bills vCPU and RAM separately, so it is **not** comparable to the other two |

The page labels these "machine" and "chip only", and draws chip-only lines
dashed, so the two can never be compared by accident.

**Where a figure cannot be derived honestly, it is left blank** and the SKU is
listed on the page. A wrong number that looks plausible is worse than a blank.
Right now that applies to five older Oracle SKUs named by hardware generation
("GPU Standard - V2", "GPU - E3") rather than by chip, and to 51 Azure machines
whose GPU count is not established — the GB200 VM, the new RTX PRO 6000 line,
plus FPGA, media-accelerator and older graphics SKUs that are not AI parts.

Some figures are **extrapolated** rather than quoted. The NVadsA10 v5 line sells
partitioned slices of one A10, so a machine with 1/6 of a GPU divides by 0.1667
to reach a whole-GPU price nobody is actually charged. Those rows are marked
`extrapolated` in the table and carry a note saying so.

## Traps handled

These are documented in code where the filtering happens, not only here.

**Oracle software licences.** The feed contains rows like
`OCI - NVIDIA AI Enterprise - H100` at $2.50/GPU/hr. That is a software licence
billed on top of compute, not the price of the chip — the real H100 row is
$10.00. It sits in the same service category and carries the same
`GPU Per Hour` unit, so filtering on the unit alone pulls it in and reports an
H100 at a quarter of its true price. Excluded in `providers/oracle.py`.

**Azure reservation totals.** Every N-series row reports `unitOfMeasure` of
`1 Hour` — including reservations, where the value is the total for the entire
term. `Standard_ND96isr_H100_v5` (8× H100) reads `551221.0` on its 1-year row,
which at face value is $68,900 per GPU-hour. Amortized over the term it is
551221 ÷ 8760 ÷ 8 = **$7.87**. Divide by 8760 for 1 year, 26280 for 3 years,
43800 for 5 years — Azure publishes 5-year terms on some SKUs.

**Google's zero-priced placeholders.** 226 GPU SKUs across all regions carry a
price of exactly $0.00 — rows like `Reserved Nvidia Tesla A100 GPU in Milan`.
They are commitment placeholders, not free GPUs. Any row priced at zero is
dropped.

**Google's RAM unit.** Accelerators and vCPUs are quoted per `h`, but RAM is
quoted per `GiBy.h`. Accepting only `h` silently discards every RAM rate, which
makes every machine-inclusive price impossible to assemble — it fails quietly,
as blanks, rather than loudly.

**Google's spot wording.** Almost every spot GPU price is published as
`<chip> attached to Spot Preemptible VMs`. Only a handful use the
`Spot Preemptible <chip>` prefix. Treating the "attached to" form as a duplicate
removes nearly all of Google's spot pricing. The `usageType` field is what marks
a row preemptible; the wording is just wording.

**Azure superseded prices.** *(not in the original brief — found while
building)* The preview API returns retired price rows next to current ones. One
meter came back both as effective 2026-04-01 to 2026-07-31 at $6.2616 and as
effective from 2026-08-01 with no end date at $5.785718. Keeping both would
record a stale price and invent a price change that never happened. Only rows
that have started and not yet ended are kept.

## Adding a machine the tracker does not recognize

New hardware appears in the "no chip mapping" list at the end of a `collect.py`
run, and on the page. Add it to `CHIP_BY_PART_NUMBER` in `providers/oracle.py`
or `GPU_COUNT` in `providers/azure.py`, then run
`python3 reprocess.py --write` so the whole history picks up the correction,
and rebuild the page.

## Notes on the sources

- **Oracle** — no authentication, one request, no pagination. Prices are
  identical across all commercial regions, so one pull covers them all; the
  region column reads `all-commercial`. The feed publishes only
  `PAY_AS_YOU_GO`, so every Oracle row is `on_demand`.
- **Azure** — no authentication, but paginated; follow `NextPageLink` until it
  is absent. Uses `api-version=2023-01-01-preview` so savings-plan rates come
  back too. Prices differ by region, so region is part of every row; currently
  `eastus` only, set by `REGIONS` in `providers/azure.py`. Azure prices the
  whole machine, so `GPU_COUNT` in that file is the hand-written table that
  turns a machine price into a per-GPU price.

  Left out on purpose: **Windows** rows (they bundle a Windows Server licence,
  so they measure licensing rather than the chip), **DevTestConsumption** (needs
  a special subscription), and **Low Priority** (Azure's deprecated pre-Spot
  tier, which would double-count preemptible pricing).
- **Google** — needs a free Cloud Billing API key, read from the
  `GCP_BILLING_KEY` environment variable or `~/.gcp_billing_key`. The key is
  never written into the repository or into the raw archive. Paginated via
  `nextPageToken`; `6F81-5844-456A` is the Compute Engine service id. Currently
  `us-central1`, set by `REGIONS` in `providers/gcp.py`.

  Google itemizes the accelerator separately from the vCPU and RAM it attaches
  to. Helpfully, that accelerator SKU is *already* quoted per GPU per hour — but
  taking it at face value is not comparable to Oracle or Azure, which both bake
  CPU and RAM into what they quote. It reads 12% low on an 8×H100 machine and
  25% low on a 1×A100 machine. So where Google publishes a fixed machine shape,
  the comparable figure is assembled:

  ```
  per GPU-hour = accelerator + (vCPU × core rate + GB × ram rate)
                               ------------------------------------
                                        GPUs in the machine
  ```

  The A2/A3/G2 families have fixed shapes and are assembled. The older chips
  (T4, P100, P4, V100) attach to flexible N1 machines where the customer picks
  any CPU and RAM, so there is no canonical machine and no honest bundle to
  compute — those stay `accelerator_only`. The A4 (B200) line needs no assembly:
  Google publishes no separate A4 vCPU/RAM SKUs because the "1 gpu slice" price
  already covers the whole machine.

  Left out on purpose: **DWS Defined Duration** and **Calendar Mode** (Google's
  scheduled-batch and reserved-block models, which have no counterpart at Oracle
  or Azure), and **`Reserved …` rows**, many of which are commitment
  placeholders priced at exactly $0.00 — kept naively they would report an A100
  as free.

## Files

| File | What it does |
|---|---|
| `collect.py` | takes a snapshot — run this daily |
| `build_page.py` | rebuilds `docs/index.html` from every snapshot |
| `reprocess.py` | recomputes the tidy files from the raw archive |
| `storage.py` | where files go, and the columns of a price row |
| `providers/oracle.py` | the Oracle feed, its filters and its chip lookup |
| `providers/azure.py` | the Azure feed, its filters and its GPU-count table |
| `providers/gcp.py` | the Google feed, its filters, chip lookup and machine shapes |
| `page_template.html` | the page's markup, styling and behaviour |

## How the page is laid out

The page is organised by hyperscaler:

1. **A card per provider** — how many of its prices were normalized, how many
   chips that covers, when this tracker pulled it, and the freshness date the
   provider states for itself. Click a card to jump to that provider.
2. **A section per provider** — its own sortable table, its own region, and its
   own list of SKUs left blank, collapsed by default. Attributing the blanks to
   the provider that produced them matters: in one flat list, 64 unrecognized
   SKUs read as a single failure rather than three separate and quite different
   ones. Each table scrolls inside its own box, so a provider with hundreds of
   rows does not push the others off the screen.
3. **Charts, across providers** — this is the one place the providers are
   deliberately mixed, because comparing them over time is the point. One line
   per provider per chip, showing the cheapest per-GPU-hour it lists, with its
   own price-type selector.

The filters at the top apply to every section at once, and a provider filtered
down to nothing is hidden rather than shown empty. Sorting is shared across the
sections, so clicking a column heading sorts all three the same way and the
numbers stay readable straight down the page.

Each provider keeps a fixed colour — in its card, its section heading, and its
chart line — so the same hyperscaler is recognisable wherever it appears.

The page's data is embedded directly inside `docs/index.html` rather than
loaded from a separate file, because browsers block a local page from reading
another local file. Embedding is what lets it work by double-clicking, with no
server.
