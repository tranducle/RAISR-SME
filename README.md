<div align="center">

# RAISR-SME

**R**apid **AI**-**S**ecurity **R**eadiness for **S**mall and **M**edium **E**nterprises

*A 25-item, six-dimension self-assessment instrument — and the public-data evidence behind it.*

![instrument](https://img.shields.io/badge/instrument-bank%20v1%20·%20frozen-orange)
![items](https://img.shields.io/badge/items-25%20in%206%20dimensions-orange)
![engines](https://img.shields.io/badge/engines-3%20·%20bit--for--bit%20parity-brightgreen)
![tests](https://img.shields.io/badge/tests-8%2F8%20passing-brightgreen)
![code](https://img.shields.io/badge/code-MIT-blue)
![instrument licence](https://img.shields.io/badge/instrument-CC%20BY%204.0-blue)

</div>

> [!IMPORTANT]
> **This repository is anonymised for peer review.** No author name, affiliation, institutional
> address, funder, or contact detail appears anywhere in it, by design. Attribution will be added
> when the paper is accepted.

---

## What this is

A small business that adopts an LLM assistant on Monday has changed its attack surface by Tuesday,
and has no practical way to find that out. Enterprise frameworks answer the question at a cost — in
hours, in vocabulary, in a consultant — that a nine-person firm does not have. **RAISR-SME** is a
twenty-minute, single-respondent questionnaire that returns one number on 0–100, a band, and a
ranked list of what to fix first.

This repository holds the two halves that a reader needs in order to check the work:

| | |
| --- | --- |
| 🧭 **The instrument** | The frozen item bank, plus three independent scoring engines that agree digit for digit, and the test suite that proves it. |
| 📊 **The analysis** | The scripts behind every estimate reported in the paper, run against public UK survey microdata, with their result files committed. |

**Higher score = more exposure**, not more maturity. This is the single most common misreading of
the instrument, so it is stated on the bank, in every engine, and on every result surface.

---

## The instrument at a glance

Six dimensions, 25 items, fixed weights, four bands.

| Dimension | Items | Weight | Reads |
| --- | :---: | :---: | --- |
| Security hygiene | 6 | **0.25** | Policy, training, insurance, backups, privileged accounts, monitoring |
| Incident readiness | 4 | **0.25** | Written plan, first-hour contact, rehearsal, exploited-vulnerability awareness |
| AI / LLM exposure | 4 | **0.15** | Any AI tool, generative AI, breadth of adoption, AI touching personal data |
| Data handling | 3 | **0.10** | Data policy, tested restore, knowing where the data actually lives |
| Governance & accountability | 5 | **0.15** | Named owner, annual review, written responsibilities, supplier checks, reporting route |
| Vendor dependence | 3 | **0.10** | Cloud dependence, software inventory, supplier security track record |

```text
0 ───────────────── 40 ───────── 65 ───── 85 ──── 100
      Low            Medium       High    Critical
```

Bands are **half-open**, `[lo, hi)`: a total of exactly 40.0 reads `Medium`.

### Two design choices that are easy to get wrong

**1. Polarity is per item, not global.** Twenty items are *gap* items — they carry risk when a
control is **absent** ("No" = 1.0). Five are *exposure* items — A1–A4 and V1 carry risk when the
exposure is **present** ("Yes" = 1.0). A single global `Yes = 0` mapping silently inverts the entire
AI-exposure dimension, which is exactly the defect corrected at the v1 freeze and recorded in
`freeze_record.fixes_at_freeze`.

**2. "Don't know" is half a point of risk, never a skip.** A firm that cannot answer whether it has
offline backups is, for the purpose of this instrument, in a materially worse position than one that
answers "yes" — and a better one than a firm that answers "no". Every score reports how many items
were answered `dk`, because a 55 resting on eight unknowns is a different object from a 55 resting
on none.

---

## Quick start

No dependencies, no data, no build step. Python 3.9+ only:

```bash
git clone <this repository>
cd RAISR-SME

# Score a worked example
python3 instrument/scoring.py --archetype solo-micro-no-governance

# Score your own answers
echo '{"H1": "no", "H2": "yes", "A1": "yes", "I1": "dk"}' | python3 instrument/scoring.py

# See every item, with its polarity
python3 instrument/scoring.py --list-items

# Prove the engines agree
python3 instrument/test_scoring.py
```

<details>
<summary><b>What the CLI prints</b></summary>

```text
Total 85.0/100   band Critical   (0 item(s) answered "don't know")

dimension                     score  weight  contrib  next step
Security hygiene              100.0    0.25     25.0  Immediate hygiene remediation sprint; external review.
Incident readiness            100.0    0.25     25.0  Run a tabletop exercise now; plug detected gaps.
Governance & accountability   100.0    0.15     15.0  Governance review with external support.
Data handling                 100.0    0.10     10.0  Data audit + breach-report readiness review.
Vendor dependence             100.0    0.10     10.0  Dependency review; contingency for key vendors.
AI/LLM exposure                 0.0    0.15      0.0  Inventory which AI tools staff actually use.

Higher is worse: the total is exposure, not maturity. The ordering above is a
presentation choice (weighted contribution); the instrument does not define one.
```

Every gap item failing, no AI in use — so AI/LLM exposure reads **0.0**, which is the standing
polarity check. If that line ever reads 100, the polarity has been re-broken.

The "next step" column is ranked by **weighted contribution** (`score × weight`). That ranking is a
presentation choice made by this implementation — the paper does not evaluate it, and the code says
so where it is computed.

</details>

---

## Three engines, one number

The instrument is scored in three independent places, and a reader is entitled to ask whether they
agree. They do, and it is checked rather than asserted:

| Engine | Where | Role |
| --- | --- | --- |
| `instrument/scoring.py` | this repo | Dependency-free reference implementation |
| `instrument/scoring.js` | this repo | Browser port, for interactive use |
| `analysis/instrument_validation.py` | this repo | The numpy engine that produced the paper's numbers |

```text
$ python3 instrument/test_scoring.py -n 20000 --seed 7

archetypes              ok    5 check(s)
polarity                ok    25 check(s)
band boundaries         ok    5 check(s)
monotonicity            ok    500 check(s)
don't know              ok    3 check(s)
input validation        ok    5 check(s)
parity vs scoring.js    ok    20000 check(s)
parity vs paper engine  ok    20000 check(s)

8 passed, 0 failed, 0 skipped
```

Parity against the JavaScript engine is **exact** — a bit comparison on IEEE-754 doubles, not a
tolerance. Parity against the numpy engine is within `1e-9`, with bands compared after quantisation.
When a dependency is unavailable (no Node, no numpy) the suite prints `SKIP … -- not a pass` and
never launders an absent check into a green line.

<details>
<summary><b>Why floating-point detail is load-bearing here</b></summary>

Three things in `scoring.py` look like they could be tidied and must not be:

1. **Order of operations.** A dimension score is `(sum(items) / n) * 100` — division first, matching
   `numpy.mean(...) * 100`. Rearranging to `sum * 100 / n` changes the last bit.
2. **Sequential addition, not `sum()`.** Since Python 3.12, the builtin `sum()` applies Neumaier
   compensated summation to floats. It is *more* accurate than adding left to right — and therefore
   disagrees with the two engines this one has to match. On 1,023 of 5,000 random response vectors
   the two totals differ in the last bits (`56.125` against `56.12499999999999`).
3. **Quantisation before the band lookup.** Because bands are half-open, that last-bit difference is
   not academic: across 50,000 random vectors, 83 land *exactly* on a cut point — about one
   respondent in 600. Totals are rounded to nine decimals before the band is read off.

Parity means reproducing the reference arithmetic, not improving on it.

</details>

---

## What the evidence says

Two arms, both on public UK microdata, both reported here with the direction they actually came out
in — including the one that failed.

### Arm 1 — cross-sectional criterion test (CSBS 2023–2025)

Weighted GLM Binomial: reported breach on core-score *z* + size + sector. The core score is a **gap**
score, so an odds ratio **below 1** means *more gaps, fewer reported breaches* — equivalently, better
hygiene, **more** reported breaches.

| Wave | n | OR per SD (weighted, controls) | 95% CI | p |
| --- | ---: | ---: | --- | ---: |
| 2023 | 3,970 | 0.879 | 0.786 – 0.983 | 0.024 |
| 2024 | 1,992 | 0.809 | 0.717 – 0.913 | 0.0006 |
| 2025 | 2,165 | 0.741 | 0.656 – 0.837 | 1.5 × 10⁻⁶ |

The plain-language version, from the 2025 wave: firms **with** a formal security policy report a
breach rate of **37.5%**; firms without, **18.3%**. The AUC of the gap score against reported
breaches is 0.383 — informative, and pointing the wrong way.

This is a **detection-and-reporting artefact**, not evidence that security policies cause breaches.
A firm with a policy has someone whose job is to notice, and a survey question can only count
breaches that were noticed. Reporting it as a finding rather than burying it is the point: any
posture score validated against self-reported incidents inherits this inversion.

### Arm 2 — panel test of lagged posture (CSLS waves 1–4)

Same-organisation panel, logits clustered by firm, plus a firm-fixed-effects linear probability
model. The question this arm exists to answer is whether the inversion survives when posture is
measured **before** the outcome.

| Specification | n | Estimate | 95% CI | p |
| --- | ---: | ---: | --- | ---: |
| Contemporaneous (full panel) | 3,061 | OR 1.195 | 1.077 – 1.325 | 0.0007 |
| Contemporaneous (lagged sample) | 1,935 | OR 1.155 | 1.000 – 1.334 | 0.050 |
| **Lagged, harmonised sample** | 1,344 | OR 0.971 | 0.858 – 1.100 | 0.64 |
| **Firm-FE (within-firm), LPM** | 1,344 | −1.1 pp | −2.25 – +0.09 pp | 0.070 |

The contemporaneous inversion reproduces. Once posture is lagged it **disappears**, and the
within-firm estimate points weakly protective without reaching conventional significance.

The null here is **bounded, not absolute**. At n = 1,344 and a 19.0% outcome rate, the design has
80% power for an OR of about 1.22 per SD — so it rules out the contemporaneous-sized inversion, and
does not rule out a small true effect in either direction.

> [!WARNING]
> **No estimate in Arm 2 is an SME estimate.** The CSLS frame covers medium (50–249) and large
> (250+) organisations only. What carries down to small firms is the *mechanism* — posture measured
> at the same moment as the outcome is contaminated by detection capability — not the coefficients.

### The hypothesis that failed

The pre-registered directional gate was an odds ratio of at least 1.3 per SD for lagged posture. The
observed lagged estimate is 0.971. **The gate was not met and the claim was withdrawn**, rather than
softened into a hedge. It is documented here for the same reason it is in the paper.

### Instrument mechanics

Verified in `analysis/results/instrument_validation.json`: monotonicity holds across the response
space; all five worked archetypes land in their intended bands (85.0 Critical → 32.2 Low); every
band boundary resolves upward as specified; every dimension has an action plan at every band.
Perturbing each weight by ±20% moves **at most one** archetype across a band cut point.

Reliability is reported honestly and is **not** a strength of the current evidence: the full 25-item
battery has never been fielded, so KR-20 can only be computed on the 4–6 CSBS items that map onto it
(0.53 on 4 items in 2023, n = 367; unstable on the 2024–25 6-item subsets, n = 24 and 25). The bank
records this as a known and accepted limit.

---

## Repository layout

```text
RAISR-SME/
├── instrument/
│   ├── bank_v1.json          # the frozen item bank — 25 items, weights, bands, action plans
│   ├── scoring.py            # reference engine + CLI (no dependencies)
│   ├── scoring.js            # browser port of the same arithmetic
│   ├── test_scoring.py       # 8 checks, incl. cross-engine parity
│   └── README.md             # bank schema, polarity, and how to extend it
├── analysis/
│   ├── csbs_common.py             # shared CSBS loading, weighting, item mapping
│   ├── arm1_cross_sectional.py    # Arm 1
│   ├── arm2_panel_lagged.py       # Arm 2
│   ├── instrument_validation.py   # coverage audit, reliability, mechanics, sensitivity
│   ├── auxiliary_analyses.py      # matched-pair and trend descriptives (secondary)
│   ├── results/*.json             # committed outputs of the four scripts above
│   ├── requirements.txt
│   └── README.md                  # how to re-run, and what each script emits
├── data/
│   └── README.md             # where to obtain every dataset (nothing is redistributed here)
├── CITATION.cff
└── LICENSE
```

---

## Data

**No microdata is included in this repository, and none can be.** The CSBS and CSLS files are
distributed by the UK Data Service under an End User Licence that forbids redistribution. Every
dataset is obtainable, free, by anyone: [`data/README.md`](data/README.md) lists each study number,
its catalogue URL, the file to download, and the SHA-256 of the file this analysis ran against, so a
replication can confirm it is holding the identical bytes.

| Source | What it supplies | Access |
| --- | --- | --- |
| UK Cyber Security Breaches Survey (SN 9404, 9285, 9101, 8971) | Arm 1 | UK Data Service, free registration + EUL |
| UK Cyber Security Longitudinal Survey (SN 9356, 9284, 9067, 8969) | Arm 2 | UK Data Service, free registration + EUL |
| Eurostat `isoc_eb_ai` | AI-adoption rates by size class | Open |
| CISA Known Exploited Vulnerabilities | Dated exposure snapshot | Open |

---

## What is deliberately not here

| Not included | Why |
| --- | --- |
| The manuscript and its figures | Under peer review; distributed by the venue. |
| Survey microdata | Licensed, non-redistributable (see above). |
| Drafts, internal notes, project bookkeeping | Working artefacts of writing the paper, not of reproducing it. |
| Absolute paths, machine names, build logs | Removed rather than published. |

---

## Reproducing the analysis

```bash
pip install -r analysis/requirements.txt
# obtain the microdata per data/README.md, then:
python3 analysis/arm1_cross_sectional.py
python3 analysis/arm2_panel_lagged.py
python3 analysis/instrument_validation.py
python3 analysis/auxiliary_analyses.py
```

Each writes to `analysis/results/`. The committed result files are the ones the paper reports; a
successful replication overwrites them with identical values. The instrument half — bank, engines,
tests — needs none of this and runs anywhere Python does.

---

## Limitations, stated once and plainly

- The 25-item bank has **not** been fielded as a battery. Its criterion evidence comes from the 3–6
  items that public surveys happen to carry.
- Arm 1 is cross-sectional and its headline is an artefact of measurement, reported as such.
- Arm 2 is a bounded null on medium and large organisations, not an SME result.
- Weights and band cut points are **pre-committed design decisions**, not estimated quantities. The
  ±20% sensitivity suite is reported beside them so a reader can see how much they matter.
- The action ranking is this implementation's presentation choice; nothing in the paper evaluates it.
- Nothing here is called novel, significant, or state-of-the-art.

---

## Licence

- **Code** — MIT. See [`LICENSE`](LICENSE).
- **Instrument** (`instrument/bank_v1.json`: item wording, dimensions, weights, bands, action plans)
  — **CC BY 4.0**. Use it, adapt it, field it; say where it came from.

Citation metadata is in [`CITATION.cff`](CITATION.cff), anonymised pending acceptance.
