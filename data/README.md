# Data: Where to Obtain Archival Sources (`RAISR-SME`, ICIIT 2027)

**This directory ships no licensed survey microdata, and cannot.** The two United Kingdom government enterprise survey series analyzed in Arm B (`exp1` through `exp3`) are distributed by the UK Data Service under an End User Licence (EUL) that prohibits public redistribution of respondent-level files. What is published here instead is everything needed to obtain the identical bytes: study numbers, official catalogue URLs, exact file paths inside each archive, and SHA-256 checksums (`CHECKSUMS.sha256`).

Registration with the UK Data Service is free and open to researchers; the EUL is accepted online.

## 1. UK Cyber Security Breaches Survey (CSBS, Arm B Cross-Sections: `exp1`, `exp3`, and `exp4` Marginals)

Repeated cross-sections of UK businesses, charities, and education institutions commissioned annually by the UK government (`N = 8,086` complete-case business interviews pooled across 2023 to 2025 in `exp3`; `11,260` raw business records audited in `exp1`).

| Study | Wave | Catalogue URL | Role in ICIIT 2027 Suite |
| :- | :- | :- | :- |
| **SN 9404** | 2025 | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9404> | Primary cross-sectional wave (`n = 2,165` businesses) and `exp4` item prevalences |
| **SN 9285** | 2024 | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9285> | Cross-sectional wave (`n = 1,992` businesses) and 8-item unrouted check |
| **SN 9101** | 2023 | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9101> | Cross-sectional wave (`n = 3,929` businesses) and skip-routing audit |
| **SN 8971** | 2016 to 2022 combined | <https://datacatalogue.ukdataservice.ac.uk/studies/study/8971> | Historical trend descriptives only (carries no `Cybercrime_all` breach outcome) |

> **Important:** `SN 8971` (2016 to 2022 combined banded-cost release) contains hygiene and ransom items without `Cybercrime_all` and is never pooled into breach regressions (`exp1` through `exp3`).

## 2. UK Cyber Security Longitudinal Survey (CSLS, Arm B Multi-Wave Panel: `exp1`, `exp2`, `exp3`)

Longitudinal enterprise panel (`>= 50` employees) re-interviewing organizations across Waves 1 to 4 (`N = 3,061` complete-case business records across `2,196` unique organizations; `n = 865` genuine consecutive annual transitions across `575` non-empty `LongId` firms after separating `482` empty-string `LongId == ""` Wave-4 Fresh single-wave businesses).

| Study | Wave | Catalogue URL | Role in ICIIT 2027 Suite |
| :- | :- | :- | :- |
| **SN 9356** | Waves 1 to 4 Master | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9356> | **Master panel file required by `exp1`, `exp2`, and `exp3`** |
| SN 9284 | 2023 (Wave 3) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9284> | Per-wave archive slice (optional provenance checksum) |
| SN 9067 | 2022 (Wave 2) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/9067> | Per-wave archive slice (optional provenance checksum) |
| SN 8969 | 2021 (Wave 1) | <https://datacatalogue.ukdataservice.ac.uk/studies/study/8969> | Per-wave archive slice (optional provenance checksum) |

> **Scope boundary:** UK CSLS covers medium (`50` to `249` employees) and large (`250+` employees) organizations and contains zero micro (`1` to `9`) or small (`10` to `49`) enterprises.

## 3. Eurostat Enterprise AI Adoption (`isoc_eb_ai`, Arm A Anchor: `exp4`)

Open data, no registration required. Dataset DOI `10.2908/ISOC_EB_AI` (*Artificial intelligence by size class of enterprise*, <https://ec.europa.eu/eurostat/databrowser/product/page/ISOC_EB_AI>):

```bash
mkdir -p data/eurostat
curl -o data/eurostat/isoc_eb_ai.json \
  "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/isoc_eb_ai?format=JSON&lang=EN"
```

Because Eurostat revises live JSON-stat cubes over time, `CHECKSUMS.sha256` records the exact `2026-06-15` vintage used in `exp4_sensitivity_and_worked_examples.py` (2025 EU27 `E_AI_TANY`: `17.00%` small `10` to `49`, `30.36%` medium `50` to `249`, `55.03%` large `250+`).

## 4. Normative Security Catalogs (NIST CSF 2.0, NIST AI RMF 1.0, CISA CPGs & KEV)

- **NIST CSF 2.0 Subcategory Catalog**: Vendored directly at `../analysis/catalogs_nist_csf_2_0.csv` (`106` active subcategories) and verified deterministically against `../instrument/nist_csf2_crosswalk.json` (`26` unique IDs across `25` items) via `../analysis/verify_ids.py`.
- **CISA Known Exploited Vulnerabilities (KEV)**: Open catalog (<https://www.cisa.gov/known-exploited-vulnerabilities-catalog>); items `I4` and `V3` reference the dated snapshot of `2026-08-17` (`1,666` exploited entries).

## Expected Directory Layout for Full Local Reruns

Place extracted Stata `.dta` distributions (not SPSS or tab-delimited, so `pandas.read_stata` preserves value labels) and `eurostat/isoc_eb_ai.json` under `data/` (either inside `artifact_repo/data/` or at the parent workspace `../data/`, which `exp1..exp4.py` auto-detect):

```text
data/
  UKDA-9404-stata/stata/stata13/csbs_2025_archive_data_public.dta
  UKDA-9285-stata/stata/stata13/csbs_2024_archive_data_public.dta
  UKDA-9101-stata/stata/stata13/csbs_2023_22-034904-01_banded_cost_data_v6-1_public.dta
  UKDA-8971-stata/stata/stata13/dcms_csbs_combined_2016-2022_banded_cost_data_only_v3_public.dta
  UKDA-9356-stata/stata/stata13/csls_waves_1-4.dta
  UKDA-9284-stata/stata/stata13/csls_wave3_only_26july2024.dta
  UKDA-9067-stata/stata/stata13/j21_079643_wave2_only_16aug2022_with_ids.dta
  UKDA-8969-stata/stata/stata13/csls_public_dataset_wave_1.dta
  eurostat/isoc_eb_ai.json
```

Verify exact byte integrity with:

```bash
cd data && shasum -a 256 -c CHECKSUMS.sha256
```

## Key Replication Precautions Verified in `exp1` to `exp3`

1. **Questionnaire skip-routing vs respondent `DK`**: Split-ballot (`policy_comb`, `govtact_comb3`), breach-contingent (`reportb17`), sector-contingent (`scheme10`), and unlabeled `-1` (`corprisk`) skips must be separated from respondent `Don't know` (including curly apostrophes) before complete-case filtering (`exp1_formative_and_missingness.py`).
2. **Empty-string `LongId` in CSLS Wave 4**: In `csls_waves_1-4.dta`, `482` single-wave Wave-4 Fresh business interviews carry `LongId == ""` rather than `NaN`; `exp2_common_sample_and_mechanisms.py` assigns each Fresh record a unique cluster ID in full-panel models (`N = 3,061`, `2,196` firms) and restricts lag/within-firm transitions strictly to non-empty `LongId` rows (`n = 865`, `575` firms).
