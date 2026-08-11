# GPU price tracker

Records what Microsoft Azure, Google Cloud and Oracle publicly charge to rent a
GPU, once a day, and builds a local page from the result.

Cloud providers publish today's prices but not yesterday's, so no public price
history exists. **The archive is the point.** The page is the visible part, but
the reason to run this daily is that a day not collected is a day gone for good.

That premise turns out to be *almost* true — see [How much history there
is](#how-much-history-there-is). Azure quietly publishes years of its own.

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

## Coverage

Every region each provider publishes, not a sample:

| | regions collected | prices per snapshot |
|---|---|---|
| Azure | 59 | ~7,250 |
| Google Cloud | 44 | ~3,750 |
| Oracle | 1 (price is uniform worldwide) | 18 |

**Region matters more than it looks.** The same 8×H100 Azure machine is
$98.32/hr in `westus3` and $186.61/hr in `southafricawest` — a 90% spread for
identical hardware. H200 and GB200 spread about 100%. That is far wider than the
year-over-year drift this tracker exists to detect, so collecting one region
would have hidden the larger effect completely.

Collecting everything also turned out to be nearly free. Google's API has no
region parameter — one call always returns all 32,242 Compute Engine SKUs — so
every region was *already* in the raw archive and was simply being filtered out.
Widening it cost no extra requests and reprocessed the existing history.

A full run takes about 70 seconds and stores ~3.4 MB, so roughly 1.2 GB a year.

## How much history there is

Two different things, and the page keeps them apart:

| | source | reaches back to |
|---|---|---|
| **Azure** | **stated by Azure in its own feed** | **2018-09-04** |
| Google Cloud | observed by this tracker | the day you started |
| Oracle | observed by this tracker | the day you started |

**Azure publishes its own price history and it is easy to miss.** Every row
carries the window its price was in force for — `effectiveStartDate` and
`effectiveEndDate`. A row reading *"$98.32, effective from 2023-12-01, no end
date"* is Azure stating its own price on every day since December 2023. One pull
therefore yields years of history, reconstructed as a step function.

How far back each chip reaches, in Azure's US East:

| chip | since | | chip | since |
|---|---|---|---|---|
| V100 | 2018-09-04 | | H100 | 2023-12-01 |
| T4 | 2020-11-01 | | H200, GB200 | 2025-04-01 |
| A100 | 2021-03-01 | | MI300X | 2025-10-01 |
| A10 | 2022-04-01 | | RTX PRO 6000 | 2026-04-01 |

**Google and Oracle genuinely publish nothing.** Google's `effectiveTime` reads
today's date on all 32,242 SKUs and Oracle has a single feed-level
`lastUpdated`; both mean "when we recomputed this", not "when this price took
effect". Treating either as a validity date would invent a price change on the
day you happened to look, so both are left blank and their history starts when
you start collecting.

**Stated is not the same as observed**, and the page never blurs them. A hollow
marker is a price the provider *says* applied on that date; a filled marker is
one this tracker *saw* on the day. The detail chart draws a line where the
record changes hands. Stated history is not a guess — but it is Azure's word
rather than a measurement, and it can be revised. Observed history cannot.

Lines are drawn as **steps**, because a list price holds until the day it
changes; sloping between two known prices would draw a gradual drift that never
happened. A step *down* can mean a price cut **or** a cheaper machine arriving —
the tooltip names the machine behind every point so the two can be told apart.

### What the reconstructed history says so far

Azure retains one superseded period per meter, so it shows both sides of its
most recent repricing. Across 386 same-SKU/region/price-type changes:

- **214 decreases, 132 increases, 40 unchanged — median −7.6%**
- every one of them took effect on **2026-08-01**, a single repricing event
- for 30 of them it was the first change since **2023-05-01**

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
("GPU Standard - V2", "GPU - E3") rather than by chip, and to Azure machines
whose GPU count Microsoft does not publish — the `NCads_A10_v4` series (their
own Q&A confirms the docs lag), the undocumented RTX PRO 6000 sizes, plus FPGA,
media-accelerator and older graphics SKUs that are not AI parts at all.

GPU counts come from Microsoft's published size tables, cited in
`providers/azure.py` beside each block. Verifying them added GB200 (4 per VM),
MI300X (8), the nine documented RTX PRO 6000 sizes, and several H100/H200
feature-flag variants. Two independent checks fell out of it: Azure and Oracle
both list MI300X at exactly **$6.00**/GPU-hour, and H200 lands at $10.00
(Oracle), $10.44 (Google) and $10.60 (Azure).

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
effective from 2026-08-01 with no end date at $5.785718. Mistaking the retired
one for today's price reports a stale number, so the tables show only rows still
in force — but the retired rows are kept, because they are the history.

**Azure windows that end before they begin.** Forty rows come back effective
*from* 2026-08-01 *to* 2026-07-31, usually at a placeholder price like $0.002.
No day falls inside such a window, so they can never be a real price. Left in,
they sort to the front of a SKU's history and turn a $0.01 placeholder into the
"price before" an 85,000% increase. Dropped in `providers/azure.py`.

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
  back too. All 59 regions are collected in one paginated query (`REGIONS = None`
  in `providers/azure.py`; a list of names still works if the volume ever needs
  limiting). Azure prices the whole machine, so `GPU_COUNT` in that file is the
  hand-written table that turns a machine price into a per-GPU price.

  Left out on purpose: **Windows** rows (they bundle a Windows Server licence,
  so they measure licensing rather than the chip), **DevTestConsumption** (needs
  a special subscription), and **Low Priority** (Azure's deprecated pre-Spot
  tier, which would double-count preemptible pricing).
- **Google** — needs a free Cloud Billing API key, read from the
  `GCP_BILLING_KEY` environment variable or `~/.gcp_billing_key`. The key is
  never written into the repository or into the raw archive. Paginated via
  `nextPageToken`; `6F81-5844-456A` is the Compute Engine service id. All 44
  regions are kept (`REGIONS = None` in `providers/gcp.py`) — the API has no
  region parameter, so every region arrives in one call regardless.

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

**Three toggles run everything** — chip, price type and region. They apply to
every table and every chart at once; there is no second set of controls
anywhere. A search box narrows by SKU name on top of them.

The state lives in the URL, so the back button works and any view can be
bookmarked or shared.

**Region is a geography, not a raw region name.** The providers name regions
nothing alike — Azure `eastus2`, Google `us-east4`, Oracle not at all — so
picking a raw name would leave one provider on screen and hide the other two.
Regions are grouped into geographies (`REGION_GROUPS` in `build_page.py`) and
the toggle selects one. Oracle charges the same price everywhere, so its rows
belong to every geography rather than none.

**Two views:**

1. **Overview** (no chip selected) — a card per hyperscaler, then a section per
   hyperscaler with its own sortable table and its own collapsed list of SKUs
   left blank, then a grid of small per-chip charts.
2. **Detail** (a chip selected) — one large interactive chart for that chip with
   a crosshair that reads every provider at the same date, above the same
   provider tables narrowed to that chip.

Clicking a chart in the overview *is* selecting that chip, so the toggle and the
click are one mechanism rather than two ways of doing the same thing.

Charts show one line per provider: the cheapest per-GPU-hour it lists for that
chip in the selected geography. Picking the cheapest *within* a geography keeps
a line from jumping when a provider opens another datacentre nearby. With "all
price types" selected, the line is the lowest posted rate of any kind — a real
number, but one that mixes spot with committed terms, and the caption says so.

**The history is daily.** However many times `collect.py` runs in a day, that
day gets one point — the last run wins. Otherwise a re-run after a failure would
put several points on one date and make "change since last time" mean "change in
the last few minutes".

Each provider keeps a fixed colour across its card, its section heading and its
chart line. A dashed line marked "chip only" is a bare accelerator price, not
comparable with the solid lines.

The page's data is embedded directly inside `docs/index.html` rather than
loaded from a separate file, because browsers block a local page from reading
another local file. Embedding is what lets it work by double-clicking, with no
server.
