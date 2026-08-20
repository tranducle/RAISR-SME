# Data — where to get it

**This directory ships no data, and cannot.** The two survey datasets the analysis runs on are
distributed by the UK Data Service under an End User Licence that forbids redistribution. What is
published here instead is everything needed to obtain the identical bytes: the study numbers, the
catalogue URLs, the exact file inside each archive, and its SHA-256.

Registration with the UK Data Service is **free** and open to anyone; the EUL is accepted online.
No special access, institutional affiliation, or application is required for these studies.

---

## 1. Cyber Security Breaches Survey (CSBS) — Arm 1

Repeated cross-section of UK businesses and charities, commissioned annually by the UK government.

| Study | Wave | Catalogue | Role |
| --- | --- | --- | --- |
| **SN 9404** | 2025 | <https://beta.ukdataservice.ac.uk/datacatalogue/studies/study?id=9404> | Primary criterion test |
| **SN 9285** | 2024 | <https://beta.ukdataservice.ac.uk/datacatalogue/studies/study?id=9285> | Validation wave |
| **SN 9101** | 2023 | <https://beta.ukdataservice.ac.uk/datacatalogue/studies/study?id=9101> | Replication wave |
| **SN 8971** | 2016–2022 combined | <https://beta.ukdataservice.ac.uk/datacatalogue/studies/study?id=8971> | Trend descriptives only |

> **SN 8971 carries no breach outcome.** The 2016–2022 combined edition is a banded-cost release:
> it has the hygiene and ransom items but not `Cybercrime_all`. It is therefore used for trend
> descriptives and never for criterion modelling. Attempting to pool it into Arm 1 is a mistake the
> code will not stop you from making.

## 2. Cyber Security Longitudinal Survey (CSLS) — Arm 2

A true panel — the same organisations re-interviewed across waves — from the same questionnaire
family as CSBS.

| Study | Wave | Catalogue | Role |
| --- | --- | --- | --- |
| **SN 9356** | 2024 (W4) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9356> | **Master panel file — the only one Arm 2 needs** |
| SN 9284 | 2023 (W3) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9284> | Per-wave slice |
| SN 9067 | 2022 (W2) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9067> | Per-wave slice |
| SN 8969 | 2021 (W1) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/8969> | Per-wave slice |

> **Download SN 9356 alone if you only want to reproduce Arm 2.** Its `csls_waves_1-4.dta` already
> contains all four waves (1,741 / 1,061 / 852 / 1,222 rows); the other three studies are slices of
> the same data. Panel key `LongId`, re-interview flag `if_longid`, weight `wght`, outcome
> `brk_outcome`.
>
> **Scope:** CSLS covers medium (50–249) and large (250+) organisations. It contains no SMEs in the
> small-firm sense, which is why Arm 2 reports a mechanism and not an SME point estimate.

## 3. Eurostat — AI adoption by enterprise size class

Open data, no registration. Byte-for-byte reproducible from the dissemination API:

```bash
mkdir -p data/eurostat
curl -o data/eurostat/isoc_eb_ai.json \
  "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/isoc_eb_ai?format=JSON&lang=EN"
```

Dataset DOI `10.2908/isoc_eb_ai` — *Artificial intelligence by size class of enterprise*,
browsable at <https://ec.europa.eu/eurostat/databrowser/product/page/ISOC_EB_AI>.

The response is a live JSON-stat cube and **is republished by Eurostat as the series is revised**,
so a later download will not match the checksum below. The `updated` field inside the file records
the vintage; the one used here is `2026-06-15`.

## 4. CISA Known Exploited Vulnerabilities

Open data, no registration: <https://www.cisa.gov/known-exploited-vulnerabilities-catalog>
(JSON feed at <https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json>).

Used only for the two dated anchors on items `I4` and `V3` in the item bank — a **snapshot** of
2026-08-17 (1,666 entries), deliberately not a live count, so the figures in the bank do not silently
disagree with the paper the day after it was written.

---

## Where to put the files

Unzip each UKDS archive directly into this directory. Each expands into its own `UKDA-<SN>-stata/`
folder and the analysis scripts read from that layout unchanged:

```text
data/
├── UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta
├── UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta
├── UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta
├── UKDA-8971-stata/stata/stata13/dcms_csbs_combined_2016-2022_banded_cost_data_only_v3_public.dta
├── UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta
├── UKDA-9284-stata/stata/stata13/csls_wave3_only_26july2024.dta
├── UKDA-9067-stata/stata/stata13/j21_079643_wave2_only_16aug2022_with_ids.dta
├── UKDA-8969-stata/stata/stata13/csls_public_dataset_wave_1.dta
└── eurostat/isoc_eb_ai.json
```

Choose the **STATA (.dta)** distribution, not SPSS or tab-delimited. It is the only format that both
reads with this stack (`pandas.read_stata`, no extra dependency) and preserves the survey's value
labels, which the item-coverage audit in `analysis/instrument_validation.py` matches on by label.

## Verifying you have the same data

```bash
cd data && shasum -a 256 -c CHECKSUMS.sha256
```

| File | SHA-256 |
| --- | --- |
| `csbs_2025_archive_data_public.dta` | `6e796f0023d76f2b8b4b9ded2fef97249e0e8bdf7d09638eeb66603e3eb980d7` |
| `csbs_2024_archive_data_public.dta` | `de7238376d47828a09d61fe5955547616808d6483ebfc96a80c115a0567763df` |
| `csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta` | `80d0589968faf08d8b6e81d85fc1f8a0baab2de1f0ef168c59929d48d5ca5f81` |
| `dcms_csbs_combined_2016-2022_banded_cost_data_only_v3_public.dta` | `e80c2ae670f524076037d61cb0a8cbf779e6c7bd3884e201bc48d52af8febf13` |
| `csls_waves_1-4.dta` | `ef4632c26fb1a02c3278bafb707ee11c1a8acb26c7a33d7c2dedcc272c71a306` |
| `csls_wave3_only_26july2024.dta` | `698734744dbb01a4de5a590d4f2ecc1c02e0f3267f8b106b91b98a15abe1237e` |
| `j21_079643_wave2_only_16aug2022_with_ids.dta` | `d9d52f150b390e45299ae938b5cb7b85a5d42086afaf11b3a01cfaa01e38f299` |
| `csls_public_dataset_wave_1.dta` | `e567fed426e1aa9cc6a4d6e022efce3d02b2b6ee4a676f8cc7fc2a8d0f14572f` |
| `eurostat/isoc_eb_ai.json` (vintage 2026-06-15) | `5c8d7f499bc36b74cbc2e8598fdff24e5c51087cffd99d0c829d2b12da95f9a7` |

A checksum mismatch on a UKDS file means the study has been re-released under a new version — check
the catalogue page for the edition, and expect estimates to move.

## Two things that will bite a replication

1. **Weights are per wave.** Each CSBS wave carries its own weight variable; pooling waves requires
   per-wave weights *and* year fixed effects, not a single pooled weight.
2. **CSBS changed mode in 2020**, face-to-face to online. Any trend statement crossing that year
   inherits a mode break, and the trend descriptives in `auxiliary_analyses.py` are reported as
   descriptives for exactly that reason.
